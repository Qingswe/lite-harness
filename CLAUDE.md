# CLAUDE.md

你正在一个为长时实现工作设计的 Unity（C#）仓库中工作。优先保证可靠完成、跨会话连续性和显式验证，而不是表面速度。

## 权威来源链

一种信息只能有一个权威来源，其他文件只能引用它，不能复制它：

1. 项目原则：`AGENTS.md` / `CLAUDE.md`
2. 当前产品事实：`openspec/specs/`
3. 变更设计：`openspec/changes/<id>/proposal.md`、`design.md`、`specs/`
4. 执行状态：`.harness/current.json` 中的唯一 active 执行槽、候选 change 与恢复点
5. 验证证据：对应 change 的 `verification.md`、`human-checks.md`、`.harness/evidence/`
6. 知识归档：`openspec/archive/`、`docs/adr/`、`docs/knowledge/`

## 固定工作循环

每轮会话开始时：

1. 运行 `pwd`，确认当前在正确的仓库根目录。
2. 读取 `.harness/current.json`，确认 `active_change`（唯一 active 执行 change）、候选 change、当前 task、blocker 和 next action。
3. 运行 `openspec list` 查看变更；读取当前 active change 的 `proposal.md`、`tasks.md`、`quality-contract.md`。若没有 active change，可以创建或继续多个候选 change 的调研、proposal 和 plan，也可以等待人工检查完成后按指令 close 已完成 change；进入实现前必须先选定唯一 active change。
4. 用 `git log --oneline -5` 查看最近提交。
5. 读取相关 `ARCHITECTURE.md`、`docs/architecture/` 与 `docs/quality/scorecard.md`。
6. 运行平台入口做环境探针：Windows 用 `.\init.ps1`，Unix/macOS/Linux 用 `./init.sh`。真实 Unity 导入、EditMode、PlayMode 和目标场景启动路径按当前 change 的 `quality-contract.md` 显式要求执行。

然后只围绕这个 active change 工作，逐条推进 `tasks.md`，直到该变更实现和自动验证完成、被释放出 active 执行槽，或被明确记录为 blocked。候选 change 可以并存，但只能处于调研、proposal、design、spec 草案和 tasks 规划阶段。

## 规则

- `openspec/changes/` 下可有多个候选 change，只做调研、proposal、design、spec 草案和 tasks 规划。
- 同一时间只有一个 active 执行 change：`.harness/current.json.active_change` 是唯一执行槽，只有它能进行实现、改 `openspec/specs/`、写本轮自动验证证据。
- 已完成实现与自动验证但仍等待人工检查的 change，可以从 `active_change` 释放出来，保留在 `openspec/changes/<id>/` 中等待人工处理，不阻塞下一个 active change。
- 候选 change 晋升前先确认范围不与当前 active change 冲突，再更新 `active_change` 后逐条推进它的 `tasks.md`。
- 没有可运行证据时，不要声称完成。
- 不要通过偷改 `tasks.md` 勾选或重写需求来隐藏未完成工作。
- 不要为了“看起来完成”而删除或削弱测试。
- 不要直接运行 `openspec archive <id>`；归档必须由人工明确指定 change，并通过 `.harness/scripts/harness close <id>`。
- 变更 close 前必须按 `docs/quality/README.md` 在 `verification.md` 记录质量文档判断；需要更新 `scorecard.md`、`tech-debt.md`、`risks.md` 或 `docs/knowledge/` 时，不要跳过。
- 以仓库内文件作为唯一事实来源，不依赖聊天记录恢复状态。

## 必需文件

- `openspec/` — 产品事实、变更设计、任务和归档的事实来源。
- `.harness/current.json` — 当前恢复点。
- `.harness/feature-index.json` — 能力索引，不是任务管理器。
- `.harness/templates/` — checkpoint、质量契约、验证和人工检查模板。
- `docs/quality/README.md` 与 `docs/quality/scorecard.md` — 质量文档更新规则与长期评分卡。
- `init.ps1` / `init.sh` — 跨平台环境探针；不再默认强制执行完整 Unity 测试。

## 完成门槛

一个变更只有在以下条件都满足后才能归档：

- `tasks.md` 全部勾选。
- `openspec validate <id> --strict` 通过。
- 要求的自动验证真的跑过，证据记录在 `verification.md` 和 `.harness/evidence/`。
- `human-checks.md` 中必须人工确认的项目已 passed 或明确 waived。
- `verification.md` 已记录“质量文档判断”，并更新所有被触发的长期质量或知识文档。
- `.harness/current.json` 与 checkpoint 已更新；若仍待人工检查，应释放 `active_change`，并在 next action 中说明后续 close 条件。

## 结束前

1. 更新 `.harness/current.json`。
2. 需要交接时从 `.harness/templates/checkpoint.md` 生成 checkpoint。
3. 把验证结果写入对应 change 的 `verification.md`，人工项写入 `human-checks.md`。
4. 按 `docs/quality/README.md` 判断并更新长期质量、技术债、风险或知识归档文档。
5. 变更通过人工检查后，按人工明确指令运行 `.harness/scripts/harness close <id>`，不要直接 archive。
6. 记录仍然损坏或未验证的内容。
7. 在仓库可安全恢复后提交（注意 `.meta` 文件与改动一起提交）。
