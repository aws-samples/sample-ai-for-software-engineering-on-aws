// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// cc1-bench: the bench's tools inside the emulated CC-1 (build plan item 3). Synthetic, written for the sample.
// Every time is the guest's monotonic clock, which runs on QEMU's instruction counter (CC1-PN §2.2), so a replay is
// repeatable.
//
//   cc1-bench player  --socket <path> --drive <file> --end-marker <file> [--connected-marker <file>]
//       Plays cc1-gwd: listens on the gateway socket, plays the drive when vstatd connects (VSTATD-IF §2), sends a
//       heartbeat every 100 ms (§2.4). At END it writes the end-of-drive marker and keeps repeating each message's
//       last frame at its cycle, so that nothing in the log depends on how fast the bench stops vstatd afterwards.
//   cc1-bench clients --socket <path> --anchor <file> [--count 16] [--first-ms 1200] [--step-ms 20]
//                     [--interval-ms 100] [--sub <path>]...
//       The replay's cockpit apps: wait for the player's connected marker, connect one at a time at fixed offsets
//       (CC1-PN §2.2), subscribe, and keep reading so that no queue fills. Prints a summary on SIGTERM.
//   cc1-bench wait --file <path> --timeout-s <n>
//   cc1-bench figures <pid>       VmHWM, threads and CPU time of a process, as JSON (CC1-PN §3, §8.5)
//   cc1-bench finish --pid <pid> --end-marker <file>   at the end of the drive: figures, then SIGTERM to vstatd
//
// Drive file: one directive per line, '#' starts a comment.
//   CYCLE <can_id hex> <ms>                 cycle of a message, for the frames repeated after END
//   F <t_us> <can_id hex> <dlc> <data hex>  a frame, t_us after the current connection was accepted
//   DROP <t_us>                             close the connection (gateway loss); times restart at the next accept
//   END <t_us>                              end of the drive
#include <grp.h>
#include <sys/inotify.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>
#include <sys/types.h>

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace {

volatile sig_atomic_t g_stop = 0;
void on_signal(int) { g_stop = 1; }

void install_handlers() {
  struct sigaction sa {};
  sa.sa_handler = on_signal;
  sigemptyset(&sa.sa_mask);
  sa.sa_flags = 0;  // no SA_RESTART: accept() and sleeps return on SIGTERM
  sigaction(SIGTERM, &sa, nullptr);
  sigaction(SIGINT, &sa, nullptr);
  signal(SIGPIPE, SIG_IGN);
}

int64_t now_us() {
  timespec ts {};
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return static_cast<int64_t>(ts.tv_sec) * 1000000 + ts.tv_nsec / 1000;
}

// Sleeps until t (monotonic, microseconds). Returns false when interrupted by SIGTERM.
bool sleep_until_us(int64_t t) {
  timespec ts {};
  ts.tv_sec = static_cast<time_t>(t / 1000000);
  ts.tv_nsec = static_cast<long>((t % 1000000) * 1000);
  while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, nullptr) == EINTR) {
    if (g_stop) return false;
  }
  return !g_stop;
}

bool send_all(int fd, const std::string& s) {
  size_t off = 0;
  while (off < s.size()) {
    ssize_t n = send(fd, s.data() + off, s.size() - off, MSG_NOSIGNAL);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) return false;
    off += static_cast<size_t>(n);
  }
  return true;
}

struct Args {
  std::map<std::string, std::string> one;
  std::vector<std::string> subs;
  std::vector<std::string> positional;
};

Args parse_args(int argc, char** argv, int first) {
  Args a;
  for (int i = first; i < argc; ++i) {
    std::string k = argv[i];
    if (k.rfind("--", 0) == 0 && i + 1 < argc) {
      std::string v = argv[++i];
      if (k == "--sub") a.subs.push_back(v); else a.one[k] = v;
    } else {
      a.positional.push_back(k);
    }
  }
  return a;
}

std::string need(const Args& a, const std::string& k) {
  auto it = a.one.find(k);
  if (it == a.one.end()) {
    std::fprintf(stderr, "cc1-bench: missing %s\n", k.c_str());
    std::exit(2);
  }
  return it->second;
}

long opt_long(const Args& a, const std::string& k, long dflt) {
  auto it = a.one.find(k);
  return it == a.one.end() ? dflt : std::stol(it->second);
}

