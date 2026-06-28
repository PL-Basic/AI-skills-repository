---
name: wifi-manager-backend
description: Work on the Wifi_Manager backend Java microservice system. Use when Codex is asked to inspect, design, debug, extend, or test the backend at F:\MyProject\testOb\Wifi_Manager, including Spring Boot/Spring Cloud modules, Gateway/Nacos/JWT, auth/user/device/admin/monitor services, MQTT command and traffic flows, audit/alert/location features, MyBatis-Plus entities and SQL, or ESP32-facing backend contracts.
---

# Wifi Manager Backend

## First Move

Inspect the live repository before proposing architecture, package placement, dependencies, entities, DTOs, mappers, or implementation steps. Read the root `pom.xml`, relevant module `pom.xml`, current `git status`, and nearby implemented source files before designing changes. The user strongly prefers recommendations grounded in the existing module layout.

When teaching implementation, first identify the current project convention, then judge it:

- Preserve good existing structure and explain why it fits.
- Call out weak or risky structure only after seeing the actual code, and explain why a new structure is better for this project.
- Do not give generic package-placement advice when the repository already has a clear convention.
- Be intellectually honest: do not agree with the user automatically, but do not override established project style without evidence.

For current project facts and known traps, read `references/backend-context.md` when the task touches architecture, module boundaries, database schema, MQTT topics, Nacos, audit, monitor rules, or next-step planning.

## Project Shape

- Backend repo: `F:\MyProject\testOb\Wifi_Manager`.
- Main modules: `wifi-common-api`, `wifi-common-mybatis`, `wifi-audit-spring-boot-starter`, `wifi-gen`, `gateway-service`, `auth-service`, `user-service`, `device-service`, `admin-service`, `monitor-service`.
- Package style: `com.plagod`.
- Runtime stack: Java 8, Spring Boot 2.3.12, Spring Cloud Hoxton.SR12, Spring Cloud Alibaba 2.2.7, Nacos 2.2.3, MyBatis-Plus 3.4.3.4, MySQL, Druid, JJWT 0.11.5, Paho MQTT.
- Target system: ESP32 SoftAP/gateway plus Java microservices plus Vue admin UI for a home WiFi management system.

## Backend Rules

- Keep `admin-service` as a BFF. It aggregates downstream services and should not become a direct persistence owner.
- Keep domain ownership clear: user data in `user-service`, device/session/blacklist/traffic ingestion in `device-service`, rules/alerts/audits/locations in `monitor-service`, auth/login/register in `auth-service`, routing/JWT filtering in `gateway-service`.
- Prefer adding query services such as `*QueryService` for read-heavy additions instead of stuffing more reads into command services.
- Put shared DTOs in `wifi-common-api` only when multiple services truly need strong typing. Avoid moving VOs there just because admin BFF proxies them once.
- Use `wifi-common-mybatis` only for persistence-shared entities/configuration, and `wifi-audit-spring-boot-starter` for opt-in auditing.
- For Spring proxy annotations such as `@Async`, `@Transactional`, `@Cacheable`, or `@Audited`, avoid same-bean `this` calls. Extract a separate `@Service` when the proxy must apply.
- Keep monitoring/action failures non-blocking for traffic ingestion. Feign evaluation and MQTT action publish failures should log warnings and not break the main traffic insert/update flow.
- Do not put production admin pages into `admin-service` static resources. Backend `dashboard.html` is a local integration page only and is excluded by the prod profile.

## Verification

Use PowerShell-friendly commands from the backend repo:

```powershell
.\mvnw.cmd compile
.\mvnw.cmd -pl auth-service,user-service,monitor-service -am compile
.\mvnw.cmd -pl admin-service -am compile
```

Before integration testing, check MySQL, Nacos, and service ports. The local environment has had MySQL service failures after disk/reboot events.

## Communication

Reply in Chinese by default. Technical terms may stay in English. The user values high-substance architecture, but expects it after code and POM inspection, not before.

When teaching implementation, do not drip-feed one tiny line at a time, and do not dump a large code block without explanation. Provide the whole relevant code for the current step, split into logical sections, and explain why each section exists before asking the user to write it. Keep this teaching style for backend, frontend, and embedded work.
