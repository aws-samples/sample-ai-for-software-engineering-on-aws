// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Test double for libsystemd's <systemd/sd-daemon.h> (CC1-PN §7.3). Host builds only; the cross build uses the
// header of the CC-1 sysroot. Records the last notification so that tests can check it.
#pragma once

#include <string>

namespace vstatd_test {
inline std::string& last_notification() {
    static std::string text;
    return text;
}
}  // namespace vstatd_test

inline int sd_notify(int /*unset_environment*/, const char* state) {
    vstatd_test::last_notification() = state != nullptr ? state : "";
    return 1;
}
