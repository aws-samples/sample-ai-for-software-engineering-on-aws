// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// The gateway side decodes while the IPC side answers GET (VSTATD-IF §8.4).
#include <gtest/gtest.h>

#include <atomic>
#include <memory>
#include <string>
#include <thread>

#include <sys/socket.h>
#include <unistd.h>

#include "client_session.h"
#include "frame_decoder.h"
#include "test_util.h"

using namespace vstatd;

TEST(Concurrency, DecodingAndGetAtTheSameTime) {
    vstatd_test::MemorySink sink;
    LogWriter log(sink);
    const auto table = std::make_unique<SignalTable>();
    std::atomic<bool> done{false};

    std::thread decoding([&table, &done]() {
        FrameDecoder decoder;
        Record record;
        for (int i = 0; i < 2000; ++i) {
            const std::string line = "F " + std::to_string(i) + " 101 8 " + (i % 2 == 0 ? "C409" : "1027") + "000000000000";
            ASSERT_TRUE(decoder.accept(line.data(), line.size(), record));
            Reading r;
            r.t_ms = i;
            r.raw = decoder.raw_value(record, kSignals[2]);
            r.verdict = Verdict::kValue;
            r.text = i % 2 == 0 ? "25.00" : "100.00";
            table->update(kSignals[2].path, r);
        }
        done.store(true);
    });

    int fds[2] = {-1, -1};
    ASSERT_EQ(::socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
    ClientSession session(Peer{fds[0], 1, &log});
    const PublishedTable published{};
    std::size_t answers = 0;
    std::string buffer;
    while (!done.load() || answers < 10) {
        session.parse_line("GET Vehicle.Speed", RequestContext{*table, published, SessionClock::now()});
        ASSERT_TRUE(session.flush());
        const auto lines = vstatd_test::read_until(fds[1], buffer, [](const std::string&) { return true; },
                                                   std::chrono::milliseconds(100));
        for (const auto& l : lines) {
            EXPECT_EQ(l.rfind("VAL Vehicle.Speed ", 0), 0U) << l;
            ++answers;
        }
    }
    decoding.join();
    ::close(fds[1]);
    EXPECT_GE(answers, 10U);
}
