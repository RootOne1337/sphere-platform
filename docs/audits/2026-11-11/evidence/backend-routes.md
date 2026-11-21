# Реестр маршрутов backend

Получено из `backend.main.app.routes` и `app.openapi()` на `94cf7c3a` после локального импорта с синтетическими настройками. Перечень фиксирует регистрацию, а проверка поведения отмечена в [аудите backend](../BACKEND-DATA.md).

Зарегистрирован 201 HTTP API маршрут и 5 WebSocket маршрутов. В OpenAPI 201 операция на 160 путях.

Дополнительные пути Starlette включают `/openapi.json`, `/api/docs`, `/docs/oauth2-redirect`, `/api/redoc`, `/metrics`.

| Метод | Путь | Обработчик | Успех в runtime OpenAPI |
| --- | --- | --- | --- |
| GET | `/api/v1/account-sessions` | [list_account_sessions](../../../../backend/api/v1/account_sessions/router.py#L54) | 200 |
| POST | `/api/v1/account-sessions` | [start_session](../../../../backend/api/v1/account_sessions/router.py#L87) | 201 |
| GET | `/api/v1/account-sessions/stats` | [get_session_stats](../../../../backend/api/v1/account_sessions/router.py#L39) | 200 |
| GET | `/api/v1/account-sessions/{session_id}` | [get_session](../../../../backend/api/v1/account_sessions/router.py#L100) | 200 |
| POST | `/api/v1/account-sessions/{session_id}/end` | [end_session](../../../../backend/api/v1/account_sessions/router.py#L110) | 200 |
| GET | `/api/v1/audit/logs` | [list_audit_logs](../../../../backend/api/v1/audit/router.py#L23) | 200 |
| GET | `/api/v1/audit/logs/export` | [export_audit_logs](../../../../backend/api/v1/audit/router.py#L59) | 200 |
| GET | `/api/v1/auth/api-keys` | [list_api_keys](../../../../backend/api/v1/auth/router.py#L393) | 200 |
| POST | `/api/v1/auth/api-keys` | [create_api_key](../../../../backend/api/v1/auth/router.py#L353) | 201 |
| DELETE | `/api/v1/auth/api-keys/{key_id}` | [revoke_api_key](../../../../backend/api/v1/auth/router.py#L409) | 200 |
| GET | `/api/v1/auth/capabilities` | [capabilities](../../../../backend/api/v1/auth/router.py#L264) | 200 |
| POST | `/api/v1/auth/login` | [login](../../../../backend/api/v1/auth/router.py#L65) | 200 |
| POST | `/api/v1/auth/login/mfa` | [login_mfa](../../../../backend/api/v1/auth/router.py#L111) | 200 |
| POST | `/api/v1/auth/logout` | [logout](../../../../backend/api/v1/auth/router.py#L213) | 204 |
| GET | `/api/v1/auth/me` | [me](../../../../backend/api/v1/auth/router.py#L254) | 200 |
| DELETE | `/api/v1/auth/mfa` | [mfa_disable](../../../../backend/api/v1/auth/router.py#L335) | 200 |
| POST | `/api/v1/auth/mfa/setup` | [mfa_setup](../../../../backend/api/v1/auth/router.py#L276) | 200 |
| POST | `/api/v1/auth/mfa/verify-setup` | [mfa_verify_setup](../../../../backend/api/v1/auth/router.py#L299) | 200 |
| POST | `/api/v1/auth/refresh` | [refresh](../../../../backend/api/v1/auth/router.py#L150) | 200 |
| POST | `/api/v1/batches` | [start_batch](../../../../backend/api/v1/batches/router.py#L60) | 202 |
| POST | `/api/v1/batches/broadcast` | [broadcast_batch](../../../../backend/api/v1/batches/router.py#L84) | 202 |
| DELETE | `/api/v1/batches/{batch_id}` | [cancel_batch](../../../../backend/api/v1/batches/router.py#L129) | 204 |
| GET | `/api/v1/batches/{batch_id}` | [get_batch_status](../../../../backend/api/v1/batches/router.py#L113) | 200 |
| GET | `/api/v1/config/agent` | [get_agent_config](../../../../backend/api/v1/config/router.py#L80) | 200 |
| GET | `/api/v1/device-events` | [list_device_events](../../../../backend/api/v1/device_events/router.py#L51) | 200 |
| POST | `/api/v1/device-events` | [create_device_event](../../../../backend/api/v1/device_events/router.py#L88) | 201 |
| GET | `/api/v1/device-events/stats` | [get_event_stats](../../../../backend/api/v1/device_events/router.py#L38) | 200 |
| GET | `/api/v1/device-events/{event_id}` | [get_device_event](../../../../backend/api/v1/device_events/router.py#L101) | 200 |
| POST | `/api/v1/device-events/{event_id}/processed` | [mark_event_processed](../../../../backend/api/v1/device_events/router.py#L111) | 200 |
| GET | `/api/v1/devices` | [list_devices](../../../../backend/api/v1/devices/router.py#L133) | 200 |
| POST | `/api/v1/devices` | [create_device](../../../../backend/api/v1/devices/router.py#L381) | 201 |
| DELETE | `/api/v1/devices/bulk` | [bulk_delete](../../../../backend/api/v1/bulk/router.py#L56) | 200 |
| POST | `/api/v1/devices/bulk/action` | [bulk_action](../../../../backend/api/v1/bulk/router.py#L38) | 200 |
| GET | `/api/v1/devices/me` | [get_device_me](../../../../backend/api/v1/devices/router.py#L93) | 200 |
| POST | `/api/v1/devices/refresh` | [refresh_device](../../../../backend/api/v1/devices/router.py#L308) | 200 |
| POST | `/api/v1/devices/register` | [register_device](../../../../backend/api/v1/devices/router.py#L325) | 201 |
| POST | `/api/v1/devices/status/bulk` | [get_bulk_status](../../../../backend/api/v1/devices/router.py#L269) | 200 |
| GET | `/api/v1/devices/status/fleet` | [get_fleet_status](../../../../backend/api/v1/devices/router.py#L286) | 200 |
| DELETE | `/api/v1/devices/{device_id}` | [delete_device](../../../../backend/api/v1/devices/router.py#L455) | 204 |
| GET | `/api/v1/devices/{device_id}` | [get_device](../../../../backend/api/v1/devices/router.py#L401) | 200 |
| PUT | `/api/v1/devices/{device_id}` | [update_device](../../../../backend/api/v1/devices/router.py#L435) | 200 |
| POST | `/api/v1/devices/{device_id}/connect` | [connect_device](../../../../backend/api/v1/devices/router.py#L546) | 204 |
| GET | `/api/v1/devices/{device_id}/direct-probe-capabilities` | [probe_capabilities](../../../../backend/api/v1/direct_probe/router.py#L97) | 200 |
| POST | `/api/v1/devices/{device_id}/logcat` | [request_logcat](../../../../backend/api/v1/devices/router.py#L845) | 200 |
| POST | `/api/v1/devices/{device_id}/reboot` | [reboot_device](../../../../backend/api/v1/devices/router.py#L881) | 200 |
| GET | `/api/v1/devices/{device_id}/screenshot` | [take_screenshot](../../../../backend/api/v1/devices/router.py#L565) | 200 |
| POST | `/api/v1/devices/{device_id}/screenshot/native` | [request_native_screenshot](../../../../backend/api/v1/devices/router.py#L731) | 200 |
| POST | `/api/v1/devices/{device_id}/shell` | [execute_shell](../../../../backend/api/v1/devices/router.py#L818) | 200 |
| GET | `/api/v1/devices/{device_id}/status` | [get_device_status](../../../../backend/api/v1/devices/router.py#L474) | 200 |
| GET | `/api/v1/devices/{device_id}/stream-diagnostics` | [get_device_stream_diagnostics](../../../../backend/api/v1/devices/router.py#L487) | 200 |
| GET | `/api/v1/devices/{device_id}/stream-sessions` | [stream_session_history](../../../../backend/api/v1/direct_probe/router.py#L50) | 200 |
| POST | `/api/v1/devices/{device_id}/ui-hierarchy` | [request_ui_hierarchy](../../../../backend/api/v1/devices/router.py#L612) | 200 |
| POST | `/api/v1/devices/{device_id}/viewers` | [pulse_device_card_viewer](../../../../backend/api/v1/devices/router.py#L60) | 200 |
| POST | `/api/v1/discovery/scan` | [scan_subnet](../../../../backend/api/v1/discovery/router.py#L24) | 200 |
| GET | `/api/v1/event-triggers` | [list_event_triggers](../../../../backend/api/v1/event_triggers/router.py#L36) | 200 |
| POST | `/api/v1/event-triggers` | [create_event_trigger](../../../../backend/api/v1/event_triggers/router.py#L84) | 201 |
| DELETE | `/api/v1/event-triggers/{trigger_id}` | [delete_event_trigger](../../../../backend/api/v1/event_triggers/router.py#L178) | 204 |
| GET | `/api/v1/event-triggers/{trigger_id}` | [get_event_trigger](../../../../backend/api/v1/event_triggers/router.py#L124) | 200 |
| PATCH | `/api/v1/event-triggers/{trigger_id}` | [update_event_trigger](../../../../backend/api/v1/event_triggers/router.py#L140) | 200 |
| POST | `/api/v1/event-triggers/{trigger_id}/toggle` | [toggle_event_trigger](../../../../backend/api/v1/event_triggers/router.py#L204) | 200 |
| GET | `/api/v1/game-accounts` | [list_game_accounts](../../../../backend/api/v1/game_accounts/router.py#L83) | 200 |
| POST | `/api/v1/game-accounts` | [create_game_account](../../../../backend/api/v1/game_accounts/router.py#L124) | 201 |
| POST | `/api/v1/game-accounts/import` | [import_game_accounts](../../../../backend/api/v1/game_accounts/router.py#L144) | 200 |
| GET | `/api/v1/game-accounts/servers` | [list_servers](../../../../backend/api/v1/game_accounts/router.py#L64) | 200 |
| GET | `/api/v1/game-accounts/stats` | [get_account_stats](../../../../backend/api/v1/game_accounts/router.py#L50) | 200 |
| DELETE | `/api/v1/game-accounts/{account_id}` | [delete_game_account](../../../../backend/api/v1/game_accounts/router.py#L213) | 200 |
| GET | `/api/v1/game-accounts/{account_id}` | [get_game_account](../../../../backend/api/v1/game_accounts/router.py#L163) | 200 |
| PATCH | `/api/v1/game-accounts/{account_id}` | [update_game_account](../../../../backend/api/v1/game_accounts/router.py#L189) | 200 |
| POST | `/api/v1/game-accounts/{account_id}/assign` | [assign_game_account](../../../../backend/api/v1/game_accounts/router.py#L231) | 200 |
| POST | `/api/v1/game-accounts/{account_id}/release` | [release_game_account](../../../../backend/api/v1/game_accounts/router.py#L255) | 200 |
| GET | `/api/v1/groups` | [list_groups](../../../../backend/api/v1/groups/router.py#L31) | 200 |
| POST | `/api/v1/groups` | [create_group](../../../../backend/api/v1/groups/router.py#L45) | 201 |
| PUT | `/api/v1/groups/devices/{device_id}/tags` | [set_device_tags](../../../../backend/api/v1/groups/router.py#L133) | 204 |
| GET | `/api/v1/groups/tags` | [list_tags](../../../../backend/api/v1/groups/router.py#L121) | 200 |
| DELETE | `/api/v1/groups/{group_id}` | [delete_group](../../../../backend/api/v1/groups/router.py#L83) | 204 |
| PUT | `/api/v1/groups/{group_id}` | [update_group](../../../../backend/api/v1/groups/router.py#L64) | 200 |
| POST | `/api/v1/groups/{group_id}/devices/move` | [move_devices](../../../../backend/api/v1/groups/router.py#L101) | 200 |
| GET | `/api/v1/health` | [health_check](../../../../backend/main.py#L103) | 200 |
| GET | `/api/v1/health/build` | [build_info](../../../../backend/api/v1/health/router.py#L29) | 200 |
| GET | `/api/v1/health/full` | [full_health](../../../../backend/api/v1/health/router.py#L78) | 200 |
| GET | `/api/v1/health/healthz` | [liveness](../../../../backend/api/v1/health/router.py#L42) | 200 |
| GET | `/api/v1/health/ready` | [readiness_check](../../../../backend/main.py#L108) | 200 |
| GET | `/api/v1/health/readyz` | [readiness](../../../../backend/api/v1/health/router.py#L60) | 200 |
| GET | `/api/v1/locations` | [list_locations](../../../../backend/api/v1/locations/router.py#L32) | 200 |
| POST | `/api/v1/locations` | [create_location](../../../../backend/api/v1/locations/router.py#L46) | 201 |
| DELETE | `/api/v1/locations/{location_id}` | [delete_location](../../../../backend/api/v1/locations/router.py#L93) | 204 |
| GET | `/api/v1/locations/{location_id}` | [get_location](../../../../backend/api/v1/locations/router.py#L63) | 200 |
| PUT | `/api/v1/locations/{location_id}` | [update_location](../../../../backend/api/v1/locations/router.py#L74) | 200 |
| DELETE | `/api/v1/locations/{location_id}/devices` | [remove_devices](../../../../backend/api/v1/locations/router.py#L134) | 200 |
| POST | `/api/v1/locations/{location_id}/devices` | [assign_devices](../../../../backend/api/v1/locations/router.py#L114) | 200 |
| POST | `/api/v1/logs/upload` | [upload_logs](../../../../backend/api/v1/logs/router.py#L96) | 200 |
| DELETE | `/api/v1/logs/{device_id}` | [delete_device_logs](../../../../backend/api/v1/logs/router.py#L184) | 200 |
| GET | `/api/v1/logs/{device_id}` | [get_device_logs](../../../../backend/api/v1/logs/router.py#L155) | 200 |
| POST | `/api/v1/monitoring/alerts` | [receive_alerts](../../../../backend/api/v1/monitoring/router.py#L65) | 200 |
| GET | `/api/v1/monitoring/fleet-coverage` | [get_fleet_coverage](../../../../backend/api/v1/monitoring/router.py#L31) | 200 |
| GET | `/api/v1/monitoring/metrics` | [get_monitoring_metrics](../../../../backend/api/v1/monitoring/router.py#L122) | 200 |
| GET | `/api/v1/monitoring/nodes` | [get_monitoring_nodes](../../../../backend/api/v1/monitoring/router.py#L172) | 200 |
| POST | `/api/v1/n8n/tasks` | [create_task](../../../../backend/api/v1/n8n/router.py#L149) | 201 |
| GET | `/api/v1/n8n/tasks/{task_id}` | [get_task_status](../../../../backend/api/v1/n8n/router.py#L185) | 200 |
| GET | `/api/v1/n8n/webhooks` | [list_webhooks](../../../../backend/api/v1/n8n/router.py#L55) | 200 |
| POST | `/api/v1/n8n/webhooks` | [create_webhook](../../../../backend/api/v1/n8n/router.py#L26) | 201 |
| DELETE | `/api/v1/n8n/webhooks/{webhook_id}` | [delete_webhook](../../../../backend/api/v1/n8n/router.py#L109) | 200 |
| GET | `/api/v1/n8n/webhooks/{webhook_id}` | [get_webhook](../../../../backend/api/v1/n8n/router.py#L69) | 200 |
| PATCH | `/api/v1/n8n/webhooks/{webhook_id}` | [update_webhook](../../../../backend/api/v1/n8n/router.py#L83) | 200 |
| GET | `/api/v1/pipeline-settings` | [get_settings](../../../../backend/api/v1/pipeline_settings/router.py#L56) | 200 |
| PATCH | `/api/v1/pipeline-settings` | [update_settings](../../../../backend/api/v1/pipeline_settings/router.py#L76) | 200 |
| POST | `/api/v1/pipeline-settings/nick/check` | [check_nick](../../../../backend/api/v1/pipeline_settings/router.py#L327) | 200 |
| POST | `/api/v1/pipeline-settings/nick/generate` | [generate_nicks](../../../../backend/api/v1/pipeline_settings/router.py#L306) | 200 |
| GET | `/api/v1/pipeline-settings/servers` | [list_servers](../../../../backend/api/v1/pipeline_settings/router.py#L288) | 200 |
| GET | `/api/v1/pipeline-settings/status` | [get_orchestration_status](../../../../backend/api/v1/pipeline_settings/router.py#L180) | 200 |
| POST | `/api/v1/pipeline-settings/toggle/farming` | [toggle_farming](../../../../backend/api/v1/pipeline_settings/router.py#L159) | 200 |
| POST | `/api/v1/pipeline-settings/toggle/orchestration` | [toggle_orchestration](../../../../backend/api/v1/pipeline_settings/router.py#L103) | 200 |
| POST | `/api/v1/pipeline-settings/toggle/registration` | [toggle_registration](../../../../backend/api/v1/pipeline_settings/router.py#L141) | 200 |
| POST | `/api/v1/pipeline-settings/toggle/scheduler` | [toggle_scheduler](../../../../backend/api/v1/pipeline_settings/router.py#L122) | 200 |
| GET | `/api/v1/pipelines` | [list_pipelines](../../../../backend/api/v1/pipelines/router.py#L80) | 200 |
| POST | `/api/v1/pipelines` | [create_pipeline](../../../../backend/api/v1/pipelines/router.py#L110) | 201 |
| GET | `/api/v1/pipelines/runs` | [list_pipeline_runs](../../../../backend/api/v1/pipelines/router.py#L142) | 200 |
| GET | `/api/v1/pipelines/runs/{run_id}` | [get_pipeline_run](../../../../backend/api/v1/pipelines/router.py#L176) | 200 |
| POST | `/api/v1/pipelines/runs/{run_id}/cancel` | [cancel_pipeline_run](../../../../backend/api/v1/pipelines/router.py#L190) | 200 |
| POST | `/api/v1/pipelines/runs/{run_id}/pause` | [pause_pipeline_run](../../../../backend/api/v1/pipelines/router.py#L207) | 200 |
| POST | `/api/v1/pipelines/runs/{run_id}/resume` | [resume_pipeline_run](../../../../backend/api/v1/pipelines/router.py#L224) | 200 |
| DELETE | `/api/v1/pipelines/{pipeline_id}` | [delete_pipeline](../../../../backend/api/v1/pipelines/router.py#L281) | 204 |
| GET | `/api/v1/pipelines/{pipeline_id}` | [get_pipeline](../../../../backend/api/v1/pipelines/router.py#L246) | 200 |
| PATCH | `/api/v1/pipelines/{pipeline_id}` | [update_pipeline](../../../../backend/api/v1/pipelines/router.py#L260) | 200 |
| POST | `/api/v1/pipelines/{pipeline_id}/run` | [run_pipeline](../../../../backend/api/v1/pipelines/router.py#L323) | 201 |
| POST | `/api/v1/pipelines/{pipeline_id}/run-batch` | [run_pipeline_batch](../../../../backend/api/v1/pipelines/router.py#L346) | 201 |
| POST | `/api/v1/pipelines/{pipeline_id}/toggle` | [toggle_pipeline](../../../../backend/api/v1/pipelines/router.py#L298) | 200 |
| GET | `/api/v1/schedules` | [list_schedules](../../../../backend/api/v1/schedules/router.py#L74) | 200 |
| POST | `/api/v1/schedules` | [create_schedule](../../../../backend/api/v1/schedules/router.py#L104) | 201 |
| DELETE | `/api/v1/schedules/{schedule_id}` | [delete_schedule](../../../../backend/api/v1/schedules/router.py#L159) | 204 |
| GET | `/api/v1/schedules/{schedule_id}` | [get_schedule](../../../../backend/api/v1/schedules/router.py#L127) | 200 |
| PATCH | `/api/v1/schedules/{schedule_id}` | [update_schedule](../../../../backend/api/v1/schedules/router.py#L141) | 200 |
| GET | `/api/v1/schedules/{schedule_id}/executions` | [list_schedule_executions](../../../../backend/api/v1/schedules/router.py#L218) | 200 |
| POST | `/api/v1/schedules/{schedule_id}/fire-now` | [fire_schedule_now](../../../../backend/api/v1/schedules/router.py#L197) | 200 |
| POST | `/api/v1/schedules/{schedule_id}/toggle` | [toggle_schedule](../../../../backend/api/v1/schedules/router.py#L180) | 200 |
| GET | `/api/v1/scripts` | [list_scripts](../../../../backend/api/v1/scripts/router.py#L64) | 200 |
| POST | `/api/v1/scripts` | [create_script](../../../../backend/api/v1/scripts/router.py#L121) | 201 |
| GET | `/api/v1/scripts/action-contract` | [get_action_contract](../../../../backend/api/v1/scripts/router.py#L140) | 200 |
| GET | `/api/v1/scripts/catalog` | [list_script_catalog](../../../../backend/api/v1/scripts/router.py#L98) | 200 |
| POST | `/api/v1/scripts/validate` | [validate_script_draft](../../../../backend/api/v1/scripts/router.py#L152) | 200 |
| DELETE | `/api/v1/scripts/{script_id}` | [archive_script](../../../../backend/api/v1/scripts/router.py#L220) | 204 |
| GET | `/api/v1/scripts/{script_id}` | [get_script](../../../../backend/api/v1/scripts/router.py#L170) | 200 |
| PUT | `/api/v1/scripts/{script_id}` | [update_script](../../../../backend/api/v1/scripts/router.py#L198) | 200 |
| GET | `/api/v1/scripts/{script_id}/versions` | [list_versions](../../../../backend/api/v1/scripts/router.py#L239) | 200 |
| GET | `/api/v1/scripts/{script_id}/versions/{version_id}` | [get_version](../../../../backend/api/v1/scripts/router.py#L254) | 200 |
| POST | `/api/v1/scripts/{script_id}/versions/{version_id}/rollback` | [rollback](../../../../backend/api/v1/scripts/router.py#L266) | 200 |
| POST | `/api/v1/streaming/{device_id}/keyframe` | [request_keyframe](../../../../backend/api/v1/streaming/router.py#L146) | 200 |
| GET | `/api/v1/streaming/{device_id}/quality` | [get_stream_quality](../../../../backend/api/v1/streaming/router.py#L27) | 200 |
| POST | `/api/v1/streaming/{device_id}/quality` | [configure_stream_quality](../../../../backend/api/v1/streaming/router.py#L38) | 200 |
| POST | `/api/v1/streaming/{device_id}/start` | [request_stream_start](../../../../backend/api/v1/streaming/router.py#L111) | 200 |
| GET | `/api/v1/streaming/{device_id}/status` | [get_stream_status](../../../../backend/api/v1/streaming/router.py#L91) | 200 |
| POST | `/api/v1/streaming/{device_id}/stop` | [request_stream_stop](../../../../backend/api/v1/streaming/router.py#L132) | 200 |
| GET | `/api/v1/tasks` | [list_tasks](../../../../backend/api/v1/tasks/router.py#L94) | 200 |
| POST | `/api/v1/tasks` | [create_task](../../../../backend/api/v1/tasks/router.py#L141) | 201 |
| DELETE | `/api/v1/tasks/{task_id}` | [cancel_task](../../../../backend/api/v1/tasks/router.py#L338) | 204 |
| GET | `/api/v1/tasks/{task_id}` | [get_task](../../../../backend/api/v1/tasks/router.py#L193) | 200 |
| GET | `/api/v1/tasks/{task_id}/live-logs` | [get_task_live_logs](../../../../backend/api/v1/tasks/router.py#L257) | 200 |
| GET | `/api/v1/tasks/{task_id}/logs` | [get_task_logs](../../../../backend/api/v1/tasks/router.py#L209) | 200 |
| GET | `/api/v1/tasks/{task_id}/progress` | [get_task_progress](../../../../backend/api/v1/tasks/router.py#L228) | 200 |
| POST | `/api/v1/tasks/{task_id}/rerun` | [rerun_task](../../../../backend/api/v1/tasks/router.py#L175) | 201 |
| GET | `/api/v1/tasks/{task_id}/screenshots` | [get_task_screenshots](../../../../backend/api/v1/tasks/router.py#L280) | 200 |
| GET | `/api/v1/tasks/{task_id}/screenshots/content` | [get_task_screenshot_content](../../../../backend/api/v1/tasks/router.py#L300) | 200 |
| POST | `/api/v1/tasks/{task_id}/stop` | [force_stop_task](../../../../backend/api/v1/tasks/router.py#L356) | 200, 202 |
| GET | `/api/v1/updates/` | [list_releases](../../../../backend/api/v1/updates/router.py#L518) | 200 |
| POST | `/api/v1/updates/` | [create_release](../../../../backend/api/v1/updates/router.py#L535) | 201 |
| GET | `/api/v1/updates/artifacts/{sha256}` | [download_artifact](../../../../backend/api/v1/updates/router.py#L439) | 200 |
| GET | `/api/v1/updates/downloads/latest` | [download_latest_apk](../../../../backend/api/v1/updates/router.py#L460) | 200 |
| GET | `/api/v1/updates/latest` | [get_latest](../../../../backend/api/v1/updates/router.py#L382) | 200 |
| POST | `/api/v1/updates/recovery` | [create_recovery](../../../../backend/api/v1/updates/router.py#L244) | 201 |
| DELETE | `/api/v1/updates/recovery/{device_id}` | [revoke_recovery](../../../../backend/api/v1/updates/router.py#L361) | 204 |
| GET | `/api/v1/updates/recovery/{device_id}` | [get_recovery_status](../../../../backend/api/v1/updates/router.py#L295) | 200 |
| POST | `/api/v1/updates/recovery/{device_id}/dispatch` | [dispatch_recovery](../../../../backend/api/v1/updates/router.py#L275) | 202 |
| DELETE | `/api/v1/updates/{release_id}` | [delete_release](../../../../backend/api/v1/updates/router.py#L579) | 200 |
| GET | `/api/v1/users` | [list_users](../../../../backend/api/v1/users/router.py#L38) | 200 |
| POST | `/api/v1/users` | [create_user](../../../../backend/api/v1/users/router.py#L74) | 201 |
| GET | `/api/v1/users/{user_id}` | [get_user](../../../../backend/api/v1/users/router.py#L121) | 200 |
| PATCH | `/api/v1/users/{user_id}/deactivate` | [deactivate_user](../../../../backend/api/v1/users/router.py#L198) | 200 |
| PUT | `/api/v1/users/{user_id}/role` | [update_user_role](../../../../backend/api/v1/users/router.py#L141) | 200 |
| POST | `/api/v1/vpn/admin/config-preview` | [preview_config](../../../../backend/api/v1/vpn/router.py#L145) | 200 |
| POST | `/api/v1/vpn/admin/keypair` | [generate_keypair](../../../../backend/api/v1/vpn/router.py#L133) | 200 |
| POST | `/api/v1/vpn/assign` | [assign_vpn](../../../../backend/api/v1/vpn/router.py#L183) | 200 |
| GET | `/api/v1/vpn/health` | [vpn_health](../../../../backend/api/v1/vpn/router.py#L276) | 200 |
| POST | `/api/v1/vpn/killswitch` | [manage_killswitch](../../../../backend/api/v1/vpn/router.py#L458) | 200 |
| GET | `/api/v1/vpn/peers` | [list_peers](../../../../backend/api/v1/vpn/router.py#L291) | 200 |
| GET | `/api/v1/vpn/pool/stats` | [pool_stats](../../../../backend/api/v1/vpn/router.py#L342) | 200 |
| POST | `/api/v1/vpn/profile-preflight` | [vpn_profile_preflight](../../../../backend/api/v1/vpn/router.py#L112) | 200 |
| GET | `/api/v1/vpn/profiles` | [list_profiles](../../../../backend/api/v1/vpn/profile_router.py#L38) | 200 |
| POST | `/api/v1/vpn/profiles` | [import_profile](../../../../backend/api/v1/vpn/profile_router.py#L49) | 200 |
| POST | `/api/v1/vpn/profiles/batch` | [import_profiles](../../../../backend/api/v1/vpn/profile_router.py#L73) | 200 |
| POST | `/api/v1/vpn/profiles/batch/preflight` | [inspect_profiles](../../../../backend/api/v1/vpn/profile_router.py#L64) | 200 |
| POST | `/api/v1/vpn/profiles/batch/status` | [profiles_import_status](../../../../backend/api/v1/vpn/profile_router.py#L84) | 200 |
| GET | `/api/v1/vpn/profiles/imports/{request_id}` | [import_status](../../../../backend/api/v1/vpn/profile_router.py#L59) | 200 |
| GET | `/api/v1/vpn/profiles/{profile_id}` | [get_profile](../../../../backend/api/v1/vpn/profile_router.py#L92) | 200 |
| POST | `/api/v1/vpn/profiles/{profile_id}/archive` | [archive_profile](../../../../backend/api/v1/vpn/profile_router.py#L114) | 200 |
| GET | `/api/v1/vpn/profiles/{profile_id}/revisions` | [profile_revisions](../../../../backend/api/v1/vpn/profile_router.py#L97) | 200 |
| POST | `/api/v1/vpn/profiles/{profile_id}/revisions` | [append_revision](../../../../backend/api/v1/vpn/profile_router.py#L105) | 200 |
| GET | `/api/v1/vpn/providers` | [vpn_providers](../../../../backend/api/v1/vpn/router.py#L105) | 200 |
| POST | `/api/v1/vpn/revoke/bulk` | [bulk_revoke_vpn](../../../../backend/api/v1/vpn/router.py#L232) | 200 |
| DELETE | `/api/v1/vpn/revoke/{device_id}` | [revoke_vpn](../../../../backend/api/v1/vpn/router.py#L213) | 204 |
| POST | `/api/v1/vpn/rotate` | [bulk_rotate](../../../../backend/api/v1/vpn/router.py#L387) | 200 |
| GET | `/api/v1/vpn/runtime` | [app_vpn_devices](../../../../backend/api/v1/vpn/runtime_router.py#L20) | 200 |
| WS | `/ws/agent/{workstation_id}` | [pc_agent_ws](../../../../backend/api/ws/agent/router.py#L192) | — |
| WS | `/ws/android/{device_id}` | [android_agent_ws](../../../../backend/api/ws/android/router.py#L632) | — |
| WS | `/ws/direct-probe/{device_id}` | [direct_probe_ws](../../../../backend/api/ws/direct/router.py#L77) | — |
| WS | `/ws/events` | [fleet_events_ws](../../../../backend/api/ws/events/router.py#L269) | — |
| WS | `/ws/stream/{device_id}` | [stream_viewer_ws](../../../../backend/api/ws/stream/router.py#L96) | — |

## Сверка с корневым `openapi.json`

`docs/openapi.json` полностью совпал по JSON-данным с `app.openapi()`. Корневой файл содержит 161 операцию на 125 путях.

Только в runtime: `GET /api/v1/audit/logs/export`, `GET /api/v1/auth/capabilities`, `POST /api/v1/devices/refresh`, `GET /api/v1/devices/{device_id}/direct-probe-capabilities`, `POST /api/v1/devices/{device_id}/screenshot/native`, `GET /api/v1/devices/{device_id}/stream-diagnostics`, `GET /api/v1/devices/{device_id}/stream-sessions`, `POST /api/v1/devices/{device_id}/ui-hierarchy`, `POST /api/v1/devices/{device_id}/viewers`, `GET /api/v1/health/build`, `GET /api/v1/locations/{location_id}`, `GET /api/v1/monitoring/fleet-coverage`, `GET /api/v1/scripts/action-contract`, `GET /api/v1/scripts/catalog`, `POST /api/v1/scripts/validate`, `GET /api/v1/scripts/{script_id}/versions/{version_id}`, `GET /api/v1/streaming/{device_id}/quality`, `POST /api/v1/streaming/{device_id}/quality`, `POST /api/v1/tasks/{task_id}/rerun`, `GET /api/v1/tasks/{task_id}/screenshots/content`, `GET /api/v1/updates/artifacts/{sha256}`, `GET /api/v1/updates/downloads/latest`, `POST /api/v1/updates/recovery`, `DELETE /api/v1/updates/recovery/{device_id}`, `GET /api/v1/updates/recovery/{device_id}`, `POST /api/v1/updates/recovery/{device_id}/dispatch`, `POST /api/v1/vpn/profile-preflight`, `GET /api/v1/vpn/profiles`, `POST /api/v1/vpn/profiles`, `POST /api/v1/vpn/profiles/batch`, `POST /api/v1/vpn/profiles/batch/preflight`, `POST /api/v1/vpn/profiles/batch/status`, `GET /api/v1/vpn/profiles/imports/{request_id}`, `GET /api/v1/vpn/profiles/{profile_id}`, `POST /api/v1/vpn/profiles/{profile_id}/archive`, `GET /api/v1/vpn/profiles/{profile_id}/revisions`, `POST /api/v1/vpn/profiles/{profile_id}/revisions`, `GET /api/v1/vpn/providers`, `POST /api/v1/vpn/revoke/bulk`, `GET /api/v1/vpn/runtime`.

Только в snapshot: нет.

| Метод | Путь | Runtime-коды | Snapshot-коды |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/logout` | 204, 422 | 200, 422 |
| POST | `/api/v1/logs/upload` | 200, 400, 408, 413, 422, 503 | 200, 422 |
| POST | `/api/v1/tasks/{task_id}/stop` | 200, 202, 422 | 200, 422 |

## Явные ответы 204

Локальный [AST scan](../../2026-11-01/check_http_statuses.py) сопоставил 197 из 201 операций `docs/openapi.json`. Следующие handlers явно возвращают `204`, отсутствующий и в документации, и в runtime-схеме.

| Метод | Путь | Явный ответ |
| --- | --- | --- |
| DELETE | `/api/v1/auth/api-keys/{key_id}` | [auth](../../../../backend/api/v1/auth/router.py#L425) |
| DELETE | `/api/v1/auth/mfa` | [auth](../../../../backend/api/v1/auth/router.py#L348) |
| POST | `/api/v1/device-events/{event_id}/processed` | [device events](../../../../backend/api/v1/device_events/router.py#L121) |
| DELETE | `/api/v1/game-accounts/{account_id}` | [game accounts](../../../../backend/api/v1/game_accounts/router.py#L225) |
| POST | `/api/v1/logs/upload` | [logs, условная ветка](../../../../backend/api/v1/logs/router.py#L150) |
| DELETE | `/api/v1/logs/{device_id}` | [logs](../../../../backend/api/v1/logs/router.py#L196) |
| DELETE | `/api/v1/n8n/webhooks/{webhook_id}` | [n8n](../../../../backend/api/v1/n8n/router.py#L122) |
| DELETE | `/api/v1/updates/{release_id}` | [updates](../../../../backend/api/v1/updates/router.py#L586) |
| PATCH | `/api/v1/users/{user_id}/deactivate` | [users](../../../../backend/api/v1/users/router.py#L239) |
