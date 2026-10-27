// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// The vstatd service: the gateway side (connection, decoding, supervision, value logging) runs in run(); the IPC
// side runs in the IpcServer thread.
#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>

#include "config.h"
#include "ipc_server.h"
#include "log_writer.h"
#include "signal_defs.h"
#include "signal_table.h"

namespace vstatd {

constexpr const char* kVersion = "2.7.0";

// Plausibility counters: combinations of values that a healthy vehicle network does not send. Counted only; they
// change nothing that vstatd publishes or logs.
struct PlausibilityStats {
    std::uint64_t speed_jumps = 0;        // more than 20 km/h between two frames of VCU_Speed
    std::uint64_t low_voltage_on = 0;     // below 9 V while the low-voltage system is ON or START
    std::uint64_t odometer_backwards = 0;
    std::uint64_t soc_jumps = 0;          // more than 5 percent between two frames of BMS_Status
    std::uint64_t range_jumps = 0;        // more than 50 km between two frames of BMS_Status
    std::uint64_t tyre_low = 0;           // a tyre below 150 kPa
    std::uint64_t temperature_jumps = 0;  // more than 10 Celsius between two frames of BCM_Exterior
    std::uint64_t park_while_moving = 0;  // park selected above 5 km/h
    std::uint64_t door_open_moving = 0;   // driver or passenger door open above 5 km/h
    std::uint64_t unbelted_moving = 0;    // driver not belted above 25 km/h
};

// Bench diagnostics of the gateway side. Not part of the interface; read by tests and debugging tools.
struct ServiceStats {
    std::uint64_t lines = 0;
    std::uint64_t bytes = 0;
    std::size_t longest_line = 0;
    std::uint64_t frames = 0;
    std::uint64_t heartbeats = 0;
    std::uint64_t ignored = 0;
    std::uint64_t invalid = 0;
    std::uint64_t timeouts = 0;
    std::uint64_t connects = 0;
    std::uint64_t failed_connects = 0;
    std::uint64_t losses = 0;
    std::uint64_t gateway_restarts = 0;      // gateway time went backwards on one connection
    std::int64_t max_heartbeat_gap_ms = 0;
    std::array<std::uint64_t, kMessageCount> message_frames{};
    std::array<std::int64_t, kMessageCount> max_frame_gap_ms{};  // longest gap between two frames of a message
    std::array<std::uint64_t, kMessageCount> unused_bits{};      // frames with bits set outside the signals
    std::array<std::uint64_t, kSignalCount> sna{};               // decoding steps with the SNA value
    std::array<std::uint64_t, kSignalCount> invalid_values{};    // decoding steps with an INVALID result
    std::array<std::uint64_t, kMessageCount> message_timeouts{};
    std::array<std::uint32_t, kMessageCount> frames_last_second{};  // frames per message in the last full second
    std::uint64_t losses_silence = 0;
    std::uint64_t losses_closed = 0;
    std::uint64_t losses_error = 0;
    std::uint64_t unknown_ids = 0;                                // distinct CAN IDs that are not ours
    std::int64_t max_step_us = 0;                                 // longest decoding step
    std::int64_t total_step_us = 0;
    // The last gateway records, oldest first after `recorder_next`, for a post-mortem look at the bench.
    std::array<std::array<char, 64>, 16> recorder{};
    std::size_t recorder_next = 0;
    PlausibilityStats plausibility;
};

class Service {
public:
    Service(const Config& config, LogWriter& log);
    ~Service();
    Service(const Service&) = delete;
    Service& operator=(const Service&) = delete;

    // Creates the IPC socket and starts the IPC thread (VSTATD-IF §8.1). False when the socket cannot be created.
    bool start_ipc();

    // Runs the gateway side until stop() is called. Returns the exit status.
    int run();

    // Ends run(); callable from any thread.
    void stop();

    // Stops the IPC side (VSTATD-IF §8.2).
    void shutdown();

    SignalTable& table() { return *table_; }
    IpcServer& ipc() { return ipc_; }
    ServiceStats stats() const;

private:
    bool stop_requested() const { return stop_.load(); }
    void wait_for_stop(int timeout_ms) const;

    const Config& config_;
    LogWriter& log_;
    std::unique_ptr<SignalTable> table_;
    IpcServer ipc_;
    std::atomic<bool> stop_{false};
    int stop_rd_ = -1;
    int stop_wr_ = -1;
    mutable std::mutex stats_mutex_;
    ServiceStats stats_;
};

}  // namespace vstatd
