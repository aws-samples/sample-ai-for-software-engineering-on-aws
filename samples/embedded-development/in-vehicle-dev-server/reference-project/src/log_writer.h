// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Runtime log: one JSON object per line on standard output (CC1-PN §5), events of VSTATD-IF §7.1 and the rate
// limits of §6.5.
#pragma once

#include <chrono>
#include <cstdint>
#include <initializer_list>
#include <map>
#include <mutex>
#include <string>
#include <vector>

namespace vstatd {

class LogSink {
public:
    virtual ~LogSink() = default;
    virtual void write(const std::string& line) = 0;
};

// Standard output; the journal stores it on CC-1.
class JournalSink : public LogSink {
public:
    void write(const std::string& line);
};

struct Field {
    const char* key;
    std::string value;
};

class LogWriter {
public:
    explicit LogWriter(LogSink& sink);

    // Writes one event now.
    void event(const char* name, std::initializer_list<Field> fields);

    // Writes one event unless an event of the same kind was written within the interval (VSTATD-IF §6.5), with
    // the count of entries suppressed since the previous one appended as "suppressed". Returns true if written.
    bool limited(const std::string& kind, std::chrono::milliseconds interval, const char* name,
                 std::vector<Field> fields);

    // Forgets the rate-limit state of every kind that starts with the prefix (a closed client).
    void forget(const std::string& prefix);

    // Milliseconds since process start (CC1-PN §5.2).
    std::int64_t now_ms() const;

    std::string format(std::int64_t t_ms, const char* name, const std::vector<Field>& fields) const;

private:
    struct RateState {
        std::chrono::steady_clock::time_point last{};
        std::uint64_t suppressed = 0;
    };

    void write_locked(const char* name, const std::vector<Field>& fields);

    LogSink& sink_;
    const std::chrono::steady_clock::time_point start_;
    std::mutex mutex_;
    std::map<std::string, RateState> rates_;
};

// Formats an integer for a log field.
std::string to_field(std::int64_t value);

}  // namespace vstatd
