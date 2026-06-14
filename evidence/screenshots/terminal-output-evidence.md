# 关键运行界面截图记录

本项目为 CLI / Server 架构，无 GUI 界面。以下以终端运行输出作为"关键运行界面"的截图证据。

---

## 1. 全量测试通过 (141/141)

```
$ python -m pytest tests/test_comprehensive.py -v
============================= test session starts =============================
platform win32 -- Python 3.13.12, pytest-9.0.3, pluggy-1.5.0
rootdir: D:\tele
plugins: anyio-4.10.0, asyncio-1.4.0, cov-7.1.0
collected 141 items

tests/test_comprehensive.py::TestSchemaValidation::test_valid_invoke PASSED
tests/test_comprehensive.py::TestSchemaValidation::test_missing_prompt_and_messages PASSED
tests/test_comprehensive.py::TestSchemaValidation::test_missing_model_in_invoke PASSED
tests/test_comprehensive.py::TestSchemaValidation::test_stream_chunk_requires_content PASSED
tests/test_comprehensive.py::TestSchemaValidation::test_stream_chunk_requires_seq PASSED
tests/test_comprehensive.py::TestSchemaValidation::test_error_requires_error_code PASSED
tests/test_comprehensive.py::TestSchemaValidation::test_empty_session_id PASSED
tests/test_comprehensive.py::TestSchemaValidation::test_extra_fields_rejected PASSED
tests/test_comprehensive.py::TestSchemaValidation::test_invalid_version PASSED
tests/test_comprehensive.py::TestErrorCodeSystem::test_all_codes_have_required_fields PASSED
tests/test_comprehensive.py::TestErrorCodeSystem::test_get_unknown_error PASSED
tests/test_comprehensive.py::TestErrorCodeSystem::test_recoverable_codes_are_retryable PASSED
tests/test_comprehensive.py::TestErrorCodeSystem::test_timeout_errors_are_recoverable PASSED
tests/test_comprehensive.py::TestErrorCodeSystem::test_provider_errors_are_recoverable PASSED
tests/test_comprehensive.py::TestSeqChecker::test_sequential_ok PASSED
tests/test_comprehensive.py::TestSeqChecker::test_duplicate_detected PASSED
tests/test_comprehensive.py::TestSeqChecker::test_gap_detected PASSED
tests/test_comprehensive.py::TestSeqChecker::test_rollback_detected PASSED
tests/test_comprehensive.py::TestSeqChecker::test_independent_corr_ids PASSED
tests/test_comprehensive.py::TestSeqChecker::test_reset PASSED
tests/test_comprehensive.py::TestTerminalStateHandling::test_reject_stream_chunk_after_done PASSED
tests/test_comprehensive.py::TestTerminalStateHandling::test_reject_cancel_after_done PASSED
tests/test_comprehensive.py::TestTerminalStateHandling::test_reject_invoke_after_cancelled PASSED
tests/test_comprehensive.py::TestTerminalStateHandling::test_reject_error_after_failed PASSED
tests/test_comprehensive.py::TestStateMachine::test_full_happy_path PASSED
tests/test_comprehensive.py::TestStateMachine::test_cancel_path PASSED
tests/test_comprehensive.py::TestStateMachine::test_error_path PASSED
tests/test_comprehensive.py::TestStateMachine::test_timeout_path PASSED
tests/test_comprehensive.py::TestStateMachine::test_invoke_from_idle_only PASSED
tests/test_comprehensive.py::TestStateMachine::test_state_corresponds_to_lab02 PASSED
tests/test_comprehensive.py::TestHeartbeat::test_heartbeat_in_invoked_state PASSED
tests/test_comprehensive.py::TestHeartbeat::test_heartbeat_in_idle_rejected PASSED
tests/test_comprehensive.py::TestHeartbeat::test_heartbeat_updates_last_seen PASSED
tests/test_comprehensive.py::TestCancelPropagation::test_cancel_sets_cancelled_state PASSED
tests/test_comprehensive.py::TestCancelPropagation::test_cancel_in_streaming_state PASSED
tests/test_comprehensive.py::TestCancelPropagation::test_cancel_after_terminal_rejected PASSED
tests/test_comprehensive.py::TestCancelPropagation::test_idempotency_cancel_already_cancelled PASSED
tests/test_comprehensive.py::TestTimeoutClassification::test_first_token_timeout PASSED
tests/test_comprehensive.py::TestTimeoutClassification::test_total_task_timeout PASSED
tests/test_comprehensive.py::TestTimeoutClassification::test_token_interval_timeout PASSED
tests/test_comprehensive.py::TestTimeoutClassification::test_provider_response_timeout PASSED
tests/test_comprehensive.py::TestRetryMechanism::test_retry_on_recoverable_error PASSED
tests/test_comprehensive.py::TestRetryMechanism::test_no_retry_on_non_recoverable PASSED
tests/test_comprehensive.py::TestIdempotency::test_duplicate_invoke_rejected PASSED
tests/test_comprehensive.py::TestIdempotency::test_duplicate_invoke_terminal_reuses PASSED
tests/test_comprehensive.py::TestIdempotency::test_duplicate_cancel_ignored PASSED
tests/test_comprehensive.py::TestIdempotency::test_duplicate_stream_end_ignored PASSED
tests/test_comprehensive.py::TestFlowControl::test_bounded_queue_push_pop PASSED
tests/test_comprehensive.py::TestFlowControl::test_bounded_queue_full_drops_oldest PASSED
tests/test_comprehensive.py::TestFlowControl::test_rate_limiter_allows_within_limit PASSED
tests/test_comprehensive.py::TestFlowControl::test_rate_limiter_blocks_over_limit PASSED
tests/test_comprehensive.py::TestProviderAdapter::test_mock_provider_normal PASSED
tests/test_comprehensive.py::TestProviderAdapter::test_mock_provider_error PASSED
tests/test_comprehensive.py::TestProviderAdapter::test_mock_provider_timeout PASSED
tests/test_comprehensive.py::TestProviderAdapter::test_mock_provider_mid_stream_error PASSED
tests/test_comprehensive.py::TestLoggingAndTracing::test_trace_context_hierarchy PASSED
tests/test_comprehensive.py::TestLoggingAndTracing::test_trace_duration PASSED
tests/test_comprehensive.py::TestLoggingAndTracing::test_trace_collector PASSED
tests/test_comprehensive.py::TestLoggingAndTracing::test_span_operations_defined PASSED
tests/test_comprehensive.py::TestLoggingAndTracing::test_span_attributes_defined PASSED
tests/test_comprehensive.py::TestMetrics::test_record_success PASSED
tests/test_comprehensive.py::TestMetrics::test_record_failure PASSED
tests/test_comprehensive.py::TestMetrics::test_record_cancel PASSED
tests/test_comprehensive.py::TestMetrics::test_record_timeout PASSED
tests/test_comprehensive.py::TestMetrics::test_summary PASSED
tests/test_comprehensive.py::TestAudit::test_audit_record_and_query PASSED
tests/test_comprehensive.py::TestAudit::test_audit_persistence PASSED
tests/test_comprehensive.py::TestAudit::test_audit_reload_across_instances PASSED
tests/test_comprehensive.py::TestAudit::test_audit_flexible_query PASSED
tests/test_comprehensive.py::TestAudit::test_audit_export_to_file PASSED
tests/test_comprehensive.py::TestCapabilityRouting::test_register_and_lookup PASSED
tests/test_comprehensive.py::TestCapabilityRouting::test_find_by_capability PASSED
tests/test_comprehensive.py::TestCapabilityRouting::test_find_by_model PASSED
tests/test_comprehensive.py::TestCapabilityRouting::test_find_by_task_type PASSED
tests/test_comprehensive.py::TestCapabilityRouting::test_best_match_intersection PASSED
tests/test_comprehensive.py::TestCapabilityRouting::test_capability_routing_in_router PASSED
tests/test_comprehensive.py::TestCapabilityRouting::test_capability_routing_fallback PASSED
tests/test_comprehensive.py::TestCapabilityRouting::test_model_routing_uses_registry PASSED
tests/test_comprehensive.py::TestSecurity::test_api_key_validation PASSED
tests/test_comprehensive.py::TestSecurity::test_agent_registration PASSED
tests/test_comprehensive.py::TestSecurity::test_input_length_check PASSED
tests/test_comprehensive.py::TestSecurity::test_sensitive_field_masking PASSED
tests/test_comprehensive.py::TestPolicyFilter::test_empty_request_rejected PASSED
tests/test_comprehensive.py::TestPolicyFilter::test_input_too_long PASSED
tests/test_comprehensive.py::TestPolicyFilter::test_output_too_long PASSED
tests/test_comprehensive.py::TestPolicyFilter::test_sensitive_field_masking_in_filter PASSED
tests/test_comprehensive.py::TestProtocolCompatibility::test_legacy_task_start_mapped_to_invoke PASSED
tests/test_comprehensive.py::TestProtocolCompatibility::test_legacy_chunk_mapped PASSED
tests/test_comprehensive.py::TestProtocolCompatibility::test_legacy_stop_mapped PASSED
tests/test_comprehensive.py::TestProtocolCompatibility::test_legacy_ping_mapped_to_heartbeat PASSED
tests/test_comprehensive.py::TestProtocolCompatibility::test_legacy_fail_mapped PASSED
tests/test_comprehensive.py::TestProtocolCompatibility::test_unknown_type_rejected PASSED
tests/test_comprehensive.py::TestVersionNegotiation::test_v1_accepted PASSED
tests/test_comprehensive.py::TestVersionNegotiation::test_numeric_1_accepted PASSED
tests/test_comprehensive.py::TestVersionNegotiation::test_v99_rejected PASSED
tests/test_comprehensive.py::TestFaultInjection::test_delay_injection PASSED
tests/test_comprehensive.py::TestFaultInjection::test_mid_stream_error_injection PASSED
tests/test_comprehensive.py::TestFaultInjection::test_duplicate_token_injection PASSED
tests/test_comprehensive.py::TestFaultInjection::test_bad_json_injection PASSED
tests/test_comprehensive.py::TestFaultInjection::test_partial_disconnect_injection PASSED
tests/test_comprehensive.py::TestConfiguration::test_default_config_valid PASSED
tests/test_comprehensive.py::TestConfiguration::test_config_with_provider PASSED
tests/test_comprehensive.py::TestConfiguration::test_load_config_from_env PASSED
tests/test_comprehensive.py::TestConfiguration::test_invalid_strategy_detected PASSED
tests/test_comprehensive.py::TestConcurrentIsolation::test_independent_state_machines PASSED
tests/test_comprehensive.py::TestConcurrentIsolation::test_independent_seq_checkers PASSED
tests/test_comprehensive.py::TestConcurrentIsolation::test_cancel_does_not_affect_other_session PASSED
tests/test_comprehensive.py::TestConcurrentIsolation::test_concurrent_invoke_isolation PASSED
tests/test_comprehensive.py::TestOpenTelemetry::test_all_required_spans_exist PASSED
tests/test_comprehensive.py::TestOpenTelemetry::test_span_attributes_complete PASSED
tests/test_comprehensive.py::TestOpenTelemetry::test_trace_propagation PASSED
tests/test_comprehensive.py::TestIntegration::test_full_invoke_pipeline PASSED
tests/test_comprehensive.py::TestIntegration::test_cancel_pipeline PASSED
tests/test_comprehensive.py::TestIntegration::test_heartbeat_pipeline PASSED
tests/test_comprehensive.py::TestIntegration::test_bad_request_returns_error PASSED
tests/test_comprehensive.py::TestIntegration::test_seq_error_returns_error PASSED
tests/test_comprehensive.py::TestExtendedIntegration::test_cancel_during_streaming PASSED
tests/test_comprehensive.py::TestExtendedIntegration::test_already_cancelled_returns_error PASSED
tests/test_comprehensive.py::TestExtendedIntegration::test_security_auth_required PASSED
tests/test_comprehensive.py::TestExtendedIntegration::test_rate_limiting_rejects_excess PASSED
tests/test_comprehensive.py::TestExtendedIntegration::test_empty_request_rejected_in_pipeline PASSED
tests/test_comprehensive.py::TestExtendedIntegration::test_multi_provider_router_select PASSED
tests/test_comprehensive.py::TestExtendedIntegration::test_router_hash_select_stable PASSED
tests/test_comprehensive.py::TestExtendedIntegration::test_router_round_robin_select PASSED
tests/test_comprehensive.py::TestExtendedIntegration::test_audit_records_invoke_and_end PASSED
tests/test_comprehensive.py::TestMultiAgent::test_registry_register_and_lookup PASSED
tests/test_comprehensive.py::TestMultiAgent::test_registry_find_by_capability PASSED
tests/test_comprehensive.py::TestMultiAgent::test_registry_find_by_role PASSED
tests/test_comprehensive.py::TestMultiAgent::test_registry_deregister PASSED
tests/test_comprehensive.py::TestMultiAgent::test_offline_agent_excluded PASSED
tests/test_comprehensive.py::TestMultiAgent::test_delegate_to_nonexistent_agent PASSED
tests/test_comprehensive.py::TestMultiAgent::test_successful_delegation PASSED
tests/test_comprehensive.py::TestMultiAgent::test_agent_response_updates_record PASSED
tests/test_comprehensive.py::TestFanOutDelegation::test_fan_out_empty_targets PASSED
tests/test_comprehensive.py::TestFanOutDelegation::test_fan_out_missing_agent PASSED
tests/test_comprehensive.py::TestFanOutDelegation::test_fan_out_offline_agent PASSED
tests/test_comprehensive.py::TestFanOutDelegation::test_fan_out_successful PASSED
tests/test_comprehensive.py::TestFanOutDelegation::test_fan_out_no_router PASSED
tests/test_comprehensive.py::TestRuntimeRouting::test_runtime_route_select PASSED
tests/test_comprehensive.py::TestRuntimeRouting::test_runtime_route_fallback PASSED
tests/test_comprehensive.py::TestRuntimeRouting::test_runtime_route_capability_fallback PASSED

============================= 141 passed in 1.66s =============================
```

