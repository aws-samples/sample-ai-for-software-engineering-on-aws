// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Hand-written from cc1-gateway.dbc and VSTATD-IF rev 1.3 §3.1/§3.2. Keep in the order of the signal table.
#include "signal_defs.h"

#include <algorithm>

namespace vstatd {

namespace {

constexpr Encoding U = Encoding::kUnsigned;
constexpr Encoding S = Encoding::kSigned;
constexpr Encoding B = Encoding::kFlag;

}  // namespace

// clang-format off
const std::array<SignalDef, kSignalCount> kSignals = {{
    // path                                                          msg  start len  encoding  dec  int factor  factor  offset  min  max  SNA  deadband
    {"Vehicle.LowVoltageSystemState",                                 0,  0,  3, Encoding::kLvState, 0, 1, 1.0, 0.0, 0.0, 5.0, 7, 1},  // 0x100 LvSystemState
    {"Vehicle.LowVoltageBattery.CurrentVoltage",                      0,  8, 10, U, 2, 0, 0.02, 0.0, 6.0, 18.0, 1023, 5},  // 0x100 LvBatteryVoltage
    {"Vehicle.Speed",                                                 1,  0, 16, U, 2, 0, 0.01, 0.0, 0.0, 300.0, 65535, 50},  // 0x101 VehicleSpeed
    {"Vehicle.Powertrain.Transmission.CurrentGear",                   2,  0,  8, S, 0, 1, 1.0, 0.0, -1.0, 8.0, -128, 1},  // 0x102 CurrentGear
    {"Vehicle.Powertrain.Transmission.SelectedGear",                  2,  8,  8, Encoding::kSelectedGear, 0, 1, 1.0, 0.0, -1.0, 127.0, -128, 1},  // 0x102 SelectedGear
    {"Vehicle.Chassis.ParkingBrake.IsEngaged",                        2, 16,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x102 ParkingBrakeEngaged
    {"Vehicle.TraveledDistance",                                      3,  0, 24, U, 0, 100, 100.0, 0.0, 0.0, 1677721400.0, 16777215, 1},  // 0x103 TraveledDistance
    {"Vehicle.Powertrain.TractionBattery.StateOfCharge.Displayed",    4,  0,  8, U, 1, 0, 0.5, 0.0, 0.0, 100.0, 255, 1},  // 0x200 SocDisplayed
    {"Vehicle.Powertrain.Range",                                      4,  8, 16, U, 0, 10, 10.0, 0.0, 0.0, 655340.0, 65535, 100},  // 0x200 RemainingRange
    {"Vehicle.Powertrain.TractionBattery.Charging.IsCharging",        4, 24,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x200 IsCharging
    {"Vehicle.Body.Lights.Beam.Low.IsOn",                             5,  0,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x300 LowBeamOn
    {"Vehicle.Body.Lights.Beam.High.IsOn",                            5,  2,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x300 HighBeamOn
    {"Vehicle.Body.Lights.DirectionIndicator.Left.IsSignaling",       5,  4,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x300 IndicatorLeft
    {"Vehicle.Body.Lights.DirectionIndicator.Right.IsSignaling",      5,  6,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x300 IndicatorRight
    {"Vehicle.Body.Lights.Hazard.IsSignaling",                        5,  8,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x300 HazardOn
    {"Vehicle.Cabin.Door.Row1.DriverSide.IsOpen",                     6,  0,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x301 DriverDoorOpen
    {"Vehicle.Cabin.Door.Row1.PassengerSide.IsOpen",                  6,  2,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x301 PassengerDoorOpen
    {"Vehicle.Body.Trunk.Rear.IsOpen",                                6,  4,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x301 TrunkOpen
    {"Vehicle.Cabin.Seat.Row1.DriverSide.IsBelted",                   6,  6,  2, B, 0, 1, 1.0, 0.0, 0.0, 1.0, 3, 1},  // 0x301 DriverBelted
    {"Vehicle.Chassis.Axle.Row1.Wheel.Left.Tire.Pressure",            7,  0,  8, U, 0, 2, 2.0, 0.0, 0.0, 500.0, 255, 2},  // 0x400 TirePressureFL
    {"Vehicle.Chassis.Axle.Row1.Wheel.Right.Tire.Pressure",           7,  8,  8, U, 0, 2, 2.0, 0.0, 0.0, 500.0, 255, 2},  // 0x400 TirePressureFR
    {"Vehicle.Chassis.Axle.Row2.Wheel.Left.Tire.Pressure",            7, 16,  8, U, 0, 2, 2.0, 0.0, 0.0, 500.0, 255, 2},  // 0x400 TirePressureRL
    {"Vehicle.Chassis.Axle.Row2.Wheel.Right.Tire.Pressure",           7, 24,  8, U, 0, 2, 2.0, 0.0, 0.0, 500.0, 255, 2},  // 0x400 TirePressureRR
    {"Vehicle.Exterior.AirTemperature",                               8,  0,  8, U, 1, 0, 0.5, -40.0, -40.0, 85.0, 255, 1},  // 0x401 ExteriorAirTemp
}};

const std::array<MessageDef, kMessageCount> kMessages = {{
    // name             CAN ID  timeout (3 x cycle)  first signal  signals
    {"VCU_PowerState",  0x100,  300,  0, 2},  // cycle 100 ms
    {"VCU_Speed",       0x101,   60,  2, 1},  // cycle 20 ms
    {"VCU_Gear",        0x102,  150,  3, 3},  // cycle 50 ms
    {"VCU_Odometer",    0x103, 3000,  6, 1},  // cycle 1000 ms
    {"BMS_Status",      0x200,  300,  7, 3},  // cycle 100 ms
    {"BCM_Lights",      0x300,  300, 10, 5},  // cycle 100 ms
    {"BCM_Closures",    0x301,  300, 15, 4},  // cycle 100 ms
    {"TPMS_Pressures",  0x400, 3000, 19, 4},  // cycle 1000 ms
    {"BCM_Exterior",    0x401, 3000, 23, 1},  // cycle 1000 ms
}};
// clang-format on

std::size_t message_index(std::uint32_t can_id) {
    const auto it = std::find_if(kMessages.begin(), kMessages.end(),
                                 [can_id](const MessageDef& m) { return m.can_id == can_id; });
    return static_cast<std::size_t>(it - kMessages.begin());
}

}  // namespace vstatd
