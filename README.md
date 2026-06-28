# Ai技能库合集

这是一个自建的 Codex skills 仓库，用来沉淀我在真实项目协作、代码学习和工程实践中反复使用的 AI 工作流。

这些 skill 不是简单的提示词合集，而是给 Codex 的“任务上下文和行动规范”：它们告诉 AI 在特定场景下应该先看什么、怎么判断、按什么顺序推进、哪些项目约定必须遵守，以及什么时候应该教学、什么时候应该直接修复问题。

## 当前包含的 Skills

| Skill | 作用 | 适合场景 |
| --- | --- | --- |
| `learn-by-building` | 用“边做边学”的方式训练学习者从需求到实现的判断能力 | 学习编码、拆解需求、设计实现路线、写伪代码、代码审查 |
| `wifi-manager-backend` | 辅助维护 Wifi_Manager Java 微服务后端 | Spring Boot/Spring Cloud、Nacos、JWT、MyBatis-Plus、MQTT、审计、告警、定位等后端任务 |
| `wifi-manager-frontend` | 辅助维护 Wifi Vue 管理端前端 | Vue 3、Vite、路由权限、会话同步、仪表盘、WebSocket 告警、GPS 可视化等前端任务 |

## 重点 Skill：learn-by-building

`learn-by-building` 是这个仓库中最重要的通用学习型 skill。它的目标不是让 AI 直接把完整代码贴给学习者，而是帮助学习者建立真正的工程实现能力。

很多学习场景的问题不在于“不会复制代码”，而在于：

- 不知道如何从需求判断要改哪些层；
- 不知道 Controller、Service、DTO、Entity、Mapper、前端页面之间如何分工；
- 不知道什么时候应该新增、修改、删除、查询或做状态切换；
- 不知道自己的实现路线是否符合当前项目结构；
- 看得懂代码片段，但独立实现时无法下手。

`learn-by-building` 针对的正是这个断点。它把学习过程拆成一条更符合工程学习规律的路径：

1. 先让学习者用自己的话复述需求；
2. 再让学习者设计实现路线；
3. 然后审查路线是否符合当前项目结构；
4. 接着写伪代码，明确业务顺序；
5. 最后再给参考实现；
6. 让学习者对比自己的版本和参考版本；
7. 再进入真实编码、审查、编译和测试。

这种方式更慢一点，但更扎实。它训练的是“看到需求后知道怎么拆、怎么落到代码结构里”的能力，而不是只训练复制答案。

## learn-by-building 的核心理念

### 先理解项目，再讲实现

它要求 AI 在提出方案前先阅读真实仓库，确认模块职责、已有约定和附近代码。这样可以避免泛泛而谈，也能避免把一个并不适合当前项目的“标准答案”强行套进去。

### 先训练判断，再提供代码

在学习场景中，它不会默认直接给出大段完整代码，而是先引导学习者回答：

- 这个需求解决什么问题？
- 谁会使用它？
- 输入是什么？
- 输出是什么？
- 后端需要改 Controller 吗？
- 需要新增 DTO 吗？
- Service 应该负责什么？
- 数据表或实体是否要变？
- 前端页面或 API wrapper 是否要改？

这些问题看起来基础，但它们正是从“看懂代码”走向“能自己写功能”的关键。

### 用工程分层训练思维

`learn-by-building` 会把常见需求映射成工程结构，例如：

- 新增功能：CreateDTO、Controller POST、Service create、Mapper insert、前端表单；
- 修改功能：UpdateDTO、Controller PUT、Service 检查存在后更新、前端编辑弹窗；
- 删除功能：Controller DELETE、Service 检查存在、按项目约定决定逻辑删除或物理删除；
- 查询列表：QueryDTO 或查询参数、分页结果、查询条件构造、前端表格；
- 状态切换：PATCH/PUT 动作接口、只更新状态字段、必要时记录操作人和时间；
- 指令下发：Controller action endpoint、Service 构造命令、MQTT 或外部系统调用。