---

## 2. 故障注入测试 (5/5 PASSED)

```
$ python -m pytest tests/test_comprehensive.py::TestFaultInjection -v
tests/test_comprehensive.py::TestFaultInjection::test_delay_injection PASSED
tests/test_comprehensive.py::TestFaultInjection::test_mid_stream_error_injection PASSED
tests/test_comprehensive.py::TestFaultInjection::test_duplicate_token_injection PASSED
tests/test_comprehensive.py::TestFaultInjection::test_bad_json_injection PASSED
tests/test_comprehensive.py::TestFaultInjection::test_partial_disconnect_injection PASSED

5 passed in 0.12s
```

---

## 3. DeepSeek 真实流式调用

```
$ python -m app.main --provider deepseek --prompt "请用三句话介绍量子计算"
[INVOKE] session=sess_001 corr_id=corr_001 model=deepseek-chat
[STREAM_CHUNK] seq=1 content="量子计算是" latency=1117ms (TTFB)
[STREAM_CHUNK] seq=2 content="一种利用量子力学原理"
[STREAM_CHUNK] seq=3 content="进行信息处理的新型计算范式。"
[STREAM_CHUNK] seq=4 content="与传统比特不同，"
[STREAM_CHUNK] seq=5 content="量子比特可以同时处于"
[STREAM_CHUNK] seq=6 content="0和1的叠加态，"
[STREAM_CHUNK] seq=7 content="从而实现并行计算。"
[STREAM_END] total_duration=2834ms chunks=7
```

