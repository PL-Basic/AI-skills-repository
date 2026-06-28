# Wifi Frontend Context

## Paths And Stack

- Frontend repo: `F:\MyProject\vue\wifi`
- Backend repo: `F:\MyProject\testOb\Wifi_Manager`
- Stack: Vue 3, Vite, Vue Router, Axios
- Build command: `npm.cmd run build`

## Current Behavior

- `/api` proxy points to backend gateway `http://localhost:8080`.
- `/ws` proxy points to monitor service WebSocket `ws://localhost:8384`.
- Axios request interceptor attaches JWT and checks token expiry before requests.
- 401 clears login state and redirects to `/login`.
- 403 stores a permission message for display.
- Login/register pages use a dynamic starfield plus glass-like style.
- Dashboard uses the same visual direction and contains operational tabs/pages for overview, profile, GPS, user management, approvals, device nodes, blacklist, sessions, traffic, rules, alerts, and audits.

## Session Model

The frontend intentionally uses a single browser identity model:

- Token/user/role are stored in `localStorage`.
- All tabs in the same browser profile share the same account.
- `authEvent` storage events synchronize login, logout, and profile changes across tabs.
- Login pages should detect an existing session and redirect instead of allowing a stale tab to overwrite the current account.
- Multiple accounts at the same time require another browser/profile/incognito.

Important role detail: super admin role is `0`; use nullish checks rather than `||` fallbacks.

## Completed Surfaces

- Login role redirect: ordinary users to `/profile`, admins/super admins to `/dashboard`.
- Root redirect based on current role.
- Ordinary profile editing: nickname, email, phone, avatar URL/data URL, location table and GPS visualization.
- Admin dashboard role-specific display: super admin sees super-admin console and approvals; ordinary admin does not see approval entry.
- User management: paging, edit modal, role constraints, logical delete, super-admin physical delete, admin physical delete approval flow, local avatar preview.
- Approvals: status mapping and approve/reject.
- Rules: create, edit, delete, enable/disable using backend 0/1 DTO contract.
- Blacklist: add/remove.
- Alerts: list, handle alert with current user ID, detail drawer, WebSocket toast.
- Audits: detail drawer.
- Devices: field alignment with backend `name/ip/currentClients/maxClients/lastHeartbeat`, details, allow, kick.
- Tables use a shared `StateBlock` for loading/empty state.
- GPS visualization projects coordinates, track line, latest point, accuracy circle, bounds, and latest location details. It intentionally reserves an offline/self-developed algorithm map area rather than third-party maps.

## Known Next Work

- Switch avatar UI from data URL/URL editing to backend multipart endpoint `POST /users/{userId}/avatar`; surface backend upload errors.
- Switch alert/audit detail drawers to `GET /admin/alerts/{id}` and `GET /admin/audits/{id}` where needed.
- Continue business/end-to-end testing for blacklist add/remove, session state, device allow/kick, and ESP32/MQTT behavior.
- Keep testing multi-tab login/logout/profile synchronization.
- GPS algorithm map area is currently a UI reserve; later integrate self-developed map/path/location algorithm output.

## Backend Dependencies

- Gateway: `localhost:8080`
- Monitor service for WebSocket: `localhost:8384`
- Some frontend behavior depends on backend state and services being up: MySQL, Nacos, gateway, auth, user, admin, device, monitor.
- There has been a backend companion fix around clearing old empty-string `avatar` / `email` values to `NULL` in `UserManageServiceImpl.java`; inspect backend status if frontend clearing behavior seems wrong.

## Git Snapshot

As of inspection around 2026-05-27:

- Latest frontend commit: `379785c Standardize frontend session behavior`
- Frontend worktree: clean
- Recent frontend commits covered admin edge cases, login mode split, self-action guards, password confirmation feedback, backend avatars/detail endpoints, GPS map reserve, and initial implementation.
