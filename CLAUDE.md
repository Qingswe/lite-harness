# CLAUDE.md

你正在一个为长时实现工作设计的 Unity（C#）仓库中工作。优先保证可靠完成、跨会话连续性和显式验证，而不是表面速度。

## 权威来源链

一种信息只能有一个权威来源，其他文件只能引用它，不能复制它：

1. 项目原则：`AGENTS.md` / `CLAUDE.md`
2. 当前产品事实：`openspec/specs/`
3. 变更设计：`openspec/changes/<id>/proposal.md`、`design.md`、`specs/`
4. 执行状态：`.harness/current.json` 中的唯一 active 执行槽、候选 change 与恢复点
5. 验证证据：对应 change 的 `verification.json`、`.harness/evidence/`
6. 知识归档：`openspec/changes/archive/`、`docs/adr/`、`docs/knowledge/`

## 固定工作循环

每轮会话开始时：

1. 运行 `pwd`，确认当前在正确的仓库根目录。
2. 运行 `.harness/scripts/harness status`（Windows 用 `.\.harness\scripts\harness.ps1 status`）。它一次给出 active 执行槽、候选 change 与 lifecycle phase、blocker、next action、任务进度、证据数量、漂移告警和最近提交——不要再手工分别读 `.harness/current.json`、跑 `openspec list` 和 `git log` 去拼同一份信息。若它以非零码退出（漂移或状态错误），先修状态再继续。
3. 读取当前 active change 的 `proposal.md`、`tasks.md`、`program.md`。若没有 active change，可以创建或继续多个候选 change 的调研、proposal 和 plan，也可以等待人工检查完成后按指令 close 已完成 change；进入实现前必须先选定唯一 active change。
4. 读取相关 `ARCHITECTURE.md` 与 `docs/architecture/`；在 `docs/quality/scorecard.md` 中只读取与当前 change 领域相关的评分行，不要整份读取。需要追溯某次评分变化时再查 `docs/quality/scorecard-history.md`。
5. 需要真实 Unity 验证时才运行平台入口做环境探针：Windows 用 `.\init.ps1`，Unix/macOS/Linux 用 `./init.sh`。入口脚本从仓库根定位实际 Unity 项目（仓库根或默认 `UnityProject/`，可用 `UNITY_PROJECT_DIR` 覆盖）。是否需要探针由当前 change 的 `program.md` 与验证记录共同决定，`harness verify` 会自动判断。

然后只围绕这个 active change 工作，逐条推进 `tasks.md`，直到该变更实现和自动验证完成、被释放出 active 执行槽，或被明确记录为 blocked。候选 change 可以并存，但只能处于调研、proposal、design、spec 草案和 tasks 规划阶段。

如果环境探针或质量契约要求的基础验证一开始就失败，先修基础状态，不要在坏的起点上继续叠新功能。

## 规则

- `openspec/changes/` 下可有多个候选 change，只做调研、proposal、design、spec 草案和 tasks 规划。
- 同一时间只有一个 active 执行 change：`.harness/current.json.active_change` 是唯一执行槽，只有它能进行实现、改 `openspec/specs/`、写本轮自动验证证据。
- 已完成实现与自动验证但仍等待人工检查的 change，可以从 `active_change` 释放出来，保留在 `openspec/changes/<id>/` 中等待人工处理，不阻塞下一个 active change。
- 候选 change 晋升前先确认范围不与当前 active change 冲突，再更新 `active_change` 后逐条推进它的 `tasks.md`。
- 没有可运行证据时，不要声称完成；不要因为“代码已经写了”就勾掉任务。
- 不要通过偷改 `tasks.md` 勾选或重写需求来隐藏未完成工作。
- 不要为了“看起来完成”而删除或削弱测试，也不要在实现过程中悄悄改弱验证规则。
- 除非是为了消除当前 blocker 的窄范围修复，否则不要把工作扩大到其他变更。
- 不要直接运行 `openspec archive <id>`；归档一律通过 `.harness/scripts/harness close <id>`。
- 归档由就绪度驱动：七项判据全部成立时自动执行 close，不需要人工逐个确认归档动作。取消的是归档动作的确认，不是人工步骤本身——`verification.json` 中任何 `role: human` 且未作答的步骤都会让就绪度为假。
- close 前必须先建立回滚点 `harness/pre-close/<id>`；建不出回滚点时必须中止归档。
- 实现与评估必须由不同角色、不同模型承担，边界见 `.harness/program.md`。同一次提交不得既改实现又把验证步骤置为终态。
- 质量文档判断由预筛脚本从 diff 计算，默认「无需更新」；只有被触发的条目才需要人工写理由，不再逐条撰写「无需更新」说明。触发规则仍以 `docs/quality/README.md` 为准。
- 以仓库内文件作为唯一事实来源，不依赖聊天记录恢复状态。

## 必需文件

- `openspec/` — 产品事实、变更设计、任务和归档的事实来源。
- `.harness/current.json` — 当前恢复点。
- `.harness/feature-index.json` — 能力索引，不是任务管理器；骨架由 `.harness/scripts/sync-feature-index.py` 从 `openspec/specs/` 派生，人工只维护 `overrides`。
- `.harness/program.md` — 循环宪法：角色边界、归档策略、回滚规则与预算。客户端中立，与各客户端的 agent 定义冲突时以它为准。
- `.harness/scripts/harness_verification.py` — 验证记录的唯一解析实现，CLI 与 dashboard 共用。禁止第二份。
- `.harness/templates/` — checkpoint、program 与 verification 模板。
- `docs/quality/README.md` 与 `docs/quality/scorecard.md` — 质量文档更新规则与长期评分卡。
- `init.ps1` / `init.sh` — 跨平台环境探针；不再默认强制执行完整 Unity 测试。

## 完成门槛

一个变更只有在以下条件都满足后才能归档：

归档就绪度由以下七项共同计算，全部成立才自动归档。人工写入的 phase 只能收紧不能放宽：声称可归档但计算判定未就绪时，采信计算结果并报告是哪一项判据。

- `tasks.md` 全部勾选，且目标行为确实已实现。
- `openspec validate <id> --strict` 通过。
- `verification.json` 全部步骤为 `passed` 或 `waived`，`waived` 均有说明。
- 步骤引用的每个证据路径真实存在。
- `program.md` 的每条评估规则至少被一个已通过或已豁免的步骤覆盖。
- 质量文档预筛已运行，被触发的条目均有人工理由。
- 角色隔离校验通过。

就绪度只驱动触发；`harness close` 仍执行完整门槛断言，就绪度误报时它是最后一道。
用 `.harness/scripts/harness ready` 查看现在可归档哪些、其余各差什么；用 `harness lint <id>` 随时跑与 close 相同的门槛。

## 结束前

1. 更新 `.harness/current.json`。
2. 需要交接时从 `.harness/templates/checkpoint.md` 生成 checkpoint。
3. 把验证结果写入对应 change 的 `verification.json`（用 `harness check <id> <step> <status>`，格式由命令保证）；需要人阅读时用 `harness render <id>`。
4. 按 `docs/quality/README.md` 判断并更新长期质量、技术债、风险或知识归档文档。
5. 就绪度七项判据全部成立时由 `.harness/scripts/harness autoclose` 自动归档，不需要人工逐个指令；仍然不要直接运行 `openspec archive`。带 `role: human` 未作答步骤的 change 到不了就绪，会停在待人工。
6. 记录仍然损坏或未验证的内容，以及仍未解决的风险或 blocker。
7. 在仓库可安全恢复后，用清晰的提交信息提交（注意 `.meta` 文件与改动一起提交）。