// ---- drive file ----

struct Event {
  enum Kind { Frame, Drop, End } kind;
  int64_t t_us;
  uint32_t can_id;
  std::string text;  // "<can_id> <dlc> <data>" as sent
};

struct Drive {
  std::map<uint32_t, int64_t> cycle_us;
  std::vector<std::vector<Event>> segments;
};

[[noreturn]] void drive_error(int line, const std::string& msg) {
  std::fprintf(stderr, "cc1-bench: drive line %d: %s\n", line, msg.c_str());
  std::exit(2);
}

Drive load_drive(const std::string& path) {
  std::ifstream in(path);
  if (!in) {
    std::fprintf(stderr, "cc1-bench: cannot read %s\n", path.c_str());
    std::exit(2);
  }
  Drive d;
  d.segments.emplace_back();
  bool ended = false;
  int64_t last_t = -1;
  std::string line;
  int n = 0;
  while (std::getline(in, line)) {
    ++n;
    auto hash = line.find('#');
    if (hash != std::string::npos) line.erase(hash);
    std::istringstream ss(line);
    std::string word;
    if (!(ss >> word)) continue;
    if (ended) drive_error(n, "directive after END");
    if (word == "CYCLE") {
      std::string id;
      long ms = 0;
      if (!(ss >> id >> ms) || ms <= 0) drive_error(n, "CYCLE <can_id> <ms>");
      d.cycle_us[static_cast<uint32_t>(std::stoul(id, nullptr, 16))] = static_cast<int64_t>(ms) * 1000;
      continue;
    }
    int64_t t = 0;
    if (!(ss >> t) || t < 0) drive_error(n, "missing time");
    if (t < last_t) drive_error(n, "times must not go backwards within a connection");
    last_t = t;
    if (word == "F") {
      std::string id, dlc, data;
      if (!(ss >> id >> dlc >> data)) drive_error(n, "F <t_us> <can_id> <dlc> <data>");
      uint32_t cid = static_cast<uint32_t>(std::stoul(id, nullptr, 16));
      if (data.size() != 2 * std::stoul(dlc)) drive_error(n, "data length does not match dlc");
      if (!d.cycle_us.count(cid)) drive_error(n, "no CYCLE for this CAN ID");
      d.segments.back().push_back({Event::Frame, t, cid, id + " " + dlc + " " + data});
    } else if (word == "DROP") {
      d.segments.back().push_back({Event::Drop, t, 0, ""});
      d.segments.emplace_back();
      last_t = -1;
    } else if (word == "END") {
      d.segments.back().push_back({Event::End, t, 0, ""});
      ended = true;
    } else {
      drive_error(n, "unknown directive " + word);
    }
  }
  if (!ended) drive_error(n, "no END");
  return d;
}

// Blocks until path exists, without polling: a busy wait would take guest CPU from vstatd and move its timing.
// Watches the parent directory, and the grandparent until the parent exists. Returns false on timeout or SIGTERM.
bool wait_created(const std::string& path, int64_t timeout_us) {
  const std::string dir = path.substr(0, path.rfind('/'));
  const std::string parent = dir.substr(0, dir.rfind('/'));
  const int64_t end = now_us() + timeout_us;
  int fd = inotify_init1(IN_CLOEXEC);
  if (fd < 0) return false;
  int wd_dir = -1;
  // IN_ATTRIB too: systemd creates a RuntimeDirectory and then sets its owner and mode, and the watch on it can only
  // be added once this user may read it.
  inotify_add_watch(fd, parent.empty() ? "/" : parent.c_str(), IN_CREATE | IN_MOVED_TO | IN_ATTRIB);
  bool ok = false;
  while (!g_stop) {
    if (wd_dir < 0 && access(dir.c_str(), F_OK) == 0) wd_dir = inotify_add_watch(fd, dir.c_str(), IN_CREATE | IN_MOVED_TO);
    if (access(path.c_str(), F_OK) == 0) { ok = true; break; }
    const int64_t left = end - now_us();
    if (left <= 0) break;
    pollfd p {fd, POLLIN, 0};
    // A watch that could not be added yet is retried on the next event; the 1 s cap is only a backstop.
    int r = poll(&p, 1, static_cast<int>(std::min<int64_t>(left / 1000 + 1, 1000)));
    if (r > 0) {
      char buf[4096];
      if (read(fd, buf, sizeof(buf)) < 0 && errno != EINTR) break;
    }
  }
  close(fd);
  return ok;
}

