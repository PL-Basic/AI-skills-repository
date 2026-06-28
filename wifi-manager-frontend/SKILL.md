---
name: wifi-manager-frontend
description: Work on the Wifi Vue frontend at F:\MyProject\vue\wifi. Use when Codex is asked to inspect, debug, extend, style, or test the Vue/Vite admin dashboard, login/register/profile flows, JWT session behavior, role-based routing, API wrappers, WebSocket alerts, GPS visualization, user/device/rule/alert/audit pages, or integration with the Wifi_Manager Java backend.
---

# Wifi Manager Frontend

## First Move

Inspect the live Vue repo before editing. Read `git status`, `package.json`, the relevant view/component/API file, and `src/utils/session.js` or router code when the task touches login, roles, redirects, or tab synchronization.

For current frontend progress, endpoint conventions, and test focus, read `references/frontend-context.md` when the task touches dashboard behavior, session model, backend integration, or next-step planning.

## Project Shape

- Frontend repo: `F:\MyProject\vue\wifi`.
- Stack: Vue 3, Vite, Vue Router, Axios.
- API base: Axios uses `/api`; Vite proxies `/api` to backend gateway `http://localhost:8080`.
- WebSocket dev proxy: `/ws` to `ws://localhost:8384`.
- Main surfaces: login, register, profile, dashboard, GPS, users, approvals, devices, blacklist, sessions, traffic, rules, alerts, audits.

## Frontend Rules

- Preserve the single browser identity model: token/user/role live in `localStorage`, tabs in one browser context share one logged-in account, and storage events synchronize login/logout/profile changes.
- Do not reintroduce separate accounts in different tabs of the same browser profile. Use another browser/profile/incognito for parallel accounts.
- Keep role redirects consistent: ordinary users go to `/profile`; admins and super admins go to `/dashboard`.
- Treat role `0` as a valid super-admin value; never use fallback expressions that overwrite `0`.
- Route and view behavior must react to session changes across tabs.
- Keep admin operations guarded in UI: ordinary admins must not edit/delete admins or super admins; super admin controls approval and stronger user actions.
- Prefer visible in-modal success/error feedback for modal saves instead of closing immediately when the user needs confirmation.
- Use existing styling direction: dynamic starfield plus glass-like admin/login visuals, but prioritize dense operational UI over marketing-style pages.
- Use existing API wrapper patterns in `src/api/*.js` and shared state helpers in `src/utils/session.js`.

## Integration Notes

- Backend gateway is expected at `localhost:8080`.
- Monitor WebSocket alert endpoint is `/ws/alerts` through Vite dev proxy; direct backend is `ws://localhost:8384/ws/alerts`.
- Avatar upload backend endpoint exists: `POST /users/{userId}/avatar`, multipart, 2MB, jpg/png/gif/webp, returns `/users/avatars/{fileName}` and updates `avatar`.
- Alert/audit detail endpoints exist: `GET /admin/alerts/{id}` and `GET /admin/audits/{id}`.

## Verification

Use:

```powershell
npm.cmd run build
```

For behavior changes, test at least the relevant browser flow manually: login redirects, multi-tab login/logout/profile sync, admin modal save feedback, WebSocket alert toast, or endpoint error handling.

## Communication

Reply in Chinese by default. Be direct about whether an issue is frontend-only or depends on backend service state.

When teaching implementation, do not drip-feed one tiny line at a time, and do not dump a large code block without explanation. Provide the whole relevant code for the current step, split into logical sections, and explain why each section exists before asking the user to write it. Keep this teaching style for backend, frontend, and embedded work.
