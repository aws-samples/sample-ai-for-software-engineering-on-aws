// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// The signals and messages that vstatd publishes (VSTATD-IF rev 1.3 §3.1, §3.2), written out by hand from
// cc1-gateway.dbc. The order of kSignals is the order of the signal table, which LIST and the log follow.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace vstatd {

constexpr std::size_t kSignalCount = 24;
constexpr std::size_t kMessageCount = 9;
constexpr std::size_t kNoMessage = kMessageCount;

// How a raw value turns into a published value.
enum class Encoding : std::uint8_t {
    kUnsigned,      // raw * factor + offset
    kSigned,        // signed raw value, published as is
    kFlag,          // two-bit flag: 0 false, 1 true, 2 error, 3 SNA
    kLvState,       // Vehicle.LowVoltageSystemState enumeration
    kSelectedGear,  // VSS gear codes -1, 0, 126, 127
};

struct SignalDef {
    const char* path;          // VSS path published by vstatd
    std::uint8_t message;      // index into kMessages
    std::uint8_t start_bit;
    std::uint8_t length;
    Encoding encoding;
    std::uint8_t decimals;     // decimals in VAL lines and in the runtime log
    std::uint32_t int_factor;  // integer factor; 0 when the factor is fractional
    double factor;
    double offset;
    double min;                // valid range, physical value
    double max;
    std::int32_t sna_raw;
    std::uint32_t deadband_raw;  // log deadband in raw units (VSTATD-IF §7.2); 1 means any change
};

struct MessageDef {
    const char* name;
    std::uint16_t can_id;
    std::uint16_t timeout_ms;  // 3 x the cycle time of the DBC (GenMsgCycleTime)
    std::uint8_t first_signal;
    std::uint8_t signal_count;
};

extern const std::array<SignalDef, kSignalCount> kSignals;
extern const std::array<MessageDef, kMessageCount> kMessages;

// Index into kMessages of the message with this CAN ID, or kNoMessage.
std::size_t message_index(std::uint32_t can_id);

}  // namespace vstatd
