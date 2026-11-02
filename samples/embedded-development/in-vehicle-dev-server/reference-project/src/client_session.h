// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// One app connected to the IPC socket: its requests (VSTATD-IF §5.2), subscriptions and outgoing queue (§5.4).
#pragma once

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "log_writer.h"
#include "signal_table.h"

namespace vstatd {

using SessionClock = std::chrono::steady_clock;

constexpr std::size_t kMaxLine = 256;          // bytes per line, newline included (VSTATD-IF §5.1)
constexpr std::size_t kQueueLines = 256;       // outgoing queue per client (§5.4)
constexpr std::size_t kMaxSubscriptions = 32;  // per client (§5.4)
constexpr std::uint32_t kDefaultIntervalMs = 100;
constexpr std::uint32_t kMinIntervalMs = 50;
constexpr std::uint32_t kMaxIntervalMs = 10000;

// Latest published value of a signal and a counter that changes whenever its value or status changes.
struct Published {
    SignalValue value;
    std::uint64_t seq = 0;
};

using PublishedTable = std::array<Published, kSignalCount>;

struct RequestContext {
    SignalTable& table;
    const PublishedTable& published;
    SessionClock::time_point now;
};

struct Peer {
    int fd;
    std::uint32_t id;
    LogWriter* log;
};

// A line prepared once and queued to several clients.
struct OutLine {
    std::array<char, kMaxLine> text;
    std::uint16_t length;
    std::uint8_t signal;
};

enum class ErrorCode : std::uint8_t { kE01, kE02, kE03, kE04, kE05, kE06 };

const char* error_line(ErrorCode code);
const char* error_name(ErrorCode code);

// Formats a VAL line (VSTATD-IF §5.3) into out; returns its length including the newline.
std::size_t format_val(const SignalValue& value, std::size_t signal, OutLine& out);

std::optional<std::uint32_t> parse_interval(const std::string& text);

class ClientSession {
public:
    explicit ClientSession(const Peer& peer) : fd_(peer.fd), id_(peer.id), log_(peer.log) {}
    ~ClientSession();
    ClientSession(const ClientSession&) = delete;
    ClientSession& operator=(const ClientSession&) = delete;

    std::uint32_t id() const { return id_; }
    int fd() const { return fd_; }

    // Reads and handles what the client sent. Returns false when the client closed the connection.
    bool on_readable(const RequestContext& ctx);

    // Handles one request line without its newline.
    void parse_line(const std::string& line, const RequestContext& ctx);

    // Writes queued lines without blocking. Returns false on a broken connection.
    bool flush();
    bool wants_write() const { return count_ > 0; }

    // Queues a line; when the queue is full the oldest line is dropped (VSTATD-IF §5.4).
    void enqueue(const char* text, std::size_t length);

    // Sends the subscription updates that are due (VSTATD-IF §5.3).
    void deliver(const RequestContext& ctx);

    // Queues an UNAVAILABLE update prepared by the server, if this client subscribes to its signal.
    void push_unavailable(const OutLine& line, std::uint64_t seq);

    // Earliest time at which a held-back update becomes due, or time_point::max().
    SessionClock::time_point next_due() const;

    std::size_t subscriptions() const { return subs_.size(); }
    std::size_t queued() const { return count_; }
    std::uint64_t missing_path_bytes() const { return missing_path_bytes_; }

private:
    struct Subscription {
        SessionClock::time_point last_sent{};
        std::chrono::milliseconds interval{kDefaultIntervalMs};
        std::uint64_t seen_seq = 0;
        std::uint8_t signal = 0;
        Status sent_status = Status::kUnavailable;
        bool pending = false;
    };

    void handle_get(const std::vector<std::string>& words, const RequestContext& ctx);
    void handle_sub(const std::vector<std::string>& words, const RequestContext& ctx);
    void handle_unsub(const std::vector<std::string>& words, const RequestContext& ctx);
    void handle_list();
    void reply(const char* text);
    void reply_error(ErrorCode code);
    void send_value(Subscription& sub, const Published& published, SessionClock::time_point now);
    void note_overflow(SessionClock::time_point now);

    int fd_;
    std::uint32_t id_;
    LogWriter* log_;
    std::string input_;
    bool discarding_ = false;
    std::vector<Subscription> subs_;
    std::uint64_t missing_path_bytes_ = 0;
    std::uint64_t dropped_ = 0;
    SessionClock::time_point last_overflow_log_{};
    bool overflow_logged_ = false;
    std::size_t offset_ = 0;  // bytes of the oldest line already written
    std::uint16_t head_ = 0;
    std::uint16_t count_ = 0;
    std::array<std::uint16_t, kQueueLines> lengths_{};
    std::array<std::array<char, kMaxLine>, kQueueLines> lines_;
};

}  // namespace vstatd
