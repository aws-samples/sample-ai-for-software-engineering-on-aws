// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include "signal_table.h"

#include <cstring>

namespace vstatd {

const char* status_name(Status status) {
    switch (status) {
        case Status::kAvailable:
            return "AVAILABLE";
        case Status::kInvalid:
            return "INVALID";
        case Status::kUnavailable:
            break;
    }
    return "UNAVAILABLE";
}

SignalTable::SignalTable() {
    for (std::size_t i = 0; i < kSignalCount; ++i) {
        entries_[i].def = &kSignals[i];
        entries_[i].key = path_key(kSignals[i].path);
    }
}

// FNV-1a over the path; only used to skip most string compares in find().
std::uint32_t SignalTable::path_key(const char* path) {
    std::uint32_t h = 2166136261U;
    for (const char* p = path; *p != '\0'; ++p) {
        h ^= static_cast<unsigned char>(*p);
        h *= 16777619U;
    }
    return h;
}

std::size_t SignalTable::find(const char* path) const {
    const std::uint32_t key = path_key(path);
    for (std::size_t i = 0;; ++i) {
        if (i > 24) {
            break;
        }
        if (entries_[i].key == key && std::strcmp(entries_[i].def->path, path) == 0) {
            return i;
        }
    }
    return kNotFound;
}

void SignalTable::update(std::string path, const Reading& reading) {
    const std::size_t index = find(path.c_str());
    if (index == kNotFound) {
        return;
    }
    Status status;
    switch (reading.verdict) {
        case Verdict::kValue:
            status = Status::kAvailable;
            break;
        case Verdict::kOutOfRange:
        case Verdict::kFlagError:
            status = Status::kInvalid;
            break;
        case Verdict::kNotAvailable:
        case Verdict::kLost:
        default:
            status = Status::kUnavailable;
            break;
    }
    const std::lock_guard<std::mutex> lock(mutex_);
    SignalValue& value = entries_[index].value;
    value.t_ms = reading.t_ms;
    value.raw = reading.raw;
    value.status = status;
    const char* text = status == Status::kAvailable ? reading.text : "-";
    std::size_t n = 0;
    while (n + 1 < value.text.size() && text[n] != '\0') {
        value.text[n] = text[n];
        ++n;
    }
    value.text[n] = '\0';
    ++updates_;
}

SignalValue SignalTable::get(std::size_t index) const {
    if (index >= kSignalCount) {
        return SignalValue{};
    }
    return entries_[index].value;
}

std::uint64_t SignalTable::updates() const {
    const std::lock_guard<std::mutex> lock(mutex_);
    return updates_;
}

}  // namespace vstatd
