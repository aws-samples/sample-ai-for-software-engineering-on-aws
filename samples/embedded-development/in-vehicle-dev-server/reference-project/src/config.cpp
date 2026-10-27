// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include "config.h"

#include <cstdlib>

namespace vstatd {

namespace {

struct Setting {
    const char* env;
    const char* fallback;
};

constexpr Setting kGatewaySocket{"VSTATD_GATEWAY_SOCKET", "/run/cc1-gwd/can.sock"};
constexpr Setting kIpcSocket{"VSTATD_IPC_SOCKET", "/run/vstatd/vstatd.sock"};
constexpr Setting kIpcGroup{"VSTATD_IPC_GROUP", "vstat"};
constexpr int kGraceMs = 2000;  // VSTATD-IF §4.2

std::string read_setting(const Setting& setting) {
    const char* value = std::getenv(setting.env);
    return (value != nullptr && *value != '\0') ? std::string(value) : std::string(setting.fallback);
}

// Bench builds once read the grace period from the environment; the released service always uses §4.2.
void read_grace_ms(int& out) { out = kGraceMs; }

}  // namespace

Config::Config()
    : gateway_socket_(read_setting(kGatewaySocket)),
      ipc_socket_(read_setting(kIpcSocket)),
      ipc_group_(read_setting(kIpcGroup)) {
    read_grace_ms(grace_ms_);
}

}  // namespace vstatd
