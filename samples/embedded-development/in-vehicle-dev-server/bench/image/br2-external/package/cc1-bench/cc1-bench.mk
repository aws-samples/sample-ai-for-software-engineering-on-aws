# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
CC1_BENCH_VERSION = 1.0
CC1_BENCH_SITE = $(BR2_EXTERNAL_CC1_PATH)/../../player
CC1_BENCH_SITE_METHOD = local
CC1_BENCH_LICENSE = MIT-0

define CC1_BENCH_BUILD_CMDS
	$(TARGET_CXX) $(TARGET_CXXFLAGS) -std=c++17 -Wall -Wextra -Werror -O2 \
		-o $(@D)/cc1-bench $(@D)/cc1-bench.cpp $(TARGET_LDFLAGS)
endef

define CC1_BENCH_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/cc1-bench $(TARGET_DIR)/usr/bin/cc1-bench
	$(INSTALL) -D -m 0755 $(@D)/run-replay.sh $(TARGET_DIR)/usr/libexec/cc1-bench/run-replay
endef

$(eval $(generic-package))
