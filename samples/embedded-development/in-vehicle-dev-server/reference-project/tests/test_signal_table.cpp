// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include <gtest/gtest.h>

#include <memory>
#include <string>

#include "signal_table.h"

using namespace vstatd;

TEST(SignalTable, FindsEveryPublishedPath) {
    const auto table = std::make_unique<SignalTable>();
    for (std::size_t i = 0; i < kSignalCount; ++i) {
        EXPECT_EQ(table->find(kSignals[i].path), i) << kSignals[i].path;
    }
}

TEST(SignalTable, StartsUnavailable) {
    const auto table = std::make_unique<SignalTable>();
    const SignalValue v = table->get(2);
    EXPECT_EQ(v.status, Status::kUnavailable);
    EXPECT_STREQ(v.text.data(), "-");
}

TEST(SignalTable, UpdateSetsStatusFromVerdict) {
    const auto table = std::make_unique<SignalTable>();
    Reading r;
    r.t_ms = 1234;
    r.raw = 2500;
    r.verdict = Verdict::kValue;
    r.text = "25.00";
    table->update("Vehicle.Speed", r);
    SignalValue v = table->get(2);
    EXPECT_EQ(v.status, Status::kAvailable);
    EXPECT_STREQ(v.text.data(), "25.00");
    EXPECT_EQ(v.t_ms, 1234);

    r.verdict = Verdict::kOutOfRange;
    table->update("Vehicle.Speed", r);
    v = table->get(2);
    EXPECT_EQ(v.status, Status::kInvalid);
    EXPECT_STREQ(v.text.data(), "-");

    r.verdict = Verdict::kNotAvailable;
    table->update("Vehicle.Speed", r);
    EXPECT_EQ(table->get(2).status, Status::kUnavailable);
    EXPECT_EQ(table->updates(), 3U);
}

TEST(SignalTable, LongTextIsCut) {
    const auto table = std::make_unique<SignalTable>();
    Reading r;
    r.verdict = Verdict::kValue;
    r.text = "12345678901234567890";
    table->update("Vehicle.TraveledDistance", r);
    EXPECT_EQ(std::string(table->get(6).text.data()).size(), 15U);
}

TEST(StatusName, Names) {
    EXPECT_STREQ(status_name(Status::kAvailable), "AVAILABLE");
    EXPECT_STREQ(status_name(Status::kInvalid), "INVALID");
    EXPECT_STREQ(status_name(Status::kUnavailable), "UNAVAILABLE");
}
