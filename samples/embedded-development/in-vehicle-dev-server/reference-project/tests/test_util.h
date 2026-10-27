// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Helpers shared by the tests: a log sink that keeps lines, temporary directories and small socket clients.
#pragma once

#include <chrono>
#include <cstdlib>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include "log_writer.h"

namespace vstatd_test {

class MemorySink : public vstatd::LogSink {
public:
    void write(const std::string& line) override {
        const std::lock_guard<std::mutex> lock(mutex_);
        lines_.push_back(line);
    }
    std::vector<std::string> lines() const {
        const std::lock_guard<std::mutex> lock(mutex_);
        return lines_;
    }
    bool contains(const std::string& part) const {
        const std::lock_guard<std::mutex> lock(mutex_);
        for (const auto& l : lines_) {
            if (l.find(part) != std::string::npos) {
                return true;
            }
        }
        return false;
    }
    std::size_t count(const std::string& part) const {
        const std::lock_guard<std::mutex> lock(mutex_);
        std::size_t n = 0;
        for (const auto& l : lines_) {
            if (l.find(part) != std::string::npos) {
                ++n;
            }
        }
        return n;
    }

private:
    mutable std::mutex mutex_;
    std::vector<std::string> lines_;
};

class TempDir {
public:
    TempDir() {
        char tmpl[] = "/tmp/vstatd-test-XXXXXX";
        const char* p = ::mkdtemp(tmpl);
        path_ = p != nullptr ? p : "/tmp";
    }
    ~TempDir() {
        const std::string cmd = "rm -rf '" + path_ + "'";
        (void)std::system(cmd.c_str());
    }
    std::string file(const std::string& name) const { return path_ + "/" + name; }

private:
    std::string path_;
};

inline sockaddr_un unix_addr(const std::string& path) {
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    path.copy(addr.sun_path, sizeof(addr.sun_path) - 1);
    return addr;
}

inline int connect_unix(const std::string& path) {
    const int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    const sockaddr_un addr = unix_addr(path);
    if (::connect(fd, reinterpret_cast<const sockaddr*>(&addr), sizeof(addr)) != 0) {
        ::close(fd);
        return -1;
    }
    return fd;
}

inline void send_text(int fd, const std::string& text) {
    std::size_t off = 0;
    while (off < text.size()) {
        const ssize_t n = ::send(fd, text.data() + off, text.size() - off, MSG_NOSIGNAL);
        if (n <= 0) {
            return;
        }
        off += static_cast<std::size_t>(n);
    }
}

// Reads lines until the predicate accepts one of them or the timeout passes.
template <typename Pred>
std::vector<std::string> read_until(int fd, std::string& buffer, Pred done, std::chrono::milliseconds timeout) {
    std::vector<std::string> lines;
    const auto end = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < end) {
        std::size_t nl = buffer.find('\n');
        while (nl != std::string::npos) {
            lines.push_back(buffer.substr(0, nl));
            buffer.erase(0, nl + 1);
            if (done(lines.back())) {
                return lines;
            }
            nl = buffer.find('\n');
        }
        char chunk[1024];
        const ssize_t n = ::recv(fd, chunk, sizeof(chunk), MSG_DONTWAIT);
        if (n > 0) {
            buffer.append(chunk, static_cast<std::size_t>(n));
        } else {
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
    }
    return lines;
}

template <typename Pred>
bool wait_for(Pred pred, std::chrono::milliseconds timeout) {
    const auto end = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < end) {
        if (pred()) {
            return true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    return pred();
}

}  // namespace vstatd_test
