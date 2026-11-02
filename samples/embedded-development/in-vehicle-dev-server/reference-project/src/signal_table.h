// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Latest value and status of every published signal (VSTATD-IF §3.4), shared by the gateway side, which writes it,
// and the IPC side, which answers GET from it.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <string>

#include "signal_defs.h"

namespace vstatd {

enum class Status : std::uint8_t { kUnavailable, kInvalid, kAvailable };

const char* status_name(Status status);

// What the decoding step concluded about a raw value.
enum class Verdict : std::uint8_t { kValue, kNotAvailable, kOutOfRange, kFlagError, kLost };

struct SignalValue {
    std::int64_t t_ms = 0;  // CC-1 monotonic clock since boot (VSTATD-IF §5.3)
    std::int32_t raw = 0;
    Status status = Status::kUnavailable;
    std::array<char, 16> text{{'-', '\0'}};
};

struct Reading {
    std::int64_t t_ms = 0;
    std::int32_t raw = 0;
    Verdict verdict = Verdict::kNotAvailable;
    const char* text = "-";
};

constexpr std::size_t kNotFound = kSignalCount;

class SignalTable {
public:
    SignalTable();
    virtual ~SignalTable() = default;
    SignalTable(const SignalTable&) = delete;
    SignalTable& operator=(const SignalTable&) = delete;

    // Stores the result of a decoding step for one signal. Virtual so that tests can observe the updates.
    virtual void update(std::string path, const Reading& reading);

    // Value and status of one signal, for GET.
    SignalValue get(std::size_t index) const;

    // Index of the signal with this path, or kNotFound.
    std::size_t find(const char* path) const;

    std::uint64_t updates() const;

private:
    struct Entry {
        std::uint32_t key = 0;
        const SignalDef* def = nullptr;
        SignalValue value;
    };

    static std::uint32_t path_key(const char* path);

    mutable std::mutex mutex_;
    std::uint64_t updates_ = 0;
    Entry entries_[24];  // kSignalCount
};

}  // namespace vstatd
