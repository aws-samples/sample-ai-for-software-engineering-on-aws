# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Unit tests for the build server (CC1-PN §7.3). Not cross-compiled.
find_package(GTest REQUIRED)

add_executable(vstatd_tests
  test_client_session.cpp
  test_concurrency.cpp
  test_config.cpp
  test_frame_decoder.cpp
  test_log_writer.cpp
  test_service.cpp
  test_signal_table.cpp
  test_supervisor.cpp
)
target_include_directories(vstatd_tests PRIVATE stubs .)
target_compile_options(vstatd_tests PRIVATE -Wall -Wextra -Werror)
target_link_libraries(vstatd_tests PRIVATE vstatd_core GTest::gtest_main Threads::Threads)
if(VSTATD_SANITIZE)
  target_compile_options(vstatd_tests PRIVATE -fsanitize=${VSTATD_SANITIZE} -fno-omit-frame-pointer -g)
  target_link_options(vstatd_tests PRIVATE -fsanitize=${VSTATD_SANITIZE})
endif()

include(GoogleTest)
gtest_discover_tests(vstatd_tests DISCOVERY_MODE PRE_TEST DISCOVERY_TIMEOUT 60)
