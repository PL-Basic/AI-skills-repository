# Wifi_Manager Backend Context

## Goal

Build a home WiFi management system where clients connect to an ESP32 SoftAP/gateway, pass through a captive portal/login flow, and are controlled by Java microservices. The backend validates users and policies, receives ESP32 heartbeat/traffic events, sends MQTT allow/kick/block commands, and exposes admin data for users, ESP32 nodes, sessions, blacklist, traffic, rules, alerts, audits, and GPS consent locations.

## Paths

- Backend: `F:\MyProject\testOb\Wifi_Manager`
- Frontend: `F:\MyProject\vue\wifi`
- Memory files: `C:\Users\45333\Desktop\memory`
- MySQL business DB: `wifi` on `localhost:3306`
- Nacos: `D:\java\tool\nacos`, console `localhost:8848/nacos`

## Current Module State

- `gateway-service` port 8080: routes `/auth/**`, `/users/**`, `/devices/**`, `/blacklist/**`, `/sessions/**`, `/traffic/**`, `/admin/**`, `/rules/**`, `/alerts/**`, `/audits/**`, `/locations/**`; performs JWT filtering and passes `X-User-Id`, `X-User-Name`, `X-User-Role`.
- `auth-service` port 8381: login/register and JWT issuing. It currently keeps direct DB user logic after a bad auth/user decoupling attempt was reverted.
- `user-service` port 8382: user paging/detail/update/status/logical delete/purge/stats/avatar support. There may be uncommitted work in `UserManageServiceImpl.java`; inspect before editing.
- `device-service` port 8383: ESP32 nodes, blacklist, sessions, traffic logs, MQTT allow/kick, heartbeat, traffic ingestion, async monitor evaluation, and action dispatch.
- `monitor-service` port 8384: access rules, alert events, audit query, GPS client location reporting, WebSocket alerts.
- `admin-service` port 8385: BFF over user/device/monitor. It should aggregate and proxy; do not make it a persistence service.

## Database And SQL

Core tables include `sys_user`, `t_esp32_node`, `t_session`, `t_mac_blacklist`, `t_traffic_log`, `t_audit_log`, `t_alert_event`, `t_access_rule`, and `t_client_location`.

DDL style preference: `snake_case`, comments, `create_time`, `update_time`, and `del_flag` when logical deletion applies. MyBatis-Plus `@TableLogic` is used where appropriate.

`t_access_rule` lives in `sql/monitor-service.sql`. `t_alert_event` historically lived in `sql/device-service.sql`; do not assume SQL file ownership always matches service ownership.

## MQTT Contract

Commands:

- `wifi/device/{deviceCode}/cmd/allow`
- `wifi/device/{deviceCode}/cmd/kick`
- `wifi/device/{deviceCode}/cmd/disconnect-mac`
- `wifi/device/{deviceCode}/cmd/block-traffic`

Events:

- `wifi/device/{deviceCode}/event/status`
- `wifi/device/{deviceCode}/event/traffic`

The newer client/traffic-level actions intentionally do not reuse node-level `cmd/kick`.

## Monitor Flow

`device-service` persists traffic and session byte totals, then asynchronously calls monitor evaluation. `monitor-service` matches enabled rules from `AccessRuleCache`, applies a cooldown key of `mac|ruleCode`, writes `t_alert_event`, and broadcasts new alerts over `/ws/alerts`.

Action execution is in `device-service`: pick the strongest action by smallest `actionType`; `1` sends `disconnect-mac`, `2` sends `block-traffic`, `3` is alert-only. Failures must be logged and swallowed.

## Audit

Auditing is opt-in via `wifi-audit-spring-boot-starter` and `@EnableAuditing`. `@Audited` writes after successful business execution and should not break business logic on audit failures.

Operator resolution order: explicit annotation `operatorName`, request header `X-User-Name`, fallback `system`.

Known audited actions include user/device/blacklist/rule/alert/auth/monitor action events. Login is intentionally not audited because it is frequent.

## Known Traps

- Read actual POMs and code before suggesting architecture. The project already has many modules and established conventions.
- `auth-service` and `gateway-service` must share the same `jwt.secret`.
- Nacos with MySQL 8.0.11 may require `allowPublicKeyRetrieval=true` because Nacos uses `127.0.0.1`; business services using `localhost` may not need it.
- Spring 5.2 does not have `setAllowedOriginPatterns`; use compatible WebSocket CORS APIs.
- Same-bean calls bypass Spring AOP and `@Async`.
- Backend integration tests can fail simply because MySQL service is stopped.
- ESP32 firmware is not yet consuming every newer backend command, so backend command publish may be ahead of hardware.

## Recent Progress Snapshot

As of the memory and git inspection around 2026-05-27:

- Backend latest visible commits include fixes for avatar backendization, registration/login precedence, self destructive user action guards, login type restrictions, ignored uploaded avatars, and bug fixes.
- Backend worktree had an uncommitted change in `user-service/src/main/java/com/plagod/service/impl/UserManageServiceImpl.java`.
- Full system compile had previously passed after common module split and GPS work.
- GPS backend is implemented: `POST /locations/report`, `GET /locations`, admin BFF `GET /admin/locations`, gateway route, and dashboard test table.
