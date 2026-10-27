// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include "service.h"

#include <algorithm>
#include <array>
#include <bitset>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <string>
#include <vector>

#include <fcntl.h>
#include <poll.h>
#include <unistd.h>

#include "frame_decoder.h"
#include "gateway_client.h"
#include "signal_defs.h"
#include "supervisor.h"

namespace vstatd {

namespace {

constexpr std::chrono::milliseconds kGatewaySilence{500};         // VSTATD-IF §4.3
constexpr std::chrono::milliseconds kMaxRetryDelay{3200};         // VSTATD-IF §4.4
constexpr std::chrono::seconds kRecordInvalidLogInterval{10};     // VSTATD-IF §2.5
constexpr std::chrono::seconds kSignalInvalidLogInterval{10};     // VSTATD-IF §3.4
constexpr int kPollMs = 5;                                        // timeouts within 10 ms (VSTATD-IF §4.1)
constexpr std::int64_t kIdleWaitMs = 100;
constexpr double kRangeEpsilon = 1e-6;

constexpr std::size_t kMaxSignalsPerMessage = 5;  // BCM_Lights
const std::array<const char*, 6> kLvStateNames = {{"UNDEFINED", "LOCK", "OFF", "ACC", "ON", "START"}};

// Start-up grace period (VSTATD-IF §4.2, rev 1.2): supervision of a message starts at its first usable frame, or
// at the end of the grace period after GATEWAY_CONNECTED, whichever is earlier.
class GracePeriod : public SupervisionHook {
public:
    explicit GracePeriod(std::chrono::milliseconds length) : length_(length) {}

    void begin(TimePoint connected) { end_ = connected + length_; }

    void attach(SupervisionEntry* entry) override { entry_ = entry; }