// ---- player ----

int listen_on(const std::string& path) {
  int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  sockaddr_un addr {};
  addr.sun_family = AF_UNIX;
  if (path.size() >= sizeof(addr.sun_path)) return -1;
  std::memcpy(addr.sun_path, path.c_str(), path.size() + 1);
  unlink(path.c_str());
  if (fd < 0 || bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0 || listen(fd, 1) != 0) return -1;
  // vstatd runs as vstat (CC1-PN §1.2) and connects as a client.
  if (group* g = getgrnam("vstat")) {
    if (chown(path.c_str(), 0, g->gr_gid) != 0) return -1;
  }
  if (chmod(path.c_str(), 0660) != 0) return -1;
  return fd;
}

bool write_marker(const std::string& path, const std::string& text) {
  std::string tmp = path + ".tmp";
  FILE* f = std::fopen(tmp.c_str(), "w");
  if (!f) return false;
  std::fputs(text.c_str(), f);
  bool ok = std::fclose(f) == 0;
  return ok && std::rename(tmp.c_str(), path.c_str()) == 0;
}

int player(const Args& a) {
  Drive d = load_drive(need(a, "--drive"));
  const std::string marker = need(a, "--end-marker");
  int lfd = listen_on(need(a, "--socket"));
  if (lfd < 0) {
    std::perror("cc1-bench player: gateway socket");
    return 1;
  }
  const int64_t gw0 = now_us();  // the gateway's start: base of every record's t_us (VSTATD-IF §2.2)
  std::map<uint32_t, int64_t> last_sent;  // CAN ID -> scheduled time of its last frame
  std::map<uint32_t, std::string> last_text;
  for (size_t s = 0; s < d.segments.size(); ++s) {
    int c = accept4(lfd, nullptr, nullptr, SOCK_CLOEXEC);
    if (c < 0) {
      if (g_stop) return 0;
      std::perror("cc1-bench player: accept");
      return 1;
    }
    const int64_t t0 = now_us();
    int64_t next_hb = t0 + 100000;
    // The first connection comes after SERVICE_READY (VSTATD-IF §8.1): the replay's clients start from here.
    if (s == 0 && a.one.count("--connected-marker") && !write_marker(a.one.at("--connected-marker"), "{}\n")) {
      std::perror("cc1-bench player: connected marker");
      return 1;
    }
    std::printf("cc1-bench player: connection %zu accepted\n", s + 1);
    std::fflush(stdout);
    for (const Event& ev : d.segments[s]) {
      const int64_t due = t0 + ev.t_us;
      while (next_hb <= due) {
        if (!sleep_until_us(next_hb)) return 0;
        if (!send_all(c, "H " + std::to_string(next_hb - gw0) + "\n")) {
          std::fprintf(stderr, "cc1-bench player: vstatd closed the gateway connection\n");
          return 1;
        }
        next_hb += 100000;
      }
      if (!sleep_until_us(due)) return 0;
      if (ev.kind == Event::Frame) {
        if (!send_all(c, "F " + std::to_string(due - gw0) + " " + ev.text + "\n")) {
          std::fprintf(stderr, "cc1-bench player: vstatd closed the gateway connection\n");
          return 1;
        }
        last_sent[ev.can_id] = due;
        last_text[ev.can_id] = ev.text;
      } else if (ev.kind == Event::Drop) {
        close(c);
        std::printf("cc1-bench player: connection %zu closed (gateway loss)\n", s + 1);
        std::fflush(stdout);
        last_sent.clear();
        last_text.clear();
        break;
      } else {
        std::ostringstream m;
        m << "{\"end_of_drive\":true,\"connections\":" << d.segments.size() << ",\"t_us\":" << ev.t_us << "}\n";
        if (!write_marker(marker, m.str())) {
          std::perror("cc1-bench player: end-of-drive marker");
          return 1;
        }
        std::printf("cc1-bench player: end of drive\n");
        std::fflush(stdout);
        // Hold: repeat each message's last frame at its cycle, and the heartbeat, until the bench stops us.
        std::map<uint32_t, int64_t> next;
        for (const auto& kv : last_sent) next[kv.first] = kv.second + d.cycle_us.at(kv.first);
        while (!g_stop) {
          int64_t t = next_hb;
          uint32_t which = 0;
          bool frame = false;
          for (const auto& kv : next) {
            if (kv.second < t) { t = kv.second; which = kv.first; frame = true; }
          }
          if (!sleep_until_us(t)) break;
          std::string out = frame ? "F " + std::to_string(t - gw0) + " " + last_text[which] + "\n"
                                  : "H " + std::to_string(t - gw0) + "\n";
          if (!send_all(c, out)) break;  // vstatd stopped
          if (frame) next[which] += d.cycle_us.at(which); else next_hb += 100000;
        }
        close(c);
        return 0;
      }
    }
  }
  return 0;
}