这些不是死板模板，而是学习脚手架。最终仍然要以真实仓库的结构为准。

## 使用示例

可以直接在 Codex 对话中这样使用：

```text
Use $learn-by-building to help me implement user blacklist management.
先不要直接给完整代码，先带我拆需求、设计实现路线和伪代码。
```

或者：

```text
Use $learn-by-building to review my implementation route for adding an alert rule page.
请指出我分层设计里哪里不合理。
```

也可以用于代码审查：

```text
Use $learn-by-building to audit this feature implementation.
重点看需求理解、分层、边界条件、异常处理和测试缺口。
```

## 项目专用 Skills

### wifi-manager-backend

这个 skill 面向 `Wifi_Manager` 后端微服务项目。它记录了项目的模块边界、技术栈、常见陷阱和验证命令，要求 AI 在改后端前先检查真实代码和 POM，而不是凭空建议包结构或架构调整。

它特别适合以下任务：

- Spring Boot/Spring Cloud 微服务开发；
- Gateway、JWT、Nacos 配置与排查；
- 用户、设备、会话、黑名单、流量、规则、告警、审计、定位等业务模块；
- MQTT 指令下发和 ESP32 交互；
- MyBatis-Plus 实体、DTO、Mapper、SQL 维护；
- 后端架构边界审查。

### wifi-manager-frontend

这个 skill 面向 Wifi Vue 管理端。它记录了前端会话模型、路由权限、接口封装、WebSocket、GPS 可视化和管理端页面的约定，帮助 AI 在改页面前先理解现有结构。

它特别适合以下任务：

- Vue 3 / Vite 页面开发；
- 登录、注册、个人资料和角色跳转；
- JWT 会话和多标签页状态同步；
- 管理端用户、设备、规则、告警、审计页面；
- WebSocket 告警提示；
- 与后端 Gateway 和各微服务联调。

## 安装方式

将需要的 skill 文件夹复制到 Codex 的 skills 目录即可。

Windows 默认路径：

```powershell
$env:USERPROFILE\.codex\skills
```

macOS / Linux 默认路径：

```bash
~/.codex/skills
```

示例：

```powershell
Copy-Item -Recurse .\learn-by-building "$env:USERPROFILE\.codex\skills\"
Copy-Item -Recurse .\wifi-manager-backend "$env:USERPROFILE\.codex\skills\"
Copy-Item -Recurse .\wifi-manager-frontend "$env:USERPROFILE\.codex\skills\"
```

安装后，在 Codex 对话中通过 `$skill-name` 触发，例如：

```text
Use $learn-by-building to help me learn how to implement this requirement.
```

## 目录结构

每个 skill 通常包含：

```text
skill-name/
  SKILL.md
  agents/
    openai.yaml
  references/
    extra-context.md
```

- `SKILL.md`：核心说明，告诉 Codex 什么时候使用这个 skill，以及使用时应该遵守的流程；
- `agents/openai.yaml`：展示名称、简短描述和默认提示词；
- `references/`：按需加载的项目背景、约定、接口或上下文资料。

## 设计原则

这个仓库里的 skills 遵循几个原则：

- 让 AI 先理解真实项目，再给建议；
- 把工程约定写下来，减少重复解释；
- 把学习过程设计成“理解、设计、伪代码、实现、对比、审查”；
- 不鼓励无上下文的大段代码复制；
- 对项目专用 skill 保持边界清晰，对通用 skill 保持可迁移。

## 适合谁

这个仓库适合：

- 想用 AI 辅助学习编程，但不想只复制答案的人；
- 想把自己的项目经验沉淀成 AI 协作规范的人；
- 需要长期维护同一个复杂项目，希望 AI 每次都能记住关键约定的人；
- 想训练“需求到代码”能力的学习者。

其中，`learn-by-building` 可以脱离具体项目独立使用；`wifi-manager-backend` 和 `wifi-manager-frontend` 则更适合配合对应项目仓库使用。
