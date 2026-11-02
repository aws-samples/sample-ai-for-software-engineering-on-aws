// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// The whole service on the build server: a fake gateway feeds records, an app talks to the IPC socket, and the
// runtime log is checked for the entries of VSTATD-IF §7.
#include <gtest/gtest.h>

#include <atomic>
#include <cstdio>
#include <memory>
#include <mutex>
#include <regex>
#include <string>
#include <thread>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include "config.h"
#include "service.h"
#include "test_util.h"

using namespace vstatd;
using namespace std::chrono_literals;

namespace {

// Plays cc1-gwd: listens on the gateway socket, sends a heartbeat every 100 ms (VSTATD-IF §2.4) and whatever the
// test gives it.
class FakeGateway {
public:
    explicit FakeGateway(const std::string& path) {
        listen_fd_ = ::socket(AF_UNIX, SOCK_STREAM, 0);
        const sockaddr_un addr = vstatd_test::unix_addr(path);
        EXPECT_EQ(::bind(listen_fd_, reinterpret_cast<const sockaddr*>(&addr), sizeof(addr)), 0);
        EXPECT_EQ(::listen(listen_fd_, 4), 0);
        heartbeat_ = std::thread([this]() {
            while (!stop_.load()) {
                send("H 0\n");
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            }
        });
    }
    ~FakeGateway() {
        stop_.store(true);
        heartbeat_.join();
        drop();
        ::close(listen_fd_);
    }
    bool accept_one() {
        const int fd = ::accept(listen_fd_, nullptr, nullptr);
        const std::lock_guard<std::mutex> lock(mutex_);
        conn_ = fd;
        return conn_ >= 0;
    }
    void send(const std::string& text) {
        const std::lock_guard<std::mutex> lock(mutex_);
        if (conn_ >= 0) {
            vstatd_test::send_text(conn_, text);
        }
    }
    void drop() {
        const std::lock_guard<std::mutex> lock(mutex_);
        if (conn_ >= 0) {
            ::close(conn_);
            conn_ = -1;
        }
    }

private:
    int listen_fd_ = -1;
    int conn_ = -1;
    std::mutex mutex_;
    std::atomic<bool> stop_{false};
    std::thread heartbeat_;
};

std::string speed_frame(int raw) {
    char data[17];
    std::snprintf(data, sizeof(data), "%02X%02X000000000000", raw & 0xFF, (raw >> 8) & 0xFF);
    return std::string("F 1 101 8 ") + data + "\n";
}

}  // namespace

