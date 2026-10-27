// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// The IPC socket for apps (VSTATD-IF §5): one thread that accepts clients, answers their requests and sends
// subscription updates. The gateway side hands it new values with publish().
#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

#include "client_session.h"
#include "config.h"
#include "log_writer.h"
#include "signal_table.h"

namespace vstatd {

constexpr std::size_t kMaxClients = 16;  // VSTATD-IF §5.4

class IpcServer {
public:
    IpcServer(const Config& config, SignalTable& table, LogWriter& log);
    ~IpcServer();
    IpcServer(const IpcServer&) = delete;
    IpcServer& operator=(const IpcServer&) = delete;

    // Creates the listening socket (VSTATD-IF §5.1). False when it cannot be created (§6.4).
    bool open_listener();

    // Starts the IPC thread.
    bool start();

    // Stops accepting clients, closes every connection and joins the thread (VSTATD-IF §8.2).
    void stop();

    // New value or status of a signal, from the gateway side.
    void publish(std::size_t index, const SignalValue& value);

    std::size_t clients() const { return clients_.load(); }

private:
    void run();
    void accept_client();
    void broadcast(OutLine line);
    void wake();
    void drain_wake();

    const Config& config_;
    SignalTable& table_;
    LogWriter& log_;
    int listen_fd_ = -1;
    int wake_rd_ = -1;
    int wake_wr_ = -1;
    std::uint32_t next_id_ = 0;
    std::atomic<bool> stopping_{false};
    std::atomic<std::size_t> clients_{0};
    std::thread thread_;
    std::vector<std::unique_ptr<ClientSession>> sessions_;
    std::mutex mutex_;
    PublishedTable published_{};
    PublishedTable local_{};
    std::array<std::uint64_t, kSignalCount> seen_{};
};

}  // namespace vstatd