// ---- clients ----

int connect_to(const std::string& path) {
  int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  sockaddr_un addr {};
  addr.sun_family = AF_UNIX;
  std::memcpy(addr.sun_path, path.c_str(), std::min(path.size() + 1, sizeof(addr.sun_path) - 1));
  if (fd < 0 || connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
    if (fd >= 0) close(fd);
    return -1;
  }
  return fd;
}

struct Pump {
  std::vector<int> fds;
  long lines = 0;
  int closed = 0;
  // Reads every open connection until the deadline (monotonic us), or until SIGTERM when deadline < 0.
  void until(int64_t deadline) {
    char buf[4096];
    while (!g_stop) {
      int64_t now = now_us();
      if (deadline >= 0 && now >= deadline) return;
      std::vector<pollfd> p;
      for (int fd : fds) if (fd >= 0) p.push_back({fd, POLLIN, 0});
      int wait_ms = deadline < 0 ? 100 : static_cast<int>((deadline - now + 999) / 1000);
      if (p.empty()) {
        if (deadline < 0) { sleep_until_us(now + 100000); continue; }
        sleep_until_us(deadline);
        return;
      }
      int r = poll(p.data(), p.size(), wait_ms);
      if (r <= 0) continue;
      for (auto& q : p) {
        if (!(q.revents & (POLLIN | POLLHUP | POLLERR))) continue;
        ssize_t n = read(q.fd, buf, sizeof(buf));
        if (n > 0) {
          for (ssize_t i = 0; i < n; ++i) if (buf[i] == '\n') ++lines;
        } else if (n == 0 || (errno != EINTR && errno != EAGAIN)) {
          for (int& fd : fds) if (fd == q.fd) { close(fd); fd = -1; ++closed; }
        }
      }
    }
  }
};

int clients(const Args& a) {
  const std::string path = need(a, "--socket");
  const long count = opt_long(a, "--count", 16);
  const long first_ms = opt_long(a, "--first-ms", 1200);
  const long step_ms = opt_long(a, "--step-ms", 20);
  const long interval_ms = opt_long(a, "--interval-ms", 100);
  std::vector<std::string> subs = a.subs;
  if (subs.empty()) {
    subs = {"Vehicle.Speed", "Vehicle.Powertrain.Transmission.SelectedGear",
            "Vehicle.Powertrain.TractionBattery.StateOfCharge.Displayed", "Vehicle.Exterior.AirTemperature"};
  }
  // Start from the gateway connection, which vstatd makes only after SERVICE_READY (VSTATD-IF §8.1), so that its IPC
  // thread already accepts; the player marks it. No probe connection to vstatd: it would be a client in the log.
  if (!wait_created(need(a, "--anchor"), 3600LL * 1000000)) return g_stop ? 0 : 1;
  const int64_t t0 = now_us();
  Pump pump;
  int connected = 0;
  for (long i = 0; i < count && !g_stop; ++i) {
    pump.until(t0 + (first_ms + i * step_ms) * 1000);
    int fd = connect_to(path);
    if (fd < 0) {
      std::fprintf(stderr, "cc1-bench clients: client %ld could not connect: %s\n", i + 1, std::strerror(errno));
      continue;
    }
    std::string req;
    for (const auto& s : subs) req += "SUB " + s + " " + std::to_string(interval_ms) + "\n";
    if (!send_all(fd, req)) std::fprintf(stderr, "cc1-bench clients: client %ld: send failed\n", i + 1);
    pump.fds.push_back(fd);
    ++connected;
  }
  pump.until(-1);
  std::printf("{\"clients\":%ld,\"connected\":%d,\"subscriptions_each\":%zu,\"lines\":%ld,\"closed_by_vstatd\":%d}\n",
              count, connected, subs.size(), pump.lines, pump.closed);
  return connected == count ? 0 : 1;
}

