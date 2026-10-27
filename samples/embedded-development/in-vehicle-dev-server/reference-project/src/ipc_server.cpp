// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include "ipc_server.h"

#include <cerrno>
#include <cstring>

#include <fcntl.h>
#include <grp.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace vstatd {

namespace {

constexpr int kPollMs = 5;
constexpr int kBacklog = 16;

bool readable(const pollfd& p) { return (p.revents & (POLLIN | POLLHUP | POLLERR)) != 0; }

bool writable(const pollfd& p) { return (p.revents & POLLOUT) != 0; }

}  // namespace

IpcServer::IpcServer(const Config& config, SignalTable& table, LogWriter& log)
    : config_(config), table_(table), log_(log) {
    for (std::size_t i = 0; i < kSignalCount; ++i) {
        published_[i].value = table_.get(i);
    }
}

IpcServer::~IpcServer() {
    stop();
    if (wake_rd_ >= 0) {
        ::close(wake_rd_);
    }
    if (wake_wr_ >= 0) {
        ::close(wake_wr_);
    }
}

bool IpcServer::open_listener() {
    const std::string& path = config_.ipc_socket();
    int listen_fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (listen_fd < 0) {
        return false;
    }
    // A socket file left by a previous run of the service.
    if (::unlink(path.c_str()) != 0 && errno != ENOENT) {
        return false;
    }
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    if (path.size() >= sizeof(addr.sun_path)) {
        close(listen_fd);
        return false;
    }
    std::memcpy(addr.sun_path, path.c_str(), path.size() + 1);
    if (::bind(listen_fd, reinterpret_cast<const sockaddr*>(&addr), sizeof(addr)) != 0) {
        close(listen_fd);
        return false;
    }
    // Mode 0660, group vstat (VSTATD-IF §5.1). The group exists on CC-1; build servers may not have it.
    if (::chmod(path.c_str(), S_IRUSR | S_IWUSR | S_IRGRP | S_IWGRP) != 0) {
        close(listen_fd);
        return false;
    }
    group grp{};
    group* found = nullptr;
    std::array<char, 1024> grp_buf{};
    if (::getgrnam_r(config_.ipc_group().c_str(), &grp, grp_buf.data(), grp_buf.size(), &found) == 0 &&
        found != nullptr && ::chown(path.c_str(), static_cast<uid_t>(-1), found->gr_gid) != 0) {
        close(listen_fd);
        return false;
    }
    if (::listen(listen_fd, kBacklog) != 0 || ::fcntl(listen_fd, F_SETFL, O_NONBLOCK) != 0) {
        close(listen_fd);
        return false;
    }
    std::array<int, 2> pipe_fds{-1, -1};
    if (::pipe(pipe_fds.data()) != 0) {
        close(listen_fd);
        return false;
    }
    wake_rd_ = pipe_fds[0];
    wake_wr_ = pipe_fds[1];
    if (::fcntl(wake_rd_, F_SETFL, O_NONBLOCK) != 0 || ::fcntl(wake_wr_, F_SETFL, O_NONBLOCK) != 0) {
        close(listen_fd);
        return false;
    }
    listen_fd_ = listen_fd;
    return true;
}

bool IpcServer::start() {
    if (listen_fd_ < 0 || thread_.joinable()) {
        return false;
    }
    stopping_.store(false);
    thread_ = std::thread([this]() { run(); });
    return true;
}

void IpcServer::stop() {
    stopping_.store(true);
    wake();
    if (thread_.joinable()) {
        thread_.join();
    }
    if (listen_fd_ >= 0) {
        ::close(listen_fd_);
        listen_fd_ = -1;
        (void)::unlink(config_.ipc_socket().c_str());
    }
}

void IpcServer::publish(std::size_t index, const SignalValue& value) {
    if (index >= kSignalCount) {
        return;
    }
    {
        const std::lock_guard<std::mutex> lock(mutex_);
        Published& p = published_[index];
        if (p.value.status == value.status && std::strcmp(p.value.text.data(), value.text.data()) == 0) {
            return;
        }
        p.value = value;
        ++p.seq;
    }
    wake();
}

void IpcServer::wake() {
    if (wake_wr_ < 0) {
        return;
    }
    const char byte = 1;
    if (::write(wake_wr_, &byte, 1) < 0) {
        // A full pipe wakes the thread anyway.
        return;
    }
}

