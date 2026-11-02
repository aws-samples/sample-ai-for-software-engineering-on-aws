// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Seed check for F-011: looks up a path that vstatd does not publish (the E02 case of VSTATD-IF §6.1). Built with
// -fsanitize=address,undefined against the reference project's vstatd_core.
#include <cstdio>
#include <memory>

#include "signal_table.h"

int main() {
    const auto table = std::make_unique<vstatd::SignalTable>();
    const std::size_t index = table->find("Vehicle.Cabin.Door.Row2.DriverSide.IsOpen");
    std::printf("find returned %zu (kNotFound is %zu)\n", index, vstatd::kNotFound);
    return index == vstatd::kNotFound ? 0 : 1;
}
