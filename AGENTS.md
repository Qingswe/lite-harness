# AGENTS.md

这个仓库面向长时运行的 coding agent 工作流，目标平台是 Unity（C#）。目标不是尽快产出代码，而是让每一轮会话结束后，下一轮仍然能无猜测地继续。

## 权威来源链

一种信息只能有一个权威来源，其他文件只能引用它，不能复制它：

1. 项目原则：`AGENTS.md` / `CLAUDE.md`
2. 当前产品事实：`openspec/specs/`
3. 变更设计：`openspec/changes/<id>/proposal.md`、`design.md`、`specs/`
4. 执行状态：`.harness/current.json` 中的唯一执行槽，与正在执行的 `openspec/changes/<id>/tasks.md`
5. 验证证据：执行中 change 的 `verification.md`、`human-checks.md`、`.harness/evidence/`
6. 知识归档：`openspec/archive/`、`docs/adr/`、`docs/knowledge/`

## 开工流程

写代码前先做这些事：

1. 用 `pwd` 确认当前目录。
2. 读取 `.harness/current.json`，确认 `active_change`（唯一执行中 change）、候选 change、当前 task、blocker 和 next action。
3. 运行 `openspec list` 查看变更；读取当前执行中 change 的 `proposal.md`、`tasks.md`、`quality-contract.md`。没有执行中 change 时，可以创建或继续多个候选 change 的调研、proposal 和 plan，但进入实现前必须先选定唯一执行中 change。
4. 用 `git log --oneline -5` 看最近提交。
5. 读取相关 `ARCHITECTURE.md`、`docs/architecture/` 与 `docs/quality/scorecard.md`。
6. 运行平台入口做环境探针：Windows 用 `.\init.ps1`，Unix/macOS/Linux 用 `./init.sh`。真实 Unity 导入、EditMode、PlayMode 验证按当前 change 的 `quality-contract.md` 显式要求执行。

如果环境探针或质量契约要求的基础验证一开始就失败，先修基础状态，不要在坏的起点上继续叠新功能。

## 工作规则

- `openspec/changes/` 下可有多个候选 change，只做调研、proposal、design、spec 草案和 tasks 规划。
- 同一时间只有一个执行中 change：`.harness/current.json.active_change` 是唯一执行槽，只有它能改代码、改 `openspec/specs/`、写验证证据或执行 close。
- 候选 change 晋升前先确认范围不与当前执行 change 冲突，再更新 `active_change`，然后逐条完成它的 `tasks.md`。
- 不要因为“代码已经写了”就勾掉任务或声称完成。
- 除非为了消除当前 blocker 的窄范围修复，否则不要扩大到其他变更。
- 实现过程中不要悄悄改弱验证规则。
- 不要直接运行 `openspec archive <id>`；归档必须通过 `.harness/scripts/harness close <id>`。
- 变更 close 前必须按 `docs/quality/README.md` 在 `verification.md` 记录质量文档判断；需要更新 `scorecard.md`、`tech-debt.md`、`risks.md` 或 `docs/knowledge/` 时，不要跳过。
- 优先依赖仓库里的持久化文件，而不是聊天记录。

## 必需文件

- `openspec/`：产品事实、变更设计、任务和归档的事实来源。
- `.harness/current.json`：当前恢复点。
- `.harness/feature-index.json`：能力索引，不是任务管理器。
- `.harness/templates/`：checkpoint、质量契约、验证和人工检查模板。
- `docs/quality/README.md` 与 `docs/quality/scorecard.md`：质量文档更新规则与长期评分卡。
- `init.ps1` / `init.sh`：跨平台环境探针；不再默认强制执行完整 Unity 测试。

## 完成定义

一个变更只有在以下条件都满足时才算完成、可归档：

- `tasks.md` 全部勾选，目标行为已实现。
- `openspec validate <id> --strict` 通过。
- 要求的自动验证真的跑过，证据记录在 `verification.md` 和 `.harness/evidence/`。
- `human-checks.md` 中必须人工确认的项目已 passed 或明确 waived。
- `verification.md` 已记录“质量文档判断”，并更新所有被触发的长期质量或知识文档。
- `.harness/current.json` 与 checkpoint 已更新。
- 仓库仍然能按标准启动路径重新开始工作。

## 收尾

结束会话前：

1. 更新 `.harness/current.json`。
2. 需要交接时从 `.harness/templates/checkpoint.md` 生成 checkpoint。
3. 把验证结果写入对应 change 的 `verification.md`，人工项写入 `human-checks.md`。
4. 按 `docs/quality/README.md` 判断并更新长期质量、技术债、风险或知识归档文档。
5. 变更完成时运行 `.harness/scripts/harness close <id>`，不要直接 archive。
6. 记录仍未解决的风险或 blocker。
7. 在工作处于安全状态后，用清晰的提交信息提交（注意 `.meta` 文件与改动一起提交）。
