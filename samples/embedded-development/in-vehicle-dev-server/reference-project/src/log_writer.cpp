// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include "log_writer.h"

#include <cstdio>

namespace vstatd {

namespace {

std::string escape(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (const char c : text) {
        if (c == '"' || c == '\\') {
            out.push_back('\\');
            out.push_back(c);
        } else if (static_cast<unsigned char>(c) < 0x20U) {
            out.append("\\u00");
            out.push_back("0123456789abcdef"[(static_cast<unsigned char>(c) >> 4U) & 0x0FU]);
            out.push_back("0123456789abcdef"[static_cast<unsigned char>(c) & 0x0FU]);
        } else {
            out.push_back(c);
        }
    }
    return out;
}

}  // namespace

void JournalSink::write(const std::string& line) {
    (void)std::fwrite(line.data(), 1, line.size(), stdout);
    (void)std::fputc('\n', stdout);
    (void)std::fflush(stdout);
}

std::string to_field(std::int64_t value) { return std::to_string(value); }

LogWriter::LogWriter(LogSink& sink) : sink_(sink), start_(std::chrono::steady_clock::now()) {}

std::int64_t LogWriter::now_ms() const {
    const auto elapsed = std::chrono::steady_clock::now() - start_;
    return std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count();
}

std::string LogWriter::format(std::int64_t t_ms, const char* name, const std::vector<Field>& fields) const {
    std::string line = "{\"t_ms\":" + std::to_string(t_ms) + ",\"ev\":\"" + name + "\"";
    for (std::size_t i = 0; i < fields.size(); ++i) {
        line = line + ",\"" + fields[i].key + "\":\"" + escape(fields[i].value) + "\"";
    }
    line += "}";
    return line;
}

void LogWriter::write_locked(const char* name, const std::vector<Field>& fields) {
    sink_.write(format(now_ms(), name, fields));
}

void LogWriter::event(const char* name, std::initializer_list<Field> fields) {
    const std::vector<Field> list(fields);
    const std::lock_guard<std::mutex> lock(mutex_);
    write_locked(name, list);
}

bool LogWriter::limited(const std::string& kind, std::chrono::milliseconds interval, const char* name,
                        std::vector<Field> fields) {
    const auto now = std::chrono::steady_clock::now();
    const std::lock_guard<std::mutex> lock(mutex_);
    auto it = rates_.find(kind);
    if (it != rates_.end() && now - it->second.last < interval) {
        ++it->second.suppressed;
        return false;
    }
    if (it == rates_.end()) {
        it = rates_.emplace(kind, RateState{}).first;
    }
    fields.push_back(Field{"suppressed", std::to_string(it->second.suppressed)});
    it->second.last = now;
    it->second.suppressed = 0;
    write_locked(name, fields);
    return true;
}

void LogWriter::forget(const std::string& prefix) {
    const std::lock_guard<std::mutex> lock(mutex_);
    auto it = rates_.lower_bound(prefix);
    while (it != rates_.end() && it->first.compare(0, prefix.size(), prefix) == 0) {
        it = rates_.erase(it);
    }
}

}  // namespace vstatd
