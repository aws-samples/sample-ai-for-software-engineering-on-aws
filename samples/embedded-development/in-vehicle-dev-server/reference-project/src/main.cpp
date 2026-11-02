// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// vstatd entry point: start-up and stop (VSTATD-IF §8.1, §8.2, §6.4).
#include <atomic>
#include <csignal>
#include <ctime>
#include <new>
#include <thread>

#include <pthread.h>
#include <systemd/sd-daemon.h>

#include "config.h"
#include "log_writer.h"
#include "service.h"

namespace {

// Waits for SIGTERM or SIGINT, or until the service has ended on its own.
bool wait_for_signal(const sigset_t& set, const std::atomic<bool>& ended) {
    const timespec tick{0, 100L * 1000L * 1000L};
    while (!ended.load()) {
        const int sig = ::sigtimedwait(&set, nullptr, &tick);
        if (sig == SIGTERM || sig == SIGINT) {
            return true;
        }
    }
    return false;
}

}  // namespace

int main() {
    // Signals are taken by sigtimedwait() below, so they are blocked before any thread starts.
    sigset_t set{};
    sigemptyset(&set);
    sigaddset(&set, SIGTERM);
    sigaddset(&set, SIGINT);
    pthread_sigmask(SIG_BLOCK, &set, nullptr);

    vstatd::JournalSink sink;
    vstatd::LogWriter log(sink);
    try {
        const vstatd::Config config;
        log.event("SERVICE_START", {vstatd::Field{"version", vstatd::kVersion}});
        vstatd::Service service(config, log);
        if (!service.start_ipc()) {
            log.event("SERVICE_STOP", {vstatd::Field{"reason", "ipc_socket"}});
            return 1;
        }
        sd_notify(0, "READY=1");
        log.event("SERVICE_READY", {});

        std::atomic<bool> ended{false};
        std::thread gateway([&service, &ended]() {
            service.run();
            ended.store(true);
        });
        wait_for_signal(set, ended);
        service.stop();
        gateway.join();
        service.shutdown();
        log.event("SERVICE_STOP", {vstatd::Field{"reason", "signal"}});
        return 0;
    } catch (const std::bad_alloc&) {
        log.event("SERVICE_STOP", {vstatd::Field{"reason", "out_of_memory"}});
        return 1;
    }
}
