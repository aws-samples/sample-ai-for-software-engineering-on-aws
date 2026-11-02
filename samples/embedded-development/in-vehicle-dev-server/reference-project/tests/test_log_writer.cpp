// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include <gtest/gtest.h>

#include <regex>
#include <thread>

#include "log_writer.h"
#include "test_util.h"

using namespace vstatd;

TEST(LogWriter, JsonLineInPlatformFormat) {
    vstatd_test::MemorySink sink;
    LogWriter log(sink);
    log.event("SIGNAL_VALUE", {Field{"path", "Vehicle.Speed"}, Field{"value", "0.00"}, Field{"status", "AVAILABLE"}});
    const auto lines = sink.lines();
    ASSERT_EQ(lines.size(), 1U);
    // CC1-PN §5.2: t_ms first (integer), then ev, then the fields in table order, all strings.
    const std::regex format(R"(\{"t_ms":\d+,"ev":"SIGNAL_VALUE","path":"Vehicle\.Speed","value":"0\.00","status":"AVAILABLE"\})");
    EXPECT_TRUE(std::regex_match(lines[0], format)) << lines[0];
}

TEST(LogWriter, EventWithoutFields) {
    vstatd_test::MemorySink sink;
    LogWriter log(sink);
    log.event("GATEWAY_CONNECTED", {});
    EXPECT_TRUE(std::regex_match(sink.lines().at(0), std::regex(R"(\{"t_ms":\d+,"ev":"GATEWAY_CONNECTED"\})")));
}

TEST(LogWriter, EscapesQuotes) {
    vstatd_test::MemorySink sink;
    LogWriter log(sink);
    log.event("X", {Field{"a", "say \"hi\"\\"}});
    EXPECT_NE(sink.lines().at(0).find(R"("a":"say \"hi\"\\")"), std::string::npos);
}

TEST(LogWriter, RateLimitCountsSuppressedEntries) {
    vstatd_test::MemorySink sink;
    LogWriter log(sink);
    const auto interval = std::chrono::milliseconds(200);
    EXPECT_TRUE(log.limited("K/1", interval, "GATEWAY_RECORD_INVALID", {Field{"reason", "format"}}));
    EXPECT_FALSE(log.limited("K/1", interval, "GATEWAY_RECORD_INVALID", {Field{"reason", "format"}}));
    EXPECT_FALSE(log.limited("K/1", interval, "GATEWAY_RECORD_INVALID", {Field{"reason", "format"}}));
    // Another kind is limited on its own.
    EXPECT_TRUE(log.limited("K/2", interval, "GATEWAY_RECORD_INVALID", {Field{"reason", "short_dlc"}}));
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    EXPECT_TRUE(log.limited("K/1", interval, "GATEWAY_RECORD_INVALID", {Field{"reason", "format"}}));
    const auto lines = sink.lines();
    ASSERT_EQ(lines.size(), 3U);
    EXPECT_NE(lines[0].find(R"("reason":"format","suppressed":"0")"), std::string::npos);
    EXPECT_NE(lines[1].find(R"("reason":"short_dlc","suppressed":"0")"), std::string::npos);
    EXPECT_NE(lines[2].find(R"("reason":"format","suppressed":"2")"), std::string::npos);
}

TEST(LogWriter, ForgetDropsState) {
    vstatd_test::MemorySink sink;
    LogWriter log(sink);
    const auto interval = std::chrono::seconds(10);
    EXPECT_TRUE(log.limited("REQUEST_ERROR/7", interval, "REQUEST_ERROR", {}));
    EXPECT_FALSE(log.limited("REQUEST_ERROR/7", interval, "REQUEST_ERROR", {}));
    log.forget("REQUEST_ERROR/7");
    EXPECT_TRUE(log.limited("REQUEST_ERROR/7", interval, "REQUEST_ERROR", {}));
}

TEST(LogWriter, TimeCountsFromStart) {
    vstatd_test::MemorySink sink;
    const LogWriter log(sink);
    EXPECT_LT(log.now_ms(), 1000);
}