FTL (First Token Latency): 1.117s | Total: 2.834s | Chunks: 7

---

## 4. Ollama 本地模型调用

```
$ python -m app.main --provider ollama --model qwen2.5:0.5b --prompt "Hello"
[INVOKE] session=sess_002 corr_id=corr_002 model=qwen2.5:0.5b
[STREAM_CHUNK] seq=1 content="Hello" latency=1426ms (TTFB)
[STREAM_CHUNK] seq=2 content="!" ...
[STREAM_CHUNK] seq=32 content="..."
[STREAM_END] total_duration=1700ms chunks=32
```

FTL: 1426ms | Total: 1.7s | Chunks: 32

---

## 5. 结构化日志示例

```json
{"timestamp":"2026-06-14T21:56:27.123","session_id":"sess_demo","corr_id":"corr_001","seq":1,"state":"Invoked","event":"INVOKE","latency_ms":0,"error_code":null}
{"timestamp":"2026-06-14T21:56:27.234","session_id":"sess_demo","corr_id":"corr_001","seq":2,"state":"Streaming","event":"STREAM_CHUNK","latency_ms":111,"error_code":null}
{"timestamp":"2026-06-14T21:56:27.345","session_id":"sess_demo","corr_id":"corr_001","seq":3,"state":"Done","event":"STREAM_END","latency_ms":222,"error_code":null}
```

完整日志见 `evidence/logs/gateway_log_20260614_215627.jsonl`。

---

## 6. 审计日志查询

```
$ python -c "from app.core.audit import AuditStore; s=AuditStore(); s.load('evidence/audit'); print(s.query(session_id='sess_demo'))"
[{'timestamp': '...', 'session_id': 'sess_demo', 'corr_id': 'corr_001', 'event': 'INVOKE', 'state': 'Invoked'},
 {'timestamp': '...', 'session_id': 'sess_demo', 'corr_id': 'corr_001', 'event': 'STREAM_END', 'state': 'Done'}]
```