// ---- wait, figures ----

int wait_file(const Args& a) {
  const std::string path = need(a, "--file");
  if (!wait_created(path, opt_long(a, "--timeout-s", 60) * 1000000)) {
    std::fprintf(stderr, "cc1-bench wait: %s did not appear\n", path.c_str());
    return 1;
  }
  return 0;
}

bool figures_json(const std::string& pid, std::string& out) {
  long hwm = -1, threads = -1;
  std::ifstream st("/proc/" + pid + "/status");
  std::string line;
  while (std::getline(st, line)) {
    std::istringstream ss(line);
    std::string key;
    long v = 0;
    ss >> key >> v;
    if (key == "VmHWM:") hwm = v;
    if (key == "Threads:") threads = v;
  }
  std::ifstream stat("/proc/" + pid + "/stat");
  std::string all((std::istreambuf_iterator<char>(stat)), std::istreambuf_iterator<char>());
  auto rp = all.rfind(')');
  long cpu_ms = -1;
  if (rp != std::string::npos) {
    std::istringstream ss(all.substr(rp + 2));
    std::vector<std::string> f;
    std::string w;
    while (ss >> w) f.push_back(w);
    if (f.size() > 12) {  // f[0] is field 3 (state); utime is field 14, stime field 15
      long ticks = std::stol(f[11]) + std::stol(f[12]);
      cpu_ms = ticks * 1000 / sysconf(_SC_CLK_TCK);
    }
  }
  if (hwm < 0 || threads < 0 || cpu_ms < 0) return false;
  out = "{\"vm_hwm_kib\":" + std::to_string(hwm) + ",\"threads_at_end\":" + std::to_string(threads) +
        ",\"cpu_ms\":" + std::to_string(cpu_ms) + "}";
  return true;
}

int figures(const Args& a) {
  std::string out;
  if (a.positional.size() != 1 || !figures_json(a.positional[0], out)) {
    std::fprintf(stderr, "cc1-bench figures: no figures\n");
    return 1;
  }
  std::printf("%s\n", out.c_str());
  return 0;
}

// Waits for the end-of-drive marker, reads the figures at once and then sends SIGTERM to vstatd, so that the end of the
// run and SERVICE_STOP come at a repeatable guest time (CC1-PN §8.5: figures after the end, before the stop).
int finish(const Args& a) {
  const std::string marker = need(a, "--end-marker");
  const pid_t pid = static_cast<pid_t>(std::stol(need(a, "--pid")));
  if (!wait_created(marker, opt_long(a, "--timeout-s", 3600) * 1000000)) {
    std::fprintf(stderr, "cc1-bench finish: no end of drive\n");
    return 1;
  }
  // Read the marker now: the player exits once vstatd is gone, and its runtime directory goes with it.
  std::ifstream m(marker);
  std::string end_json((std::istreambuf_iterator<char>(m)), std::istreambuf_iterator<char>());
  while (!end_json.empty() && (end_json.back() == '\n' || end_json.back() == ' ')) end_json.pop_back();
  std::string figs;
  if (end_json.empty() || !figures_json(std::to_string(pid), figs)) {
    std::fprintf(stderr, "cc1-bench finish: no figures\n");
    return 1;
  }
  if (kill(pid, SIGTERM) != 0) {
    std::perror("cc1-bench finish: SIGTERM");
    return 1;
  }
  std::printf("{\"end\":%s,\"figures\":%s}\n", end_json.c_str(), figs.c_str());
  return 0;
}
}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: cc1-bench player|clients|wait|figures ...\n");
    return 2;
  }
  install_handlers();
  const std::string cmd = argv[1];
  Args a = parse_args(argc, argv, 2);
  if (cmd == "player") return player(a);
  if (cmd == "clients") return clients(a);
  if (cmd == "wait") return wait_file(a);
  if (cmd == "figures") return figures(a);
  if (cmd == "finish") return finish(a);
  std::fprintf(stderr, "cc1-bench: unknown command %s\n", cmd.c_str());
  return 2;
}
