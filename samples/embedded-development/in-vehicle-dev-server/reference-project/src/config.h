// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Start-up settings. The defaults are those of VSTATD-IF and CC1-PN; environment variables override them:
//   VSTATD_GATEWAY_SOCKET  gateway socket, default /run/cc1-gwd/can.sock (VSTATD-IF §2.1)
//   VSTATD_IPC_SOCKET      IPC socket, default /run/vstatd/vstatd.sock (VSTATD-IF §5.1)
//   VSTATD_IPC_GROUP       group of the IPC socket, default vstat
#pragma once

#include <chrono>
#include <string>

namespace vstatd {

class Config {
public:
    Config();

    const std::string& gateway_socket() const { return gateway_socket_; }
    const std::string& ipc_socket() const { return ipc_socket_; }
    const std::string& ipc_group() const { return ipc_group_; }
    std::chrono::milliseconds grace() const { return std::chrono::milliseconds(grace_ms_); }

    void set_gateway_socket(const std::string& path) { gateway_socket_ = path; }
    void set_ipc_socket(const std::string& path) { ipc_socket_ = path; }

private:
    std::string gateway_socket_;
    std::string ipc_socket_;
    std::string ipc_group_;
    int grace_ms_;
};

}  // namespace vstatd
