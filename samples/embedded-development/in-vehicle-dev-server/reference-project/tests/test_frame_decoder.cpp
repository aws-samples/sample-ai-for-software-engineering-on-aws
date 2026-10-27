// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include <gtest/gtest.h>

#include <cstring>
#include <string>

#include "frame_decoder.h"
#include "signal_defs.h"

using namespace vstatd;

namespace {

bool parse(const std::string& line, Record& r) { return parse_record(line.data(), line.size(), r); }

Record frame(const std::string& line) {
    Record r;
    EXPECT_TRUE(parse(line, r)) << line;
    return r;
}

}  // namespace

TEST(ParseRecord, Frame) {
    const Record r = frame("F 1532000 101 8 C409000000000000");
    EXPECT_EQ(r.kind, RecordKind::kFrame);
    EXPECT_EQ(r.t_us, 1532000U);
    EXPECT_EQ(r.can_id, 0x101U);
    EXPECT_EQ(r.dlc, 8);
    EXPECT_EQ(r.data[0], 0xC4);
    EXPECT_EQ(r.data[1], 0x09);
}

TEST(ParseRecord, Heartbeat) {
    const Record r = frame("H 1600000");
    EXPECT_EQ(r.kind, RecordKind::kHeartbeat);
    EXPECT_EQ(r.t_us, 1600000U);
}

TEST(ParseRecord, LowerCaseHex) {
    const Record r = frame("F 1 7ff 8 c4090000000000ab");
    EXPECT_EQ(r.can_id, 0x7FFU);
    EXPECT_EQ(r.data[7], 0xAB);
}

TEST(ParseRecord, ShortFrameParses) {
    const Record r = frame("F 10 101 2 C409");
    EXPECT_EQ(r.dlc, 2);
}

TEST(ParseRecord, Rejects) {
    Record r;
    for (const char* bad : {"", "X 1", "H", "H ", "H 12a", "H  12", "F 1 101 8", "F 1 101 8 C40900000000000",
                            "F 1 101 8 C4090000000000000", "F 1 800 8 0000000000000000", "F 1 101 9 000000000000000000",
                            "F 1 101 8 G409000000000000", "F x 101 8 0000000000000000", "F 1  101 8 0000000000000000",
                            "F 1 101 -1 00", "F 1 1011 8 0000000000000000", "H 1 2"}) {
        EXPECT_FALSE(parse(bad, r)) << '"' << bad << '"';
    }
}

TEST(HexNibble, Digits) {
    EXPECT_EQ(hex_nibble('0'), 0);
    EXPECT_EQ(hex_nibble('9'), 9);
    EXPECT_EQ(hex_nibble('a'), 10);
    EXPECT_EQ(hex_nibble('F'), 15);
    EXPECT_EQ(hex_nibble('g'), -1);
}

TEST(FrameDecoder, RawValuesAreLittleEndian) {
    FrameDecoder d;
    // VCU_Speed raw 0x09C4 = 2500 (25.00 km/h), VSTATD-IF §2.2 example.
    EXPECT_EQ(d.raw_value(frame("F 1 101 8 C409000000000000"), kSignals[2]), 2500);
    // VCU_PowerState: LvSystemState bits 0-2, LvBatteryVoltage bits 8-17.
    const Record power = frame("F 1 100 8 04A2020000000000");
    EXPECT_EQ(d.raw_value(power, kSignals[0]), 4);
    EXPECT_EQ(d.raw_value(power, kSignals[1]), 0x2A2);
    // VCU_Odometer: 24 bits.
    EXPECT_EQ(d.raw_value(frame("F 1 103 8 FEFFFF0000000000"), kSignals[6]), 16777214);
}

TEST(FrameDecoder, SignedValues) {
    FrameDecoder d;
    const Record gear = frame("F 1 102 8 FF7E010000000000");
    EXPECT_EQ(d.raw_value(gear, kSignals[3]), -1);
    EXPECT_EQ(d.raw_value(gear, kSignals[4]), 126);
    EXPECT_EQ(d.raw_value(gear, kSignals[5]), 1);
    EXPECT_EQ(d.raw_value(frame("F 1 102 8 8080000000000000"), kSignals[3]), -128);
}

TEST(FrameDecoder, TwoBitFlags) {
    FrameDecoder d;
    // BCM_Lights: low beam 1, high beam 0, left 2, right 3, hazard 1.
    const Record lights = frame("F 1 300 8 E101000000000000");
    EXPECT_EQ(d.raw_value(lights, kSignals[10]), 1);
    EXPECT_EQ(d.raw_value(lights, kSignals[11]), 0);
    EXPECT_EQ(d.raw_value(lights, kSignals[12]), 2);
    EXPECT_EQ(d.raw_value(lights, kSignals[13]), 3);
    EXPECT_EQ(d.raw_value(lights, kSignals[14]), 1);
}

TEST(FrameDecoder, AcceptChecksDlcOfKnownMessages) {
    FrameDecoder d;
    Record r;
    const std::string short_frame = "F 1 101 2 C409";
    EXPECT_FALSE(d.accept(short_frame.data(), short_frame.size(), r));
    EXPECT_EQ(d.last_error(), DecodeError::kShortDlc);
    const std::string unknown = "F 1 555 2 C409";
    EXPECT_TRUE(d.accept(unknown.data(), unknown.size(), r));
    const std::string garbage = "hello";
    EXPECT_FALSE(d.accept(garbage.data(), garbage.size(), r));
    EXPECT_EQ(d.last_error(), DecodeError::kFormat);
    EXPECT_EQ(d.records(), 3U);
    EXPECT_EQ(d.rejected(), 2U);
}

TEST(ScaleUnsigned, IntegerFactors) {
    EXPECT_EQ(scale_unsigned(16777214U, kSignals[6]), 1677721400U);
    EXPECT_EQ(scale_unsigned(65534U, kSignals[8]), 655340U);
    EXPECT_EQ(scale_unsigned(250U, kSignals[19]), 500U);
}
