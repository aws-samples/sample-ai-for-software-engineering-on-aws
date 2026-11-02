// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Message timeouts and gateway silence (VSTATD-IF §4.1, §4.3), on the monotonic clock (§4.5).
#pragma once

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>

#include "signal_defs.h"

namespace vstatd {

using Clock = std::chrono::steady_clock;
using TimePoint = Clock::time_point;

struct SupervisionEntry {
    TimePoint last_rx{};                      // last usable frame, or the start of supervision
    std::chrono::milliseconds timeout{0};
    std::uint8_t message = 0;
    bool supervised = true;
    bool received = false;                    // a usable frame arrived since GATEWAY_CONNECTED
    bool timed_out = false;
};

// Lets other parts of the service take part in supervision. The hook sees each entry while it is checked.
class SupervisionHook {
public:
    virtual ~SupervisionHook() = default;
    virtual void attach(SupervisionEntry* entry) = 0;
    virtual void apply(TimePoint now) = 0;
};

struct CheckResult {
    std::array<bool, kMessageCount> timed_out{};  // messages whose timeout started in this check
    std::size_t count = 0;
    std::int64_t t_ms = 0;                        // time of the first timeout, CC-1 clock since boot
};

class Supervisor {
public:
    Supervisor(std::chrono::milliseconds grace, std::chrono::milliseconds silence);

    void set_hook(SupervisionHook* hook) { hook_ = hook; }

    // GATEWAY_CONNECTED: every message is counted from now.
    void reset(TimePoint now);

    // A usable frame of a message (VSTATD-IF §2.5). Returns true when it ends a timeout.
    bool on_frame(std::size_t message, TimePoint now);

    // Any line from the gateway, usable or not (VSTATD-IF §4.3).
    void on_line(TimePoint now) { last_line_ = now; }

    // Detects message timeouts.
    void check(TimePoint at, std::int64_t at_ms, CheckResult& result);

    bool gateway_silent(TimePoint now) const { return now - last_line_ > silence_; }
    bool timed_out(std::size_t message) const { return entries_[message].timed_out; }
    std::chrono::milliseconds grace() const { return grace_; }

private:
    std::chrono::milliseconds grace_;
    std::chrono::milliseconds silence_;
    SupervisionHook* hook_ = nullptr;
    TimePoint last_line_{};
    std::array<SupervisionEntry, kMessageCount> entries_{};
};

}  // namespace vstatd