    void apply(TimePoint now) override {
        if (entry_ == nullptr || entry_->received) {
            return;
        }
        if (now < end_) {
            entry_->supervised = false;
            return;
        }
        if (entry_->last_rx < end_) {
            entry_->last_rx = end_;
        }
    }

private:
    std::chrono::milliseconds length_;
    TimePoint end_{};
    SupervisionEntry* entry_ = nullptr;
};

// Last decoded values used by the plausibility counters.
struct LastValues {
    double speed_kmh = 0.0;
    bool speed_known = false;
    std::uint64_t odometer_m = 0;
    bool odometer_known = false;
    double soc_percent = 0.0;
    bool soc_known = false;
    std::uint64_t range_m = 0;
    bool range_known = false;
    double temperature_c = 0.0;
    bool temperature_known = false;
    std::int32_t lv_state = 0;
};

constexpr double kSpeedJumpKmh = 20.0;
constexpr double kLowVoltage = 9.0;
constexpr double kSocJumpPercent = 5.0;
constexpr std::uint64_t kRangeJumpM = 50000;
constexpr std::uint64_t kTyreLowKpa = 150;
constexpr double kTemperatureJumpC = 10.0;
constexpr double kMovingKmh = 5.0;
constexpr double kBeltKmh = 25.0;

// What the value log knows about a signal (VSTATD-IF §7.2).
struct SignalLogState {
    std::int32_t logged_raw = 0;
    Status logged_status = Status::kUnavailable;
};

std::int64_t boot_ms(TimePoint t) {
    return std::chrono::duration_cast<std::chrono::milliseconds>(t.time_since_epoch()).count();
}

const char* reason_name(DecodeError error) { return error == DecodeError::kShortDlc ? "short_dlc" : "format"; }

}  // namespace

Service::Service(const Config& config, LogWriter& log)
    : config_(config), log_(log), table_(std::make_unique<SignalTable>()), ipc_(config, *table_, log) {
    std::array<int, 2> fds{-1, -1};
    if (::pipe(fds.data()) == 0) {
        stop_rd_ = fds[0];
        stop_wr_ = fds[1];
        if (::fcntl(stop_rd_, F_SETFL, O_NONBLOCK) != 0 || ::fcntl(stop_wr_, F_SETFL, O_NONBLOCK) != 0) {
            stop_.store(true);
        }
    }
}

Service::~Service() {
    shutdown();
    if (stop_rd_ >= 0) {
        ::close(stop_rd_);
    }
    if (stop_wr_ >= 0) {
        ::close(stop_wr_);
    }
}

bool Service::start_ipc() { return ipc_.open_listener() && ipc_.start(); }

void Service::stop() {
    stop_.store(true);
    if (stop_wr_ >= 0) {
        const char byte = 1;
        if (::write(stop_wr_, &byte, 1) < 0) {
            // A full pipe still wakes run().
            return;
        }
    }
}

void Service::shutdown() { ipc_.stop(); }

ServiceStats Service::stats() const {
    const std::lock_guard<std::mutex> lock(stats_mutex_);
    return stats_;
}

void Service::wait_for_stop(int timeout_ms) const {
    pollfd p{};
    p.fd = stop_rd_;
    p.events = POLLIN;
    (void)::poll(&p, 1, timeout_ms);
}

int Service::run() {
    // ------------------------------------------------------------------------------------------------------------
    // State of the gateway side. Everything below runs on this thread; the IPC thread only sees the signal table
    // and what is published to it.
    // ------------------------------------------------------------------------------------------------------------
    int status = 0;
    GatewayClient gateway(config_.gateway_socket());
    FrameDecoder decoder;
    Supervisor supervisor(config_.grace(), kGatewaySilence);
    GracePeriod grace(supervisor.grace());
    supervisor.set_hook(&grace);
    std::array<SignalLogState, kSignalCount> logged{};
    std::vector<std::string> lines;
    lines.reserve(64);
    ServiceStats counters{};
    bool connected = false;
    bool retry_logged = false;
    TimePoint next_attempt = Clock::now();
    // Bench diagnostics: reception gaps per message, heartbeat gaps and the gateway's own clock.
    std::array<TimePoint, kMessageCount> last_frame{};
    std::array<bool, kMessageCount> seen_frame{};
    TimePoint last_heartbeat{};
    bool seen_heartbeat = false;
    std::uint64_t last_gateway_us = 0;
    std::bitset<0x800> unknown_ids;
    LastValues last;
    std::array<std::uint32_t, kMessageCount> frames_this_second{};
    TimePoint second_start = Clock::now();
    std::uint64_t loops = 0;

    for (;;) {
        loops = loops + 1;
        if (stop_requested()) {
            supervisor.set_hook(nullptr);
            gateway.close();
            return status;
        }

        // --------------------------------------------------------------------------------------------------------
        // Connection to the gateway (VSTATD-IF §4.4). The first attempt is made at once; after a failure or a
        // loss the delay starts at 100 ms and doubles up to 3200 ms. Failed attempts are not logged one by one.
        // --------------------------------------------------------------------------------------------------------
        if (!connected) {
            const TimePoint before = Clock::now();
            if (before < next_attempt) {
                const auto wait = std::chrono::duration_cast<std::chrono::milliseconds>(next_attempt - before);
                wait_for_stop(static_cast<int>(std::min<std::int64_t>(wait.count() + 1, kIdleWaitMs)));
                continue;
            }
            if (!gateway.connect()) {
                ++counters.failed_connects;
                const std::chrono::milliseconds delay = gateway.next_delay();
                if (delay >= kMaxRetryDelay && !retry_logged) {
                    log_.event("GATEWAY_RETRY", {Field{"delay_ms", to_field(delay.count())}});
                    retry_logged = true;
                }
                next_attempt = before + delay;
                continue;
            }
            connected = true;
            retry_logged = false;
            gateway.reset_delay();
            ++counters.connects;
            log_.event("GATEWAY_CONNECTED", {});
            const TimePoint at = Clock::now();
            supervisor.reset(at);
            grace.begin(at);
            // A new connection starts the diagnostics of the gateway's timing again.
            seen_frame.fill(false);
            seen_heartbeat = false;
            last_gateway_us = 0;
            last = LastValues{};
        }

        // --------------------------------------------------------------------------------------------------------
        // Wait for gateway records, a stop request or the next supervision tick.
        // --------------------------------------------------------------------------------------------------------
        std::array<pollfd, 2> fds{};
        fds[0].fd = gateway.socket_fd();
        fds[0].events = POLLIN;
        fds[1].fd = stop_rd_;
        fds[1].events = POLLIN;
        const int ready = ::poll(fds.data(), fds.size(), kPollMs);
        if (ready < 0 && errno != EINTR) {
            wait_for_stop(kPollMs);
        }
        if (stop_requested()) {
            continue;
        }

        // --------------------------------------------------------------------------------------------------------
        // Read what the gateway sent. A closed socket or a read error is a gateway loss (VSTATD-IF §4.3).
        // --------------------------------------------------------------------------------------------------------
        const char* lost_reason = nullptr;
        lines.clear();
        if (ready > 0 && (fds[0].revents & (POLLIN | POLLHUP | POLLERR)) != 0) {
            const ReadStatus read = gateway.read_records(lines);
            if (read == ReadStatus::kClosed) {
                lost_reason = "closed";
            } else if (read == ReadStatus::kError) {
                lost_reason = "error";
            }
        }

        // --------------------------------------------------------------------------------------------------------
        // One decoding step per usable frame (VSTATD-IF §2.5, §3, §7.3).
        // --------------------------------------------------------------------------------------------------------
        for (std::size_t li = 0; li < lines.size(); ++li) {
            const std::string& text = lines[li];
            const TimePoint rx = Clock::now();
            supervisor.on_line(rx);
            ++counters.lines;
            counters.bytes += text.size() + 1U;
            counters.longest_line = std::max(counters.longest_line, text.size());
            {
                // Flight recorder: the line, cut to 63 characters.
                std::array<char, 64>& slot = counters.recorder[counters.recorder_next];
                const std::size_t n = std::min(text.size(), slot.size() - 1U);
                for (std::size_t c = 0; c < n; ++c) {
                    slot[c] = text[c];
                }
                slot[n] = '\0';
                counters.recorder_next = (counters.recorder_next + 1U) % counters.recorder.size();
            }
            try {
                Record record;
                if (!decoder.accept(text.data(), text.size(), record)) {
                    // Discarded; logged at most once per 10 s for each reason (VSTATD-IF §2.5, §6.5).
                    ++counters.invalid;
                    const char* reason = reason_name(decoder.last_error());
                    log_.limited(std::string("GATEWAY_RECORD_INVALID/") + reason, kRecordInvalidLogInterval,
                                 "GATEWAY_RECORD_INVALID", {Field{"reason", reason}});
                    continue;
                }
                // The gateway's clock (t_us) only tells whether the gateway restarted without closing the socket;
                // supervision runs on the CC-1 monotonic clock (VSTATD-IF §4.5).
                if (record.t_us < last_gateway_us) {
                    ++counters.gateway_restarts;
                }
                last_gateway_us = record.t_us;
                const bool heartbeat = record.kind == RecordKind::kHeartbeat;
                if (heartbeat) {
                    ++counters.heartbeats;
                    if (seen_heartbeat) {
                        const auto gap = std::chrono::duration_cast<std::chrono::milliseconds>(rx - last_heartbeat);
                        counters.max_heartbeat_gap_ms = std::max<std::int64_t>(counters.max_heartbeat_gap_ms, gap.count());
                    }
                    last_heartbeat = rx;
                    seen_heartbeat = true;
                }
                if (heartbeat) {
                    continue;
                }
                const std::size_t m = message_index(record.can_id);
                if (m == kNoMessage) {
                    // Not one of ours: ignored without a log entry (VSTATD-IF §2.5). Distinct IDs are counted for
                    // the bench, to spot a gateway filter that lets too much through.
                    ++counters.ignored;
                    if (record.can_id < unknown_ids.size() && !unknown_ids.test(record.can_id)) {
                        unknown_ids.set(record.can_id);
                        counters.unknown_ids = unknown_ids.count();
                    }
                    continue;
                }
                ++counters.frames;
                const MessageDef& msg = kMessages[m];
                const std::int64_t step_ms = boot_ms(rx);
                ++counters.message_frames[m];
                if (seen_frame[m]) {
                    const auto gap = std::chrono::duration_cast<std::chrono::milliseconds>(rx - last_frame[m]);
                    counters.max_frame_gap_ms[m] = std::max<std::int64_t>(counters.max_frame_gap_ms[m], gap.count());
                }
                last_frame[m] = rx;
                seen_frame[m] = true;
                ++frames_this_second[m];

                // Bits outside the message's signals should be zero; senders that set them are counted.
                std::uint64_t payload = 0;
                for (std::size_t b = record.data.size(); b > 0; --b) {
                    payload = (payload << 8U) | record.data[b - 1];
                }
                std::uint64_t used_bits = 0;
                for (std::size_t s = msg.first_signal; s < static_cast<std::size_t>(msg.first_signal) + msg.signal_count;
                     ++s) {
                    const std::uint64_t width = (std::uint64_t{1} << kSignals[s].length) - 1U;
                    used_bits |= width << kSignals[s].start_bit;
                }
                if ((payload & ~used_bits) != 0U) {
                    ++counters.unused_bits[m];
                }

                // A usable frame ends a timeout of its message: SIGNAL_RECOVERED comes first (VSTATD-IF §7.3).
                if (supervisor.on_frame(m, rx)) {
                    log_.event("SIGNAL_RECOVERED", {Field{"message", msg.name}});
                }

                // ---- Decoding of the message's signals, as written from cc1-gateway.dbc ---------------------
                // Each slot is one signal of the message, in the order of the signal table (VSTATD-IF §3.1).
                std::array<std::int32_t, kMaxSignalsPerMessage> raws{};
                std::array<Verdict, kMaxSignalsPerMessage> verdicts{};
                std::array<std::array<char, 16>, kMaxSignalsPerMessage> texts{};
                std::array<int, kMaxSignalsPerMessage> written{};
                verdicts.fill(Verdict::kValue);
                switch (m) {
                    case 0: {
                        // VCU_PowerState (0x100), 100 ms.
                        // Vehicle.LowVoltageSystemState: bits 0-2, enumeration of VSTATD-IF §3.5, SNA 7.
                        const SignalDef& state = kSignals[0];
                        const std::int32_t lv = decoder.raw_value(record, state);
                        raws[0] = lv;
                        if (lv == state.sna_raw) {
                            verdicts[0] = Verdict::kNotAvailable;
                        } else if (lv == 6) {
                            verdicts[0] = Verdict::kFlagError;
                        } else if (lv > 5) {
                            verdicts[0] = Verdict::kFlagError;
                        } else {
                            written[0] = std::snprintf(texts[0].data(), texts[0].size(), "%s",
                                                       kLvStateNames[static_cast<std::size_t>(lv)]);
                            last.lv_state = lv;
                        }
                        // Vehicle.LowVoltageBattery.CurrentVoltage: bits 8-17, 0.02 V, 6 to 18 V, SNA 1023.
                        const SignalDef& voltage = kSignals[1];
                        const std::int32_t mv = decoder.raw_value(record, voltage);
                        raws[1] = mv;
                        if (mv == voltage.sna_raw) {
                            verdicts[1] = Verdict::kNotAvailable;
                        } else {
                            const double volts = static_cast<double>(mv) * voltage.factor;
                            if (volts < voltage.min - kRangeEpsilon || volts > voltage.max + kRangeEpsilon) {
                                verdicts[1] = Verdict::kOutOfRange;
                            } else {
                                written[1] = std::snprintf(texts[1].data(), texts[1].size(), "%.2f", volts);
                                // ON (4) or START (5) with a weak battery.
                                if (volts < kLowVoltage && (last.lv_state == 4 || last.lv_state == 5)) {
                                    ++counters.plausibility.low_voltage_on;
                                }
                            }
                        }
                        break;
                    }
                    case 1: {
                        // VCU_Speed (0x101), 20 ms.
                        // Vehicle.Speed: bits 0-15, 0.01 km/h, 0 to 300 km/h, SNA 65535.
                        const SignalDef& speed = kSignals[2];
                        const std::int32_t v = decoder.raw_value(record, speed);
                        raws[0] = v;
                        if (v == speed.sna_raw) {
                            verdicts[0] = Verdict::kNotAvailable;
                        } else {
                            const double kmh = static_cast<double>(v) * speed.factor;
                            if (kmh > speed.max + kRangeEpsilon) {
                                verdicts[0] = Verdict::kOutOfRange;
                            } else {
                                written[0] = std::snprintf(texts[0].data(), texts[0].size(), "%.2f", kmh);
                                if (last.speed_known && std::fabs(kmh - last.speed_kmh) > kSpeedJumpKmh) {
                                    ++counters.plausibility.speed_jumps;
                                }
                                last.speed_kmh = kmh;
                                last.speed_known = true;
                            }
                        }
                        break;
                    }
                    case 2: {
                        // VCU_Gear (0x102), 50 ms.
                        // Vehicle.Powertrain.Transmission.CurrentGear: bits 0-7 signed, -1 to 8, SNA -128.
                        const SignalDef& current = kSignals[3];
                        const std::int32_t gear = decoder.raw_value(record, current);
                        raws[0] = gear;
                        if (gear == current.sna_raw) {
                            verdicts[0] = Verdict::kNotAvailable;
                        } else if (gear < static_cast<std::int32_t>(current.min) ||
                                   gear > static_cast<std::int32_t>(current.max)) {
                            verdicts[0] = Verdict::kOutOfRange;
                        } else {
                            written[0] = std::snprintf(texts[0].data(), texts[0].size(), "%d", gear);
                        }
                        // Vehicle.Powertrain.Transmission.SelectedGear: bits 8-15 signed, VSS codes -1 reverse,
                        // 0 neutral, 126 park, 127 drive; SNA -128. Codes for single forward gears are not sent.
                        const SignalDef& selected = kSignals[4];
                        const std::int32_t code = decoder.raw_value(record, selected);
                        raws[1] = code;
                        if (code == selected.sna_raw) {
                            verdicts[1] = Verdict::kNotAvailable;
                        } else if (code != -1 && code != 0 && code != 126 && code != 127) {
                            verdicts[1] = Verdict::kOutOfRange;
                        } else {
                            written[1] = std::snprintf(texts[1].data(), texts[1].size(), "%d", code);
                            if (code == 126 && last.speed_known && last.speed_kmh > kMovingKmh) {
                                ++counters.plausibility.park_while_moving;
                            }
                        }
                        // Vehicle.Chassis.ParkingBrake.IsEngaged: bits 16-17, flag.
                        const std::int32_t brake = decoder.raw_value(record, kSignals[5]);
                        raws[2] = brake;
                        if (brake == 3) {
                            verdicts[2] = Verdict::kNotAvailable;
                        } else if (brake == 2) {
                            verdicts[2] = Verdict::kFlagError;
                        } else {
                            written[2] = std::snprintf(texts[2].data(), texts[2].size(), "%s", brake == 1 ? "true" : "false");
                        }
                        break;
                    }
                    case 3: {
                        // VCU_Odometer (0x103), 1000 ms.
                        // Vehicle.TraveledDistance: bits 0-23, 100 m, SNA 16777215. Every other value is in range.
                        const SignalDef& odo = kSignals[6];
                        const std::int32_t hm = decoder.raw_value(record, odo);
                        raws[0] = hm;
                        if (hm == odo.sna_raw) {
                            verdicts[0] = Verdict::kNotAvailable;
                        } else {
                            const std::uint64_t meters = scale_unsigned(static_cast<std::uint32_t>(hm), odo);
                            written[0] = std::snprintf(texts[0].data(), texts[0].size(), "%llu",
                                                       static_cast<unsigned long long>(meters));
                            if (last.odometer_known && meters < last.odometer_m) {
                                ++counters.plausibility.odometer_backwards;
                            }
                            last.odometer_m = meters;
                            last.odometer_known = true;
                        }
                        break;
                    }
                    case 4: {
                        // BMS_Status (0x200), 100 ms.
                        // Vehicle.Powertrain.TractionBattery.StateOfCharge.Displayed: bits 0-7, 0.5 percent, 0 to
                        // 100 percent, SNA 255.
                        const SignalDef& soc = kSignals[7];
                        const std::int32_t half_pct = decoder.raw_value(record, soc);
                        raws[0] = half_pct;
                        if (half_pct == soc.sna_raw) {
                            verdicts[0] = Verdict::kNotAvailable;
                        } else {
                            const double percent = static_cast<double>(half_pct) * soc.factor;
                            if (percent > soc.max + kRangeEpsilon) {
                                verdicts[0] = Verdict::kOutOfRange;
                            } else {
                                written[0] = std::snprintf(texts[0].data(), texts[0].size(), "%.1f", percent);
                                if (last.soc_known && std::fabs(percent - last.soc_percent) > kSocJumpPercent) {
                                    ++counters.plausibility.soc_jumps;
                                }
                                last.soc_percent = percent;
                                last.soc_known = true;
                            }
                        }
                        // Vehicle.Powertrain.Range: bits 8-23, 10 m, 0 to 655340 m, SNA 65535.
                        const SignalDef& range = kSignals[8];
                        const std::int32_t dam = decoder.raw_value(record, range);
                        raws[1] = dam;
                        if (dam == range.sna_raw) {
                            verdicts[1] = Verdict::kNotAvailable;
                        } else {
                            const std::uint64_t meters = scale_unsigned(static_cast<std::uint32_t>(dam), range);
                            written[1] = std::snprintf(texts[1].data(), texts[1].size(), "%llu",
                                                       static_cast<unsigned long long>(meters));
                            const std::uint64_t change =
                                meters > last.range_m ? meters - last.range_m : last.range_m - meters;
                            if (last.range_known && change > kRangeJumpM) {
                                ++counters.plausibility.range_jumps;
                            }
                            last.range_m = meters;
                            last.range_known = true;
                        }
                        // Vehicle.Powertrain.TractionBattery.Charging.IsCharging: bits 24-25, flag.
                        const std::int32_t charging = decoder.raw_value(record, kSignals[9]);
                        raws[2] = charging;
                        if (charging == 3) {
                            verdicts[2] = Verdict::kNotAvailable;
                        } else if (charging == 2) {
                            verdicts[2] = Verdict::kFlagError;
                        } else {
                            written[2] = std::snprintf(texts[2].data(), texts[2].size(), "%s",
                                                       charging == 1 ? "true" : "false");
                        }
                        break;
                    }
                    case 5: {
                        // BCM_Lights (0x300), 100 ms. Five two-bit flags: low beam, high beam, left and right
                        // indicator, hazard (bits 0-1, 2-3, 4-5, 6-7, 8-9).
                        const std::int32_t low = decoder.raw_value(record, kSignals[10]);
                        raws[0] = low;
                        if (low == 3) {
                            verdicts[0] = Verdict::kNotAvailable;
                        } else if (low == 2) {
                            verdicts[0] = Verdict::kFlagError;
                        } else {
                            written[0] = std::snprintf(texts[0].data(), texts[0].size(), "%s", low == 1 ? "true" : "false");
                        }
                        const std::int32_t high = decoder.raw_value(record, kSignals[11]);
                        raws[1] = high;
                        if (high == 3) {
                            verdicts[1] = Verdict::kNotAvailable;
                        } else if (high == 2) {
                            verdicts[1] = Verdict::kFlagError;
                        } else {
                            written[1] = std::snprintf(texts[1].data(), texts[1].size(), "%s", high == 1 ? "true" : "false");
                        }
                        const std::int32_t left = decoder.raw_value(record, kSignals[12]);
                        raws[2] = left;
                        if (left == 3) {
                            verdicts[2] = Verdict::kNotAvailable;
                        } else if (left == 2) {
                            verdicts[2] = Verdict::kFlagError;
                        } else {
                            written[2] = std::snprintf(texts[2].data(), texts[2].size(), "%s", left == 1 ? "true" : "false");
                        }
                        const std::int32_t right = decoder.raw_value(record, kSignals[13]);
                        raws[3] = right;
                        if (right == 3) {
                            verdicts[3] = Verdict::kNotAvailable;
                        } else if (right == 2) {
                            verdicts[3] = Verdict::kFlagError;
                        } else {
                            written[3] = std::snprintf(texts[3].data(), texts[3].size(), "%s", right == 1 ? "true" : "false");
                        }
                        const std::int32_t hazard = decoder.raw_value(record, kSignals[14]);
                        raws[4] = hazard;
                        if (hazard == 3) {
                            verdicts[4] = Verdict::kNotAvailable;
                        } else if (hazard == 2) {
                            verdicts[4] = Verdict::kFlagError;
                        } else {
                            written[4] = std::snprintf(texts[4].data(), texts[4].size(), "%s",
                                                       hazard == 1 ? "true" : "false");
                        }
                        break;
                    }
                    case 6: {
                        // BCM_Closures (0x301), 100 ms. Four two-bit flags: driver door, passenger door, trunk,
                        // driver seat belt (bits 0-1, 2-3, 4-5, 6-7).
                        const std::int32_t driver = decoder.raw_value(record, kSignals[15]);
                        raws[0] = driver;
                        if (driver == 3) {
                            verdicts[0] = Verdict::kNotAvailable;
                        } else if (driver == 2) {
                            verdicts[0] = Verdict::kFlagError;
                        } else {
                            written[0] = std::snprintf(texts[0].data(), texts[0].size(), "%s",
                                                       driver == 1 ? "true" : "false");
                            if (driver == 1 && last.speed_known && last.speed_kmh > kMovingKmh) {
                                ++counters.plausibility.door_open_moving;
                            }
                        }
                        const std::int32_t passenger = decoder.raw_value(record, kSignals[16]);
                        raws[1] = passenger;
                        if (passenger == 3) {
                            verdicts[1] = Verdict::kNotAvailable;
                        } else if (passenger == 2) {
                            verdicts[1] = Verdict::kFlagError;
                        } else {
                            written[1] = std::snprintf(texts[1].data(), texts[1].size(), "%s",
                                                       passenger == 1 ? "true" : "false");
                            if (passenger == 1 && last.speed_known && last.speed_kmh > kMovingKmh) {
                                ++counters.plausibility.door_open_moving;
                            }
                        }
                        const std::int32_t trunk = decoder.raw_value(record, kSignals[17]);
                        raws[2] = trunk;
                        if (trunk == 3) {
                            verdicts[2] = Verdict::kNotAvailable;
                        } else if (trunk == 2) {
                            verdicts[2] = Verdict::kFlagError;
                        } else {
                            written[2] = std::snprintf(texts[2].data(), texts[2].size(), "%s",
                                                       trunk == 1 ? "true" : "false");
                        }
                        const std::int32_t belt = decoder.raw_value(record, kSignals[18]);
                        raws[3] = belt;
                        if (belt == 3) {
                            verdicts[3] = Verdict::kNotAvailable;
                        } else if (belt == 2) {
                            verdicts[3] = Verdict::kFlagError;
                        } else {
                            written[3] = std::snprintf(texts[3].data(), texts[3].size(), "%s", belt == 1 ? "true" : "false");
                            if (belt == 0 && last.speed_known && last.speed_kmh > kBeltKmh) {
                                ++counters.plausibility.unbelted_moving;
                            }
                        }
                        break;
                    }
                    case 7: {
                        // TPMS_Pressures (0x400), 1000 ms. One byte per tyre, 2 kPa, 0 to 500 kPa, SNA 255.
                        // Front left tyre (FL): bits 0-7.
                        const SignalDef& tyre_fl = kSignals[19];
                        const std::int32_t fl = decoder.raw_value(record, tyre_fl);
                        raws[0] = fl;
                        if (fl == tyre_fl.sna_raw) {
                            verdicts[0] = Verdict::kNotAvailable;
                        } else {
                            const std::uint64_t kpa = scale_unsigned(static_cast<std::uint32_t>(fl), tyre_fl);
                            if (static_cast<double>(kpa) > tyre_fl.max + kRangeEpsilon) {
                                verdicts[0] = Verdict::kOutOfRange;
                            } else {
                                written[0] = std::snprintf(texts[0].data(), texts[0].size(), "%llu",
                                                           static_cast<unsigned long long>(kpa));
                                if (kpa < kTyreLowKpa) {
                                    ++counters.plausibility.tyre_low;
                                }
                            }
                        }
                        // Front right tyre (FR): bits 8-15.
                        const SignalDef& tyre_fr = kSignals[20];
                        const std::int32_t fr = decoder.raw_value(record, tyre_fr);
                        raws[1] = fr;
                        if (fr == tyre_fr.sna_raw) {
                            verdicts[1] = Verdict::kNotAvailable;
                        } else {
                            const std::uint64_t kpa = scale_unsigned(static_cast<std::uint32_t>(fr), tyre_fr);
                            if (static_cast<double>(kpa) > tyre_fr.max + kRangeEpsilon) {
                                verdicts[1] = Verdict::kOutOfRange;
                            } else {
                                written[1] = std::snprintf(texts[1].data(), texts[1].size(), "%llu",
                                                           static_cast<unsigned long long>(kpa));
                                if (kpa < kTyreLowKpa) {
                                    ++counters.plausibility.tyre_low;
                                }
                            }
                        }
                        // Rear left tyre (RL): bits 16-23.
                        const SignalDef& tyre_rl = kSignals[21];
                        const std::int32_t rl = decoder.raw_value(record, tyre_rl);
                        raws[2] = rl;
                        if (rl == tyre_rl.sna_raw) {
                            verdicts[2] = Verdict::kNotAvailable;
                        } else {
                            const std::uint64_t kpa = scale_unsigned(static_cast<std::uint32_t>(rl), tyre_rl);
                            if (static_cast<double>(kpa) > tyre_rl.max + kRangeEpsilon) {
                                verdicts[2] = Verdict::kOutOfRange;
                            } else {
                                written[2] = std::snprintf(texts[2].data(), texts[2].size(), "%llu",
                                                           static_cast<unsigned long long>(kpa));
                                if (kpa < kTyreLowKpa) {
                                    ++counters.plausibility.tyre_low;
                                }
                            }
                        }
                        // Rear right tyre (RR): bits 24-31.
                        const SignalDef& tyre_rr = kSignals[22];
                        const std::int32_t rr = decoder.raw_value(record, tyre_rr);
                        raws[3] = rr;
                        if (rr == tyre_rr.sna_raw) {
                            verdicts[3] = Verdict::kNotAvailable;
                        } else {
                            const std::uint64_t kpa = scale_unsigned(static_cast<std::uint32_t>(rr), tyre_rr);
                            if (static_cast<double>(kpa) > tyre_rr.max + kRangeEpsilon) {
                                verdicts[3] = Verdict::kOutOfRange;
                            } else {
                                written[3] = std::snprintf(texts[3].data(), texts[3].size(), "%llu",
                                                           static_cast<unsigned long long>(kpa));
                                if (kpa < kTyreLowKpa) {
                                    ++counters.plausibility.tyre_low;
                                }
                            }
                        }
                        break;
                    }
                    case 8: {
                        // BCM_Exterior (0x401), 1000 ms.
                        // Vehicle.Exterior.AirTemperature: bits 0-7, 0.5 Celsius, offset -40, -40 to 85 Celsius,
                        // SNA 255.
                        const SignalDef& air = kSignals[23];
                        const std::int32_t t = decoder.raw_value(record, air);
                        raws[0] = t;
                        if (t == air.sna_raw) {
                            verdicts[0] = Verdict::kNotAvailable;
                        } else {
                            const double celsius = static_cast<double>(t) * air.factor + air.offset;
                            if (celsius > air.max + kRangeEpsilon) {
                                verdicts[0] = Verdict::kOutOfRange;
                            } else {
                                // -0.0 is written as 0.0.
                                const double shown = (celsius > -0.05 && celsius < 0.0) ? 0.0 : celsius;
                                written[0] = std::snprintf(texts[0].data(), texts[0].size(), "%.*f",
                                                           static_cast<int>(air.decimals), shown);
                                if (last.temperature_known &&
                                    std::fabs(celsius - last.temperature_c) > kTemperatureJumpC) {
                                    ++counters.plausibility.temperature_jumps;
                                }
                                last.temperature_c = celsius;
                                last.temperature_known = true;
                            }
                        }
                        break;
                    }
                    default:
                        break;
                }

                // ---- Signal table, IPC and value log (VSTATD-IF §3.4, §5.3, §7.2) -------------------------
                std::array<bool, kMaxSignalsPerMessage> invalid{};
                for (std::size_t k = 0; k < msg.signal_count; ++k) {
                    const std::size_t s = msg.first_signal + k;
                    const SignalDef& def = kSignals[s];
                    if (verdicts[k] == Verdict::kValue &&
                        (written[k] <= 0 || static_cast<std::size_t>(written[k]) >= texts[k].size())) {
                        // Cannot happen with the ranges of VSTATD-IF §3.1; publish nothing rather than a cut value.
                        verdicts[k] = Verdict::kOutOfRange;
                    }
                    Reading reading;
                    reading.t_ms = step_ms;
                    reading.raw = raws[k];
                    reading.verdict = verdicts[k];
                    reading.text = verdicts[k] == Verdict::kValue ? texts[k].data() : "-";
                    table_->update(def.path, reading);
                    const SignalValue current = table_->get(s);
                    ipc_.publish(s, current);

                    const Status status = current.status;
                    SignalLogState& state = logged[s];
                    bool log_value = false;
                    if (status != state.logged_status) {
                        log_value = true;
                    } else if (status == Status::kAvailable) {
                        const std::int64_t delta = static_cast<std::int64_t>(raws[k]) - state.logged_raw;
                        log_value = std::llabs(delta) >= static_cast<std::int64_t>(def.deadband_raw);
                    }
                    if (log_value) {
                        log_.event("SIGNAL_VALUE", {Field{"path", def.path},
                                                    Field{"value", status == Status::kAvailable ? texts[k].data() : "-"},
                                                    Field{"status", status_name(status)}});
                        state.logged_raw = raws[k];
                        state.logged_status = status;
                    }
                    invalid[k] = status == Status::kInvalid;
                    if (verdicts[k] == Verdict::kNotAvailable) {
                        ++counters.sna[s];
                    }
                    if (invalid[k]) {
                        ++counters.invalid_values[s];
                    }
                }

                // SIGNAL_INVALID after the values of the step, at most once per 10 s per signal (VSTATD-IF §3.4).
                for (std::size_t k = 0; k < msg.signal_count; ++k) {
                    if (!invalid[k]) {
                        continue;
                    }
                    const char* path = kSignals[msg.first_signal + k].path;
                    log_.limited(std::string("SIGNAL_INVALID/") + path, kSignalInvalidLogInterval, "SIGNAL_INVALID",
                                 {Field{"path", path}, Field{"raw", std::to_string(raws[k])}});
                }

                // Time spent in the decoding step, for CPU comparisons on the same bench.
                const auto spent = std::chrono::duration_cast<std::chrono::microseconds>(Clock::now() - rx).count();
                counters.total_step_us += spent;
                counters.max_step_us = std::max<std::int64_t>(counters.max_step_us, spent);
            } catch (const std::exception&) {
            }
        }

        // --------------------------------------------------------------------------------------------------------
        // Gateway loss (VSTATD-IF §4.3): silence for 500 ms, or the socket closed or failed. Every signal becomes
        // UNAVAILABLE; GATEWAY_LOST comes before the SIGNAL_VALUE entries it causes (§7.3).
        // --------------------------------------------------------------------------------------------------------
        const TimePoint now = Clock::now();
        if (lost_reason == nullptr && supervisor.gateway_silent(now)) {
            lost_reason = "silence";
        }
        if (lost_reason != nullptr) {
            ++counters.losses;
            if (std::strcmp(lost_reason, "silence") == 0) {
                ++counters.losses_silence;
            } else if (std::strcmp(lost_reason, "closed") == 0) {
                ++counters.losses_closed;
            } else {
                ++counters.losses_error;
            }
            log_.event("GATEWAY_LOST", {Field{"reason", lost_reason}});
            const std::int64_t lost_ms = boot_ms(now);
            for (std::size_t s = 0; s < kSignalCount; ++s) {
                Reading reading;
                reading.t_ms = lost_ms;
                reading.verdict = Verdict::kLost;
                const SignalValue before = table_->get(s);
                reading.raw = before.raw;
                table_->update(kSignals[s].path, reading);
                ipc_.publish(s, table_->get(s));
                if (logged[s].logged_status != Status::kUnavailable) {
                    log_.event("SIGNAL_VALUE", {Field{"path", kSignals[s].path}, Field{"value", "-"},
                                                Field{"status", status_name(Status::kUnavailable)}});
                    logged[s].logged_status = Status::kUnavailable;
                }
            }
            gateway.close();
            connected = false;
            retry_logged = false;
            gateway.reset_delay();
            next_attempt = now + gateway.next_delay();
            {
                const std::lock_guard<std::mutex> lock(stats_mutex_);
                stats_ = counters;
            }
            continue;
        }

        // --------------------------------------------------------------------------------------------------------
        // Message timeouts (VSTATD-IF §4.1): SIGNAL_TIMEOUT once per message, then the SIGNAL_VALUE entries of its
        // signals; messages that time out together follow the order of §3.2.
        // --------------------------------------------------------------------------------------------------------
        CheckResult result;
        supervisor.check(now, boot_ms(now), result);
        if (result.count > 0) {
            for (std::size_t m = 0; m < kMessageCount; ++m) {
                if (!result.timed_out[m]) {
                    continue;
                }
                ++counters.timeouts;
                ++counters.message_timeouts[m];
                const MessageDef& msg = kMessages[m];
                log_.event("SIGNAL_TIMEOUT", {Field{"message", msg.name}});
                for (std::size_t s = msg.first_signal; s < static_cast<std::size_t>(msg.first_signal) + msg.signal_count;
                     ++s) {
                    Reading reading;
                    reading.t_ms = result.t_ms;
                    reading.verdict = Verdict::kNotAvailable;
                    reading.raw = table_->get(s).raw;
                    table_->update(kSignals[s].path, reading);
                    ipc_.publish(s, table_->get(s));
                    if (logged[s].logged_status != Status::kUnavailable) {
                        log_.event("SIGNAL_VALUE", {Field{"path", kSignals[s].path}, Field{"value", "-"},
                                                    Field{"status", status_name(Status::kUnavailable)}});
                        logged[s].logged_status = Status::kUnavailable;
                    }
                }
            }
        }

        // Frame rates per message over whole seconds.
        if (now - second_start >= std::chrono::seconds(1)) {
            counters.frames_last_second = frames_this_second;
            frames_this_second.fill(0U);
            second_start = now;
        }

        {
            const std::lock_guard<std::mutex> lock(stats_mutex_);
            stats_ = counters;
        }
    }

    loops = 0;
    return status;
}

}  // namespace vstatd
