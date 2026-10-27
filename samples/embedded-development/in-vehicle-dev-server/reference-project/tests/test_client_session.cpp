// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <vector>

#include <sys/socket.h>
#include <unistd.h>

#include "client_session.h"
#include "test_util.h"

using namespace vstatd;
using namespace std::chrono_literals;

namespace {

// A session on one end of a socket pair; the test is the app on the other end.
class SessionTest : public ::testing::Test {
protected:
    void SetUp() override {
        int fds[2] = {-1, -1};
        ASSERT_EQ(::socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
        app_ = fds[1];
        session_ = std::make_unique<ClientSession>(Peer{fds[0], 1, &log_});
        for (std::size_t i = 0; i < kSignalCount; ++i) {
            published_[i].value = table_->get(i);
        }
    }
    void TearDown() override { ::close(app_); }

    RequestContext ctx() const { return RequestContext{*table_, published_, SessionClock::now()}; }

    std::vector<std::string> request(const std::string& line, std::size_t expect) {
        session_->parse_line(line, ctx());
        EXPECT_TRUE(session_->flush());
        std::size_t seen = 0;
        return vstatd_test::read_until(app_, buffer_, [&seen, expect](const std::string&) { return ++seen == expect; },
                                       500ms);
    }

    vstatd_test::MemorySink sink_;
    LogWriter log_{sink_};
    std::unique_ptr<SignalTable> table_ = std::make_unique<SignalTable>();
    PublishedTable published_{};
    std::unique_ptr<ClientSession> session_;
    int app_ = -1;
    std::string buffer_;
};

}  // namespace

TEST_F(SessionTest, ListReturnsEveryPathInTableOrder) {
    const auto lines = request("LIST", kSignalCount + 1);
    ASSERT_EQ(lines.size(), kSignalCount + 1);
    for (std::size_t i = 0; i < kSignalCount; ++i) {
        EXPECT_EQ(lines[i], std::string("PATH ") + kSignals[i].path);
    }
    EXPECT_EQ(lines.back(), "OK");
}

TEST_F(SessionTest, GetBeforeAnyFrame) {
    const auto lines = request("GET Vehicle.Speed", 1);
    ASSERT_EQ(lines.size(), 1U);
    EXPECT_EQ(lines[0].rfind("VAL Vehicle.Speed - UNAVAILABLE ", 0), 0U) << lines[0];
}

TEST_F(SessionTest, GetAvailableValue) {
    Reading r;
    r.t_ms = 4242;
    r.raw = 2500;
    r.verdict = Verdict::kValue;
    r.text = "25.00";
    table_->update("Vehicle.Speed", r);
    const auto lines = request("GET Vehicle.Speed", 1);
    ASSERT_EQ(lines.size(), 1U);
    EXPECT_EQ(lines[0], "VAL Vehicle.Speed 25.00 AVAILABLE 4242");
}

TEST_F(SessionTest, SubAnswersOkThenCurrentValue) {
    const auto lines = request("SUB Vehicle.Speed 200", 2);
    ASSERT_EQ(lines.size(), 2U);
    EXPECT_EQ(lines[0], "OK");
    EXPECT_EQ(lines[1].rfind("VAL Vehicle.Speed - UNAVAILABLE", 0), 0U);
    EXPECT_EQ(session_->subscriptions(), 1U);
    // A second SUB replaces the interval.
    request("SUB Vehicle.Speed 50", 2);
    EXPECT_EQ(session_->subscriptions(), 1U);
}

TEST_F(SessionTest, UnsubOfUnsubscribedPathIsOk) {
    const auto lines = request("UNSUB Vehicle.Speed", 1);
    ASSERT_EQ(lines.size(), 1U);
    EXPECT_EQ(lines[0], "OK");
}

TEST_F(SessionTest, UnknownRequestIsE01) {
    const auto lines = request("PING", 1);
    ASSERT_EQ(lines.size(), 1U);
    EXPECT_EQ(lines[0], "ERR E01 unknown request");
    EXPECT_TRUE(sink_.contains(R"("ev":"REQUEST_ERROR","client":"1","code":"E01","suppressed":"0")"));
}

TEST_F(SessionTest, IntervalOutOfRangeIsE05) {
    EXPECT_EQ(request("SUB Vehicle.Speed 49", 1).at(0), "ERR E05 interval out of range");
    EXPECT_EQ(request("SUB Vehicle.Speed 10001", 1).at(0), "ERR E05 interval out of range");
    EXPECT_EQ(session_->subscriptions(), 0U);
    // The second error within a second is not logged (VSTATD-IF §6.2).
    EXPECT_EQ(sink_.count("REQUEST_ERROR"), 1U);
}

TEST_F(SessionTest, EveryPathCanBeSubscribed) {
    for (std::size_t i = 0; i < kSignalCount; ++i) {
        request(std::string("SUB ") + kSignals[i].path, 2);
    }
    EXPECT_EQ(session_->subscriptions(), kSignalCount);
    // Every path is subscribed; re-subscribing keeps the count and is not an error.
    EXPECT_EQ(request("SUB Vehicle.Speed 1000", 2).at(0), "OK");
}

TEST_F(SessionTest, LineTooLongIsE03) {
    const std::string longline = "GET " + std::string(300, 'x') + "\nLIST\n";
    vstatd_test::send_text(app_, longline);
    ASSERT_TRUE(vstatd_test::wait_for([&]() { return session_->on_readable(ctx()) && session_->queued() > 0; }, 500ms));
    EXPECT_TRUE(session_->flush());
    std::size_t seen = 0;
    const auto lines =
        vstatd_test::read_until(app_, buffer_, [&seen](const std::string&) { return ++seen == kSignalCount + 2; }, 500ms);
    ASSERT_GE(lines.size(), 2U);
    EXPECT_EQ(lines[0], "ERR E03 line too long");
    EXPECT_EQ(lines[1], std::string("PATH ") + kSignals[0].path);
}

TEST_F(SessionTest, FullQueueDropsOldestLine) {
    for (int i = 0; i < 300; ++i) {
        const std::string line = "L" + std::to_string(i) + "\n";
        session_->enqueue(line.data(), line.size());
    }
    EXPECT_EQ(session_->queued(), kQueueLines);
    EXPECT_TRUE(sink_.contains(R"("ev":"CLIENT_QUEUE_OVERFLOW","client":"1","dropped":"1")"));
    EXPECT_TRUE(session_->flush());
    std::string buffer;
    const auto lines = vstatd_test::read_until(app_, buffer, [](const std::string& l) { return l == "L299"; }, 500ms);
    ASSERT_FALSE(lines.empty());
    EXPECT_EQ(lines.front(), "L44");
}

TEST_F(SessionTest, SubscriptionUpdatesAreHeldBackByInterval) {
    request("SUB Vehicle.Speed 100", 2);
    // Two changes within the interval: only the latest is sent, at the end of the interval.
    for (int v = 1; v <= 2; ++v) {
        published_[2].value.status = Status::kAvailable;
        published_[2].value.text = {{'1', static_cast<char>('0' + v), '\0'}};
        ++published_[2].seq;
        session_->deliver(ctx());
    }
    EXPECT_EQ(session_->queued(), 0U);
    std::this_thread::sleep_for(110ms);
    session_->deliver(ctx());
    EXPECT_EQ(session_->queued(), 1U);
    EXPECT_TRUE(session_->flush());
    const auto lines = vstatd_test::read_until(app_, buffer_, [](const std::string&) { return true; }, 500ms);
    ASSERT_EQ(lines.size(), 1U);
    EXPECT_EQ(lines[0].rfind("VAL Vehicle.Speed 12 AVAILABLE", 0), 0U);
}

TEST(ParseInterval, Values) {
    EXPECT_EQ(parse_interval("100").value(), 100U);
    EXPECT_EQ(parse_interval("10000").value(), 10000U);
    EXPECT_FALSE(parse_interval("").has_value());
}
