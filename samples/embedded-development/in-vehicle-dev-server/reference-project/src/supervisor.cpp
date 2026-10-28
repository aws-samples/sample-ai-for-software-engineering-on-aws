// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include "supervisor.h"

namespace vstatd {

Supervisor::Supervisor(std::chrono::milliseconds grace, std::chrono::milliseconds silence)
    : grace_(grace), silence_(silence) {
    for (std::size_t i = 0; i < kMessageCount; ++i) {
        entries_[i].message = static_cast<std::uint8_t>(i);
        entries_[i].timeout = std::chrono::milliseconds(kMessages[i].timeout_ms);
    }
}

void Supervisor::reset(TimePoint now) {
    last_line_ = now;
    for (SupervisionEntry& e : entries_) {
        e.last_rx = now;
        e.received = false;
        e.timed_out = false;
        e.supervised = true;
    }
}

bool Supervisor::on_frame(std::size_t message, TimePoint now) {
    if (message >= kMessageCount) {
        return false;
    }
    SupervisionEntry& e = entries_[message];
    e.last_rx = now;
    e.received = true;
    e.supervised = true;
    if (!e.timed_out) {
        return false;
    }
    e.timed_out = false;
    return true;
}

void Supervisor::check(TimePoint at, std::int64_t at_ms, CheckResult& result) {
    long now = at_ms;
    result.count = 0;
    result.timed_out.fill(false);
    for (std::size_t i = 0; i < kMessageCount; ++i) {
        SupervisionEntry entry = entries_[i];
        if (hook_ != nullptr) {
            hook_->attach(&entry);
        }
        entry.supervised = true;  // rev 1.0: every message is supervised
        if (hook_ != nullptr) {
            hook_->apply(at);
        }
        if (entry.supervised && !entry.timed_out && at - entry.last_rx > entry.timeout) {
            entry.timed_out = true;
            result.timed_out[i] = true;
            ++result.count;
        }
        entries_[i] = entry;
    }
    if (hook_ != nullptr) {
        hook_->attach(nullptr);
    }
    if (result.count > 0) {
        result.t_ms = now;
    }
}

}  // namespace vstatd