TEST(Service, RecordsToLogAndApps) {
    vstatd_test::TempDir dir;
    Config config;
    config.set_gateway_socket(dir.file("can.sock"));
    config.set_ipc_socket(dir.file("vstatd.sock"));
    FakeGateway gw(config.gateway_socket());
    vstatd_test::MemorySink sink;
    LogWriter log(sink);
    auto service = std::make_unique<Service>(config, log);
    ASSERT_TRUE(service->start_ipc());
    std::thread runner([&service]() { service->run(); });

    // Connection, then a few frames: values are decoded and logged.
    ASSERT_TRUE(gw.accept_one());
    ASSERT_TRUE(vstatd_test::wait_for([&]() { return sink.contains(R"("ev":"GATEWAY_CONNECTED")"); }, 1000ms));
    gw.send("F 1 100 8 04A2020000000000\n");
    gw.send(speed_frame(2500));
    gw.send("F 1 300 8 E101000000000000\n");
    gw.send("F 1 555 8 0000000000000000\nbad record\nF 1 101 2 C409\nH 2\n");
    // The short frame is the last record logged: wait for it, then everything before it is in the log.
    ASSERT_TRUE(vstatd_test::wait_for(
        [&]() { return sink.contains(R"("ev":"GATEWAY_RECORD_INVALID","reason":"short_dlc","suppressed":"0")"); },
        1000ms));
    EXPECT_TRUE(sink.contains(R"("path":"Vehicle.Speed","value":"25.00","status":"AVAILABLE")"));
    EXPECT_TRUE(sink.contains(R"("path":"Vehicle.LowVoltageSystemState","value":"ON","status":"AVAILABLE")"));
    EXPECT_TRUE(sink.contains(R"("path":"Vehicle.LowVoltageBattery.CurrentVoltage","value":"13.48","status":"AVAILABLE")"));
    EXPECT_TRUE(sink.contains(R"("path":"Vehicle.Body.Lights.Beam.Low.IsOn","value":"true","status":"AVAILABLE")"));
    EXPECT_TRUE(sink.contains(R"("path":"Vehicle.Body.Lights.DirectionIndicator.Left.IsSignaling","value":"-","status":"INVALID")"));
    EXPECT_TRUE(sink.contains(R"("ev":"GATEWAY_RECORD_INVALID","reason":"format","suppressed":"0")"));

    // An app: LIST, GET, SUB, and errors.
    const int app = vstatd_test::connect_unix(config.ipc_socket());
    ASSERT_GE(app, 0);
    std::string buffer;
    vstatd_test::send_text(app, "GET Vehicle.Speed\nSUB Vehicle.Speed 50\nFOO\nSUB Vehicle.Speed 20\nLIST\n");
    const auto lines = vstatd_test::read_until(app, buffer, [](const std::string& l) { return l == "OK" ; }, 1000ms);
    ASSERT_GE(lines.size(), 1U);
    EXPECT_EQ(lines[0].rfind("VAL Vehicle.Speed 25.00 AVAILABLE ", 0), 0U) << lines[0];
    const auto more = vstatd_test::read_until(app, buffer, [](const std::string& l) { return l == "OK"; }, 1000ms);
    bool e01 = false;
    bool e05 = false;
    for (const auto& l : more) {
        e01 = e01 || l == "ERR E01 unknown request";
        e05 = e05 || l == "ERR E05 interval out of range";
    }
    EXPECT_TRUE(e01);
    EXPECT_TRUE(e05);
    EXPECT_TRUE(sink.contains(R"("ev":"CLIENT_CONNECTED","client":"1")"));

    // An out-of-range speed is INVALID and logged as SIGNAL_INVALID.
    gw.send(speed_frame(30001));
    ASSERT_TRUE(vstatd_test::wait_for([&]() { return sink.contains(R"("ev":"SIGNAL_INVALID","path":"Vehicle.Speed","raw":"30001")"); }, 1000ms));

    // VCU_Speed stops for longer than its 60 ms timeout, then comes back.
    gw.send(speed_frame(2600));
    std::this_thread::sleep_for(150ms);
    gw.send("H 3\n");
    ASSERT_TRUE(vstatd_test::wait_for([&]() { return sink.contains(R"("ev":"SIGNAL_TIMEOUT","message":"VCU_Speed")"); }, 1000ms));
    gw.send(speed_frame(2700));
    // SIGNAL_RECOVERED comes before the values of the same step (§7.3): wait for the value.
    ASSERT_TRUE(vstatd_test::wait_for(
        [&]() { return sink.contains(R"("path":"Vehicle.Speed","value":"27.00","status":"AVAILABLE")"); }, 1000ms));
    EXPECT_TRUE(sink.contains(R"("ev":"SIGNAL_RECOVERED","message":"VCU_Speed")"));

    // The subscriber saw the timeout at once.
    const auto updates = vstatd_test::read_until(
        app, buffer, [](const std::string& l) { return l.rfind("VAL Vehicle.Speed - UNAVAILABLE", 0) == 0; }, 1000ms);
    ASSERT_FALSE(updates.empty());

    // The gateway closes the socket: GATEWAY_LOST, every signal UNAVAILABLE, then a new connection.
    gw.drop();
    ASSERT_TRUE(vstatd_test::wait_for([&]() { return sink.contains(R"("ev":"GATEWAY_LOST","reason":"closed")"); }, 1000ms));
    ASSERT_TRUE(gw.accept_one());
    ASSERT_TRUE(vstatd_test::wait_for([&]() { return sink.count(R"("ev":"GATEWAY_CONNECTED")") == 2; }, 2000ms));

    ::close(app);
    ASSERT_TRUE(vstatd_test::wait_for([&]() { return sink.contains(R"("ev":"CLIENT_DISCONNECTED","client":"1")"); }, 1000ms));
    service->stop();
    runner.join();
    service->shutdown();

    // Every line is one JSON object in the format of CC1-PN §5.2.
    const std::regex format(R"(\{"t_ms":\d+,"ev":"[A-Z_]+"(,"[a-z_]+":"[^"]*")*\})");
    for (const auto& l : sink.lines()) {
        EXPECT_TRUE(std::regex_match(l, format)) << l;
    }
    // GATEWAY_LOST comes before the SIGNAL_VALUE entries it causes.
    const auto all = sink.lines();
    std::size_t lost = 0;
    for (std::size_t i = 0; i < all.size(); ++i) {
        if (all[i].find(R"("ev":"GATEWAY_LOST")") != std::string::npos) {
            lost = i;
        }
    }
    ASSERT_GT(lost, 0U);
    EXPECT_NE(all[lost + 1].find(R"("ev":"SIGNAL_VALUE")"), std::string::npos);
    EXPECT_NE(all[lost + 1].find(R"("status":"UNAVAILABLE")"), std::string::npos);
}

TEST(Service, SeventeenthClientIsRejected) {
    vstatd_test::TempDir dir;
    Config config;
    config.set_gateway_socket(dir.file("missing.sock"));
    config.set_ipc_socket(dir.file("vstatd.sock"));
    vstatd_test::MemorySink sink;
    LogWriter log(sink);
    auto service = std::make_unique<Service>(config, log);
    ASSERT_TRUE(service->start_ipc());
    std::vector<int> apps;
    for (int i = 0; i < 16; ++i) {
        apps.push_back(vstatd_test::connect_unix(config.ipc_socket()));
        ASSERT_GE(apps.back(), 0);
    }
    ASSERT_TRUE(vstatd_test::wait_for([&]() { return service->ipc().clients() == 16; }, 1000ms));
    const int extra = vstatd_test::connect_unix(config.ipc_socket());
    ASSERT_GE(extra, 0);
    std::string buffer;
    const auto lines = vstatd_test::read_until(extra, buffer, [](const std::string&) { return true; }, 1000ms);
    ASSERT_EQ(lines.size(), 1U);
    EXPECT_EQ(lines[0], "ERR E06 too many clients");
    // The IPC thread logs CLIENT_REJECTED, then REQUEST_ERROR, after it has sent the error line: wait for the last.
    ASSERT_TRUE(vstatd_test::wait_for(
        [&]() { return sink.contains(R"("ev":"REQUEST_ERROR","client":"17","code":"E06","suppressed":"0")"); }, 1000ms));
    EXPECT_TRUE(sink.contains(R"("ev":"CLIENT_REJECTED","client":"17")"));
    ::close(extra);
    for (const int fd : apps) {
        ::close(fd);
    }
    service->shutdown();
}

TEST(Service, IpcSocketThatCannotBeCreated) {
    Config config;
    config.set_ipc_socket("/nonexistent-dir/vstatd.sock");
    vstatd_test::MemorySink sink;
    LogWriter log(sink);
    Service service(config, log);
    EXPECT_FALSE(service.start_ipc());
}
