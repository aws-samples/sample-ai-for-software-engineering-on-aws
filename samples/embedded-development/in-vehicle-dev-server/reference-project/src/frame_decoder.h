// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Gateway records (VSTATD-IF §2.2) and raw-value decoding (§2.3, §3.3).
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "signal_defs.h"

namespace vstatd {

enum class RecordKind : std::uint8_t { kFrame, kHeartbeat };

struct Record {
    std::uint64_t t_us = 0;
    std::uint32_t can_id = 0;
    RecordKind kind = RecordKind::kHeartbeat;
    std::uint8_t dlc = 0;
    std::array<std::uint8_t, 8> data{};
};

// Why the decoder refused the last record; GATEWAY_RECORD_INVALID reason (VSTATD-IF §7.4).
enum class DecodeError : std::uint8_t { kNone, kFormat, kShortDlc };

// Parses one gateway record without its newline. Returns false when it does not match VSTATD-IF §2.2.
bool parse_record(const char* line, std::size_t length, Record& out);

// Value of one hexadecimal digit, or -1.
int hex_nibble(signed char c);

// raw * factor for the signals with an integer factor (VSTATD-IF §3.3).
std::uint64_t scale_unsigned(std::uint32_t raw, const SignalDef& def);

class FrameDecoder {
public:
    FrameDecoder();

    // Parses a record and checks it against the message table (VSTATD-IF §2.5). Returns false when the record
    // cannot be used; last_error() then says why. Frames of unknown messages are accepted (and ignored later).
    bool accept(const char* line, std::size_t length, Record& out);

    // Raw value of one signal of a frame, sign-extended for signed signals (little-endian, VSTATD-IF §2.3).
    std::int32_t raw_value(const Record& record, const SignalDef& def);

    DecodeError last_error() const { return static_cast<DecodeError>(last_error_); }
    std::uint32_t records() const { return records_; }
    std::uint32_t rejected() const { return rejected_; }
    std::uint64_t decoded() const { return decoded_; }

private:
    std::uint32_t records_;
    std::uint32_t rejected_;
    std::uint64_t decoded_;
    std::uint8_t last_error_;  // a DecodeError
};

}  // namespace vstatd
