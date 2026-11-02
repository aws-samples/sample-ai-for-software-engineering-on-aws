// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Client of the CAN gateway socket (VSTATD-IF §2.1). vstatd only reads from it.
#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace vstatd {

enum class ReadStatus : std::uint8_t { kOk, kClosed, kError };

class GatewayClient {
public:
    explicit GatewayClient(const std::string& path);
    ~GatewayClient();
    GatewayClient(const GatewayClient&) = delete;
    GatewayClient& operator=(const GatewayClient&) = delete;

    bool connect();
    void close();
    bool connected() const { return fd_ >= 0; }
    int socket_fd() const { return fd_; }

    // Reads what the socket has and appends every complete line, without its newline, to lines.
    ReadStatus read_records(std::vector<std::string>& lines);

    // Reconnection delay of VSTATD-IF §4.4: 100 ms after a loss or a failed first attempt, doubled after each
    // failed attempt up to 3200 ms.
    std::chrono::milliseconds next_delay();
    void reset_delay() { delay_ = std::chrono::milliseconds(0); }

private:
    static constexpr std::size_t kBufferSize = 4096;

    std::string path_;
    int fd_ = -1;
    std::size_t used_ = 0;
    bool overlong_ = false;
    std::chrono::milliseconds delay_{0};
    std::unique_ptr<char[]> buffer_;
};

}  // namespace vstatd
