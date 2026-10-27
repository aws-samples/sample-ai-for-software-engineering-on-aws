// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include "frame_decoder.h"

#include <cstdlib>

namespace vstatd {

namespace {

constexpr std::uint32_t kMaxCanId = 0x7FF;
constexpr std::size_t kMaxTimeDigits = 19;

struct Cursor {
    const char* text;
    std::size_t length;
    std::size_t pos;
};

bool at_end(const Cursor& c) { return c.pos >= c.length; }

bool is_digit(char c) { return c >= '0' && c <= '9'; }

// One separating space.
bool skip_space(Cursor& c) {
    if (at_end(c) || c.text[c.pos] != ' ') {
        return false;
    }
    ++c.pos;
    return true;
}

bool read_decimal(Cursor& c, std::uint64_t& value) {
    const std::size_t start = c.pos;
    std::uint64_t v = 0;
    while (!at_end(c) && is_digit(c.text[c.pos])) {
        if (c.pos - start >= kMaxTimeDigits) {
            return false;
        }
        v = v * 10U + static_cast<std::uint64_t>(c.text[c.pos] - '0');
        ++c.pos;
    }
    if (c.pos == start) {
        return false;
    }
    value = v;
    return true;
}

bool read_can_id(Cursor& c, std::uint32_t& value) {
    const std::size_t start = c.pos;
    std::uint32_t v = 0;
    while (!at_end(c) && c.text[c.pos] != ' ') {
        const int nibble = hex_nibble(static_cast<signed char>(c.text[c.pos]));
        if (nibble < 0 || c.pos - start >= 3) {
            return false;
        }
        v = (v << 4U) | static_cast<std::uint32_t>(nibble);
        ++c.pos;
    }
    if (c.pos == start || v > kMaxCanId) {
        return false;
    }
    value = v;
    return true;
}

bool read_data(Cursor& c, Record& out) {
    for (std::size_t i = 0; i < out.dlc; ++i) {
        if (c.pos + 2 > c.length) {
            return false;
        }
        const int hi = hex_nibble(static_cast<signed char>(c.text[c.pos]));
        const int lo = hex_nibble(static_cast<signed char>(c.text[c.pos + 1]));
        if (hi < 0 || lo < 0) {
            return false;
        }
        out.data[i] = static_cast<std::uint8_t>((hi << 4) | lo);
        c.pos += 2;
    }
    return true;
}

}  // namespace

int hex_nibble(signed char c) {
    int v = c;
    if (v >= '0' && v <= '9') {
        return v - '0';
    }
    if (v >= 'a' && v <= 'f') {
        return v - 'a' + 10;
    }
    if (v >= 'A' && v <= 'F') {
        return v - 'A' + 10;
    }
    return -1;
}

bool parse_record(const char* line, std::size_t length, Record& out) {
    if (line == nullptr || length < 3) {
        return false;
    }
    Cursor c{line, length, 1};
    Record r;
    if (line[0] == 'H') {
        r.kind = RecordKind::kHeartbeat;
        if (!skip_space(c) || !read_decimal(c, r.t_us) || !at_end(c)) {
            return false;
        }
        out = r;
        return true;
    }
    if (line[0] != 'F') {
        return false;
    }
    r.kind = RecordKind::kFrame;
    if (!skip_space(c) || !read_decimal(c, r.t_us) || !skip_space(c) || !read_can_id(c, r.can_id) ||
        !skip_space(c) || at_end(c) || !is_digit(line[c.pos])) {
        return false;
    }
    char* end = nullptr;
    const int dlc = std::strtoul(line + c.pos, &end, 10);
    if (end != line + c.pos + 1 || dlc > 8) {
        return false;
    }
    ++c.pos;
    r.dlc = static_cast<std::uint8_t>(dlc);
    if (r.dlc > 0 && !skip_space(c)) {
        return false;
    }
    if (r.dlc == 0 && !at_end(c) && !skip_space(c)) {
        return false;
    }
    if (!read_data(c, r) || !at_end(c)) {
        return false;
    }
    out = r;
    return true;
}

std::uint64_t scale_unsigned(std::uint32_t raw, const SignalDef& def) {
    // raw has at most 24 bits and the largest integer factor is 100, so the product stays below 2^32.
    std::uint64_t physical{raw * def.int_factor};
    return physical;
}

FrameDecoder::FrameDecoder() : records_(0U), rejected_(0U), decoded_(0U) {
    // Ported from the C gateway library, where decoder_init(struct decoder *d) cleared the error state.
    FrameDecoder* const d = this;
    d->last_error_ = static_cast<std::uint8_t>(DecodeError::kNone);
}

bool FrameDecoder::accept(const char* line, std::size_t length, Record& out) {
    ++records_;
    if (!parse_record(line, length, out)) {
        ++rejected_;
        last_error_ = static_cast<std::uint8_t>(DecodeError::kFormat);
        return false;
    }
    if (out.kind == RecordKind::kFrame && message_index(out.can_id) != kNoMessage && out.dlc < 8) {
        ++rejected_;
        last_error_ = static_cast<std::uint8_t>(DecodeError::kShortDlc);
        return false;
    }
    last_error_ = static_cast<std::uint8_t>(DecodeError::kNone);
    return true;
}

std::int32_t FrameDecoder::raw_value(const Record& record, const SignalDef& def) {
    ++decoded_;
    std::uint64_t payload = 0;
    for (std::size_t i = record.data.size(); i > 0; --i) {
        payload = (payload << 8U) | record.data[i - 1];
    }
    const std::uint64_t mask = (std::uint64_t{1} << def.length) - 1U;
    const std::uint64_t bits = (payload >> def.start_bit) & mask;
    if (def.encoding == Encoding::kSigned || def.encoding == Encoding::kSelectedGear) {
        const std::uint64_t sign = std::uint64_t{1} << (def.length - 1U);
        if ((bits & sign) != 0U) {
            return static_cast<std::int32_t>(static_cast<std::int64_t>(bits) - static_cast<std::int64_t>(mask) - 1);
        }
    }
    return static_cast<std::int32_t>(bits);
}

}  // namespace vstatd
