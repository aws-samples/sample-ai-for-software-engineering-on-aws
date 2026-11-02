// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include <gtest/gtest.h>

#include "supervisor.h"

using namespace vstatd;
using std::chrono::milliseconds;

namespace {

constexpr std::size_t kSpeed = 1;     // VCU_Speed, timeout 60 ms
constexpr std::size_t kOdometer = 3;  // VCU_Odometer, timeout 3000 ms

// Every message has had a frame at t0, so supervision is running for all of them.
Supervisor running(TimePoint t0) {
    Supervisor s(milliseconds(2000), milliseconds(500));
    s.reset(t0);
    for (std::size_t m = 0; m < kMessageCount; ++m) {
        s.on_frame(m, t0);
    }
    return s;
}

}  // namespace

TEST(Supervisor, MessageTimesOutAfterItsTimeout) {
    const TimePoint t0 = Clock::now();
    Supervisor s = running(t0);
    CheckResult r;
    s.check(t0 + milliseconds(60), 60, r);
    EXPECT_EQ(r.count, 0U);
    s.check(t0 + milliseconds(61), 61, r);
    EXPECT_EQ(r.count, 1U);
    EXPECT_TRUE(r.timed_out[kSpeed]);
    EXPECT_EQ(r.t_ms, 61);
    EXPECT_TRUE(s.timed_out(kSpeed));
    EXPECT_FALSE(s.timed_out(kOdometer));
}

TEST(Supervisor, TimeoutIsReportedOnce) {
    const TimePoint t0 = Clock::now();
    Supervisor s = running(t0);
    CheckResult r;
    s.check(t0 + milliseconds(100), 100, r);
    EXPECT_TRUE(r.timed_out[kSpeed]);
    s.check(t0 + milliseconds(200), 200, r);
    EXPECT_FALSE(r.timed_out[kSpeed]);
}

TEST(Supervisor, FrameEndsTimeout) {
    const TimePoint t0 = Clock::now();
    Supervisor s = running(t0);
    CheckResult r;
    s.check(t0 + milliseconds(100), 100, r);
    EXPECT_TRUE(s.on_frame(kSpeed, t0 + milliseconds(110)));
    EXPECT_FALSE(s.timed_out(kSpeed));
    EXPECT_FALSE(s.on_frame(kSpeed, t0 + milliseconds(120)));
}

TEST(Supervisor, SeveralMessagesInOneCheck) {
    const TimePoint t0 = Clock::now();
    Supervisor s = running(t0);
    CheckResult r;
    s.check(t0 + milliseconds(301), 301, r);
    EXPECT_EQ(r.count, 6U);
    EXPECT_FALSE(r.timed_out[kOdometer]);
}

TEST(Supervisor, GatewaySilence) {
    const TimePoint t0 = Clock::now();
    Supervisor s = running(t0);
    s.on_line(t0);
    EXPECT_FALSE(s.gateway_silent(t0 + milliseconds(500)));
    EXPECT_TRUE(s.gateway_silent(t0 + milliseconds(501)));
}