void IpcServer::drain_wake() {
    std::array<char, 64> sink{};
    while (::read(wake_rd_, sink.data(), sink.size()) > 0) {
    }
}

void IpcServer::accept_client() {
    const int client_fd = ::accept(listen_fd_, nullptr, nullptr);
    if (client_fd < 0) {
        return;
    }
    ::fcntl(client_fd, F_SETFL, O_NONBLOCK);
    const std::uint32_t id = ++next_id_;
    if (sessions_.size() >= kMaxClients) {
        const char* text = error_line(ErrorCode::kE06);
        (void)::send(client_fd, text, std::strlen(text), MSG_NOSIGNAL | MSG_DONTWAIT);
        log_.event("CLIENT_REJECTED", {Field{"client", std::to_string(id)}});
        log_.limited("REQUEST_ERROR/" + std::to_string(id), std::chrono::seconds(1), "REQUEST_ERROR",
                     {Field{"client", std::to_string(id)}, Field{"code", error_name(ErrorCode::kE06)}});
        ::close(client_fd);
        return;
    }
    sessions_.push_back(std::make_unique<ClientSession>(Peer{client_fd, id, &log_}));
    clients_.store(sessions_.size());
    log_.event("CLIENT_CONNECTED", {Field{"client", std::to_string(id)}});
}

void IpcServer::broadcast(OutLine line) {
    const std::uint64_t seq = local_[line.signal].seq;
    for (const auto& session : sessions_) {
        session->push_unavailable(line, seq);
    }
}

void IpcServer::run() {
    std::vector<pollfd> fds;
    std::vector<bool> closed;
    while (!stopping_.load()) {
        {
            const std::lock_guard<std::mutex> lock(mutex_);
            local_ = published_;
        }
        // A change to UNAVAILABLE goes to every subscriber at once (VSTATD-IF §5.3).
        for (std::size_t i = 0; i < kSignalCount; ++i) {
            if (local_[i].seq == seen_[i]) {
                continue;
            }
            seen_[i] = local_[i].seq;
            if (local_[i].value.status == Status::kUnavailable) {
                OutLine line{};
                format_val(local_[i].value, i, line);
                broadcast(line);
            }
        }
        const RequestContext due{table_, local_, SessionClock::now()};
        for (const auto& session : sessions_) {
            session->deliver(due);
        }

        fds.clear();
        fds.reserve(sessions_.size() + 2);
        pollfd p{};
        p.fd = wake_rd_;
        p.events = POLLIN;
        fds.push_back(p);
        p.fd = listen_fd_;
        fds.push_back(p);
        for (const auto& session : sessions_) {
            p.fd = session->fd();
            p.events = session->wants_write() ? static_cast<short>(POLLIN | POLLOUT) : static_cast<short>(POLLIN);
            fds.push_back(p);
        }
        if (::poll(fds.data(), fds.size(), kPollMs) < 0) {
            continue;
        }
        if (readable(fds[0])) {
            drain_wake();
        }

        const RequestContext ctx{table_, local_, SessionClock::now()};
        closed.assign(sessions_.size(), false);
        for (std::size_t i = 0; i < sessions_.size(); ++i) {
            const pollfd& ready = fds[i + 2];
            ClientSession& session = *sessions_[i];
            if (readable(ready) && !session.on_readable(ctx)) {
                closed[i] = true;
                continue;
            }
            if ((writable(ready) || session.wants_write()) && !session.flush()) {
                closed[i] = true;
            }
        }
        for (std::size_t i = sessions_.size(); i > 0; --i) {
            if (!closed[i - 1]) {
                continue;
            }
            const std::uint32_t id = sessions_[i - 1]->id();
            sessions_.erase(sessions_.begin() + static_cast<std::ptrdiff_t>(i - 1));
            log_.event("CLIENT_DISCONNECTED", {Field{"client", std::to_string(id)}});
            log_.forget("REQUEST_ERROR/" + std::to_string(id));
        }
        clients_.store(sessions_.size());
        if (readable(fds[1])) {
            accept_client();
        }
    }
    sessions_.clear();
    clients_.store(0);
}

}  // namespace vstatd
