# Findings backlog for `vstatd`

> Synthetic, written for the AI-DLC embedded sample. The findings come from the analysers and settings of
> `[TR §3]` on the current release. Locations are given by file and function; the reference project contains the
> code they point at, and its analyser run reproduces them with line numbers.

Label `fix` puts a finding in the current batch; each one gets a triage decision under `[TR §4]`. Label `later` keeps
it in the backlog.

| ID | Tool | Check | Location | Message | Label |
| --- | --- | --- | --- | --- | --- |
| F-001 | cppcheck | nullPointerRedundantCheck | `src/gateway_client.cpp` › `GatewayClient::read_records` | Either the condition 'buf==nullptr' is redundant or there is possible null pointer dereference: buf. | fix |
| F-002 | clang-tidy | bugprone-unused-return-value | `src/gateway_client.cpp` › `GatewayClient::connect` | the value returned by this function should not be disregarded; neglecting it may lead to errors (`fcntl`) | fix |
| F-003 | cppcheck | resourceLeak | `src/gateway_client.cpp` › `GatewayClient::connect` | Resource leak: fd | fix |
| F-004 | clang-tidy | bugprone-narrowing-conversions | `src/frame_decoder.cpp` › `parse_record` | narrowing conversion from 'unsigned long' to signed type 'int' is implementation-defined | fix |
| F-005 | cppcheck | uninitMemberVar | `src/frame_decoder.cpp` › `FrameDecoder::FrameDecoder` | Member variable 'FrameDecoder::last_error_' is not initialized in the constructor. | fix |
| F-006 | clang-tidy | bugprone-signed-char-misuse | `src/frame_decoder.cpp` › `hex_nibble` | 'signed char' to 'int' conversion; consider casting to 'unsigned char' first. | fix |
| F-007 | clang-tidy | bugprone-implicit-widening-of-multiplication-result | `src/frame_decoder.cpp` › `scale_unsigned` | performing an implicit widening conversion to type 'std::uint64_t' (aka 'unsigned long') of a multiplication performed in type 'std::uint32_t' (aka 'unsigned int') | fix |
| F-008 | cppcheck | knownConditionTrueFalse | `src/supervisor.cpp` › `Supervisor::check` | Condition 'entry.supervised' is always true | fix |
| F-009 | cppcheck | variableScope | `src/supervisor.cpp` › `Supervisor::check` | The scope of the variable 'now' can be reduced. | later |
| F-010 | clang-tidy | cppcoreguidelines-init-variables | `src/signal_table.cpp` › `SignalTable::update` | variable 'status' is not initialized | fix |
| F-011 | cppcheck | arrayIndexOutOfBoundsCond | `src/signal_table.cpp` › `SignalTable::find` | Either the condition 'i>24' is redundant or the array 'entries_[24]' is accessed at index 24, which is out of bounds. | fix |
| F-012 | clang-tidy | performance-unnecessary-value-param | `src/signal_table.cpp` › `SignalTable::update` | the parameter 'path' is copied for each invocation but only used as a const reference; consider making it a const reference | fix |
| F-013 | cppcheck | passedByValue | `src/ipc_server.cpp` › `IpcServer::broadcast` | Function parameter 'line' should be passed by const reference. | fix |
| F-014 | cppcheck | resourceLeak | `src/ipc_server.cpp` › `IpcServer::open_listener` | Resource leak: listen_fd | fix |
| F-015 | clang-tidy | bugprone-unused-return-value | `src/ipc_server.cpp` › `IpcServer::accept_client` | the value returned by this function should not be disregarded; neglecting it may lead to errors (`fcntl`) | fix |
| F-016 | clang-tidy | bugprone-unchecked-optional-access | `src/client_session.cpp` › `ClientSession::handle_sub` | unchecked access to optional value | fix |
| F-017 | cppcheck | containerOutOfBounds | `src/client_session.cpp` › `ClientSession::parse_line` | Either the condition 'words.size()==1' is redundant or words size can be 1. Expression 'words[1]' cause access out of bounds. | fix |
| F-018 | clang-tidy | cert-err34-c | `src/client_session.cpp` › `parse_interval` | 'atoi' used to convert a string to an integer value, but function will not report conversion errors; consider using 'strtol' instead | fix |
| F-019 | cppcheck | uselessCallsSubstr | `src/client_session.cpp` › `ClientSession::parse_line` | Ineffective call of function 'substr' because it returns a copy of the object. Use operator= instead. | later |
| F-020 | clang-tidy | performance-inefficient-string-concatenation | `src/log_writer.cpp` › `LogWriter::format` | string concatenation results in allocation of unnecessary temporary strings; consider using 'operator+=' or 'string::append()' instead | later |
| F-021 | clang-tidy | cppcoreguidelines-pro-type-member-init | `src/client_session.h` › `ClientSession::ClientSession` | constructor does not initialize these fields: lines_ | fix |
| F-022 | cppcheck | shadowVariable | `src/service.cpp` › `Service::run` | Local variable 'status' shadows outer variable | later |
| F-023 | clang-tidy | bugprone-branch-clone | `src/service.cpp` › `Service::run` | repeated branch body in conditional chain | fix |
| F-024 | cppcheck | duplicateCondition | `src/service.cpp` › `Service::run` | The if condition is the same as the previous if condition | later |
| F-025 | clang-tidy | bugprone-empty-catch | `src/service.cpp` › `Service::run` | empty catch statements hide issues; to handle exceptions appropriately, consider re-throwing, handling, or avoiding catch altogether | fix |
| F-026 | cppcheck | unreadVariable | `src/service.cpp` › `Service::run` | Variable 'loops' is assigned a value that is never used. | later |
| F-027 | clang-tidy | cppcoreguidelines-pro-type-member-init | `src/config.cpp` › `Config::Config` | constructor does not initialize these fields: grace_ms_ | fix |
| F-028 | clang-tidy | bugprone-unused-return-value | `src/main.cpp` › `main` | the value returned by this function should not be disregarded; neglecting it may lead to errors (`sd_notify`) | fix |
| F-029 | cppcheck | missingOverride | `src/log_writer.h` › `JournalSink::write` | The function 'write' overrides a function in a base class but is not marked with a 'override' specifier. | later |
| F-030 | clang-tidy | bugprone-easily-swappable-parameters | `src/supervisor.cpp` › `Supervisor::Supervisor` | 2 adjacent parameters of 'Supervisor' of similar type ('std::chrono::milliseconds') are easily swapped by mistake | later |
