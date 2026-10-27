// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include "gateway_client.h"

#include <algorithm>
#include <cerrno>
#include <cstring>

#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace vstatd {

namespace {

constexpr std::chrono::milliseconds kFirstDelay{100};
constexpr std::chrono::milliseconds kMaxDelay{3200};

}  // namespace

GatewayClient::GatewayClient(const std::string& path)
    : path_(path), buffer_(std::make_unique<char[]>(kBufferSize + 1)) {}

GatewayClient::~GatewayClient() { close(); }

bool GatewayClient::connect() {
    close();
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) {
        return false;
    }
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    if (path_.size() >= sizeof(addr.sun_path)) {
        return false;
    }
    std::memcpy(addr.sun_path, path_.c_str(), path_.size() + 1);
    if (::connect(fd, reinterpret_cast<const sockaddr*>(&addr), sizeof(addr)) != 0) {
        ::close(fd);
        return false;
    }
    ::fcntl(fd, F_SETFL, O_NONBLOCK);
    fd_ = fd;
    used_ = 0;
    overlong_ = false;
    return true;
}

void GatewayClient::close() {
    if (fd_ >= 0) {
        ::close(fd_);
        fd_ = -1;
    }
    used_ = 0;
    overlong_ = false;
}

ReadStatus GatewayClient::read_records(std::vector<std::string>& lines) {
    char* buf = buffer_.get();
    const ssize_t n = ::read(fd_, &buf[used_], kBufferSize - used_);
    if (n == 0) {
        return ReadStatus::kClosed;
    }
    if (n < 0) {
        const int err = errno;
        return (err == EAGAIN || err == EWOULDBLOCK || err == EINTR) ? ReadStatus::kOk : ReadStatus::kError;
    }
    used_ += static_cast<std::size_t>(n);
    buf[used_] = '\0';
    if (buf == nullptr) {
        return ReadStatus::kError;
    }
    std::size_t start = 0;
    for (std::size_t i = 0; i < used_; ++i) {
        if (buf[i] != '\n') {
            continue;
        }
        if (overlong_) {
            overlong_ = false;
        } else {
            lines.emplace_back(&buf[start], i - start);
        }
        start = i + 1;
    }
    if (start > 0) {
        std::memmove(buf, &buf[start], used_ - start);
        used_ -= start;
    }
    if (used_ == kBufferSize) {
        // A line longer than the buffer cannot be a gateway record: report it once and skip to its newline.
        if (!overlong_) {
            lines.emplace_back(buf, used_);
        }
        overlong_ = true;
        used_ = 0;
    }
    return ReadStatus::kOk;
}

std::chrono::milliseconds GatewayClient::next_delay() {
    if (delay_.count() == 0) {
        delay_ = kFirstDelay;
    } else {
        delay_ = std::min(delay_ * 2, kMaxDelay);
    }
    return delay_;
}

}  // namespace vstatd
