// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#include <gtest/gtest.h>

#include <cstdlib>

#include "config.h"

using vstatd::Config;

TEST(Config, DefaultsFromTheSpecification) {
    ::unsetenv("VSTATD_GATEWAY_SOCKET");
    ::unsetenv("VSTATD_IPC_SOCKET");
    const Config c;
    EXPECT_EQ(c.gateway_socket(), "/run/cc1-gwd/can.sock");
    EXPECT_EQ(c.ipc_socket(), "/run/vstatd/vstatd.sock");
    EXPECT_EQ(c.ipc_group(), "vstat");
}

TEST(Config, EnvironmentOverridesSockets) {
    ::setenv("VSTATD_GATEWAY_SOCKET", "/tmp/gw.sock", 1);
    ::setenv("VSTATD_IPC_SOCKET", "/tmp/ipc.sock", 1);
    const Config c;
    EXPECT_EQ(c.gateway_socket(), "/tmp/gw.sock");
    EXPECT_EQ(c.ipc_socket(), "/tmp/ipc.sock");
    ::unsetenv("VSTATD_GATEWAY_SOCKET");
    ::unsetenv("VSTATD_IPC_SOCKET");
}
