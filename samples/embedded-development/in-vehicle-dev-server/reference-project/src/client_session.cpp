// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include "client_session.h"

#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include <sys/socket.h>
#include <unistd.h>

namespace vstatd {

namespace {

constexpr std::chrono::seconds kErrorLogInterval{1};     // VSTATD-IF §6.2
constexpr std::chrono::seconds kOverflowLogInterval{1};  // VSTATD-IF §5.4
constexpr std::size_t kReadChunk = 512;

std::vector<std::string> split_words(const std::string& line) {
    std::vector<std::string> words;
    std::size_t pos = 0;
    while (pos < line.size()) {
        const std::size_t next = line.find(' ', pos);
        const std::size_t end = next == std::string::npos ? line.size() : next;
        if (end > pos) {
            words.emplace_back(line, pos, end - pos);
        }
        pos = end + 1;
    }
    return words;
}

bool needs_path(const std::string& request) { return request == "GET" || request == "SUB" || request == "UNSUB"; }

std::string error_kind(std::uint32_t client) { return "REQUEST_ERROR/" + std::to_string(client); }

}  // namespace

const char* error_line(ErrorCode code) {
    switch (code) {
        case ErrorCode::kE01:
            return "ERR E01 unknown request\n";
        case ErrorCode::kE02:
            return "ERR E02 unknown path\n";
        case ErrorCode::kE03:
            return "ERR E03 line too long\n";
        case ErrorCode::kE04:
            return "ERR E04 too many subscriptions\n";
        case ErrorCode::kE05:
            return "ERR E05 interval out of range\n";
        case ErrorCode::kE06:
            break;
    }
    return "ERR E06 too many clients\n";
}

const char* error_name(ErrorCode code) {
    static const std::array<const char*, 6> kNames = {{"E01", "E02", "E03", "E04", "E05", "E06"}};
    return kNames[static_cast<std::size_t>(code)];
}

std::size_t format_val(const SignalValue& value, std::size_t signal, OutLine& out) {
    const char* text = value.status == Status::kAvailable ? value.text.data() : "-";
    const int n = std::snprintf(out.text.data(), out.text.size(), "VAL %s %s %s %lld\n", kSignals[signal].path,
                                text, status_name(value.status), static_cast<long long>(value.t_ms));
    std::size_t length = 0;
    if (n > 0) {
        length = std::min(static_cast<std::size_t>(n), out.text.size() - 1);
    }
    out.length = static_cast<std::uint16_t>(length);
    out.signal = static_cast<std::uint8_t>(signal);
    return length;
}

std::optional<std::uint32_t> parse_interval(const std::string& text) {
    if (text.empty()) {
        return std::nullopt;
    }
    const int value = std::atoi(text.c_str());
    return static_cast<std::uint32_t>(value);
}

ClientSession::~ClientSession() {
    if (fd_ >= 0) {
        ::close(fd_);
    }
}

bool ClientSession::on_readable(const RequestContext& ctx) {
    std::array<char, kReadChunk> chunk{};
    const ssize_t n = ::recv(fd_, chunk.data(), chunk.size(), MSG_DONTWAIT);
    if (n == 0) {
        return false;
    }
    if (n < 0) {
        const int err = errno;
        return err == EAGAIN || err == EWOULDBLOCK || err == EINTR;
    }
    for (std::size_t i = 0; i < static_cast<std::size_t>(n); ++i) {
        const char c = chunk[i];
        if (c == '\n') {
            if (discarding_) {
                discarding_ = false;
            } else {
                parse_line(input_, ctx);
            }
            input_.clear();
            continue;
        }
        if (discarding_) {
            continue;
        }
        if (input_.size() + 1 >= kMaxLine) {
            // The line will not fit in 256 bytes with its newline (VSTATD-IF §5.1, §6.1 E03).
            reply_error(ErrorCode::kE03);
            input_.clear();
            discarding_ = true;
            continue;
        }
        input_.push_back(c);
    }
    return true;
}

void ClientSession::parse_line(const std::string& line, const RequestContext& ctx) {
    const std::vector<std::string> words = split_words(line);
    if (words.empty()) {
        reply_error(ErrorCode::kE01);
        return;
    }
    const std::string& first = words[0];
    const std::string request = first.substr(0);
    if (words.size() == 1 && needs_path(request)) {
        missing_path_bytes_ += words[1].size();
        reply_error(ErrorCode::kE02);
        return;
    }
    if (request == "GET") {
        handle_get(words, ctx);
    } else if (request == "SUB") {
        handle_sub(words, ctx);
    } else if (request == "UNSUB") {
        handle_unsub(words, ctx);
    } else if (request == "LIST") {
        handle_list();
    } else {
        reply_error(ErrorCode::kE01);
    }
}

void ClientSession::handle_get(const std::vector<std::string>& words, const RequestContext& ctx) {
    const std::size_t index = ctx.table.find(words[1].c_str());
    if (index == kNotFound) {
        reply_error(ErrorCode::kE02);
        return;
    }
    const SignalValue value = ctx.table.get(index);
    OutLine line{};
    const std::size_t length = format_val(value, index, line);
    enqueue(line.text.data(), length);
}

void ClientSession::handle_sub(const std::vector<std::string>& words, const RequestContext& ctx) {
    const std::size_t index = ctx.table.find(words[1].c_str());
    if (index == kNotFound) {
        reply_error(ErrorCode::kE02);
        return;
    }
    const std::optional<std::uint32_t> interval =
        words.size() > 2 ? parse_interval(words[2]) : std::optional<std::uint32_t>(kDefaultIntervalMs);
    const std::uint32_t interval_ms = *interval;
    if (interval_ms < kMinIntervalMs || interval_ms > kMaxIntervalMs) {
        reply_error(ErrorCode::kE05);
        return;
    }
    auto it = std::find_if(subs_.begin(), subs_.end(), [index](const Subscription& s) { return s.signal == index; });
    if (it == subs_.end()) {
        if (subs_.size() >= kMaxSubscriptions) {
            reply_error(ErrorCode::kE04);
            return;
        }
        subs_.emplace_back();
        it = subs_.end() - 1;
        it->signal = static_cast<std::uint8_t>(index);
    }
    it->interval = std::chrono::milliseconds(interval_ms);
    reply("OK\n");
    send_value(*it, ctx.published[index], ctx.now);
}

void ClientSession::handle_unsub(const std::vector<std::string>& words, const RequestContext& ctx) {
    const std::size_t index = ctx.table.find(words[1].c_str());
    if (index == kNotFound) {
        reply_error(ErrorCode::kE02);
        return;
    }
    subs_.erase(std::remove_if(subs_.begin(), subs_.end(), [index](const Subscription& s) { return s.signal == index; }),
                subs_.end());
    reply("OK\n");
}

void ClientSession::handle_list() {
    std::array<char, kMaxLine> line{};
    for (std::size_t i = 0; i < kSignalCount; ++i) {
        const int n = std::snprintf(line.data(), line.size(), "PATH %s\n", kSignals[i].path);
        if (n > 0) {
            enqueue(line.data(), std::min(static_cast<std::size_t>(n), line.size() - 1));
        }
    }
    reply("OK\n");
}

void ClientSession::reply(const char* text) { enqueue(text, std::strlen(text)); }

void ClientSession::reply_error(ErrorCode code) {
    reply(error_line(code));
    if (log_ != nullptr) {
        log_->limited(error_kind(id_), kErrorLogInterval, "REQUEST_ERROR",
                      {Field{"client", std::to_string(id_)}, Field{"code", error_name(code)}});
    }
}

void ClientSession::send_value(Subscription& sub, const Published& published, SessionClock::time_point now) {
    OutLine line{};
    const std::size_t length = format_val(published.value, sub.signal, line);
    enqueue(line.text.data(), length);
    sub.last_sent = now;
    sub.seen_seq = published.seq;
    sub.sent_status = published.value.status;
    sub.pending = false;
}

void ClientSession::deliver(const RequestContext& ctx) {
    for (Subscription& sub : subs_) {
        const Published& published = ctx.published[sub.signal];
        if (published.seq != sub.seen_seq) {
            sub.pending = true;
        }
        if (!sub.pending) {
            continue;
        }
        if (ctx.now - sub.last_sent >= sub.interval) {
            send_value(sub, published, ctx.now);
        }
    }
}

void ClientSession::push_unavailable(const OutLine& line, std::uint64_t seq) {
    for (Subscription& sub : subs_) {
        if (sub.signal != line.signal || sub.sent_status == Status::kUnavailable) {
            continue;
        }
        enqueue(line.text.data(), line.length);
        sub.last_sent = SessionClock::now();
        sub.seen_seq = seq;
        sub.sent_status = Status::kUnavailable;
        sub.pending = false;
    }
}

SessionClock::time_point ClientSession::next_due() const {
    SessionClock::time_point due = SessionClock::time_point::max();
    for (std::size_t i = 0; i < subs_.size(); ++i) {
        if (subs_[i].pending) {
            due = std::min(due, subs_[i].last_sent + subs_[i].interval);
        }
    }
    return due;
}

void ClientSession::note_overflow(SessionClock::time_point now) {
    ++dropped_;
    if (log_ == nullptr || (overflow_logged_ && now - last_overflow_log_ < kOverflowLogInterval)) {
        return;
    }
    log_->event("CLIENT_QUEUE_OVERFLOW", {Field{"client", std::to_string(id_)}, Field{"dropped", std::to_string(dropped_)}});
    dropped_ = 0;
    last_overflow_log_ = now;
    overflow_logged_ = true;
}

void ClientSession::enqueue(const char* text, std::size_t length) {
    const std::size_t n = std::min(length, kMaxLine);
    if (count_ == kQueueLines) {
        // Drop the oldest line that has not been started; a half-written line has to be finished first.
        const std::size_t victim = offset_ > 0 ? (head_ + 1U) % kQueueLines : head_;
        if (victim == head_) {
            head_ = static_cast<std::uint16_t>((head_ + 1U) % kQueueLines);
        } else {
            for (std::size_t k = victim; k != (head_ + count_ - 1U) % kQueueLines; k = (k + 1U) % kQueueLines) {
                const std::size_t from = (k + 1U) % kQueueLines;
                lines_[k] = lines_[from];
                lengths_[k] = lengths_[from];
            }
        }
        --count_;
        note_overflow(SessionClock::now());
    }
    const std::size_t slot = (head_ + count_) % kQueueLines;
    std::memcpy(lines_[slot].data(), text, n);
    lengths_[slot] = static_cast<std::uint16_t>(n);
    ++count_;
}

bool ClientSession::flush() {
    while (count_ > 0) {
        const std::size_t length = lengths_[head_];
        const ssize_t n = ::send(fd_, lines_[head_].data() + offset_, length - offset_, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n < 0) {
            const int err = errno;
            return err == EAGAIN || err == EWOULDBLOCK || err == EINTR;
        }
        offset_ += static_cast<std::size_t>(n);
        if (offset_ < length) {
            return true;
        }
        offset_ = 0;
        head_ = static_cast<std::uint16_t>((head_ + 1U) % kQueueLines);
        --count_;
    }
    // An empty queue starts again at its first slot.
    head_ = 0;
    return true;
}

}  // namespace vstatd
