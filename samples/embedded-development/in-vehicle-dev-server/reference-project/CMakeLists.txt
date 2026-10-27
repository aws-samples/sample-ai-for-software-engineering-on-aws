# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
cmake_minimum_required(VERSION 3.16)
project(vstatd VERSION 2.7.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()
# The team's flags (TR §2.1) are set below; keep CMake's per-configuration flags out of the way.
set(CMAKE_CXX_FLAGS_RELEASE "")

# Team rules TR §2.1.
set(VSTATD_FLAGS -Wall -Wextra -Werror -O2 -fstack-protector-strong -D_FORTIFY_SOURCE=2)

# Host builds only (TR §2.2): "thread" or "address,undefined".
set(VSTATD_SANITIZE "" CACHE STRING "Sanitizers for the host build: thread or address,undefined")

find_package(Threads REQUIRED)

add_library(vstatd_core STATIC
  src/client_session.cpp
  src/config.cpp
  src/frame_decoder.cpp
  src/gateway_client.cpp
  src/ipc_server.cpp
  src/log_writer.cpp
  src/service.cpp
  src/signal_defs.cpp
  src/signal_table.cpp
  src/supervisor.cpp
)
target_include_directories(vstatd_core PUBLIC src)
target_compile_options(vstatd_core PRIVATE ${VSTATD_FLAGS})
target_link_libraries(vstatd_core PUBLIC Threads::Threads)

add_executable(vstatd src/main.cpp)
target_compile_options(vstatd PRIVATE ${VSTATD_FLAGS})
target_link_libraries(vstatd PRIVATE vstatd_core)

if(CMAKE_CROSSCOMPILING)
  # libsystemd from the CC-1 sysroot (CC1-PN §7.2).
  target_link_libraries(vstatd PRIVATE systemd)
else()
  # Build server: the test double of CC1-PN §7.3 stands in for libsystemd.
  target_include_directories(vstatd PRIVATE tests/stubs)
  if(VSTATD_SANITIZE)
    foreach(t vstatd_core vstatd)
      target_compile_options(${t} PRIVATE -fsanitize=${VSTATD_SANITIZE} -fno-omit-frame-pointer -g)
      target_link_options(${t} PRIVATE -fsanitize=${VSTATD_SANITIZE})
    endforeach()
  endif()
  enable_testing()
  add_subdirectory(tests)
endif()
