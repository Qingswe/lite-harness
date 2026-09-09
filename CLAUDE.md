# CLAUDE.md

本仓库面向长时运行的 coding agent 工作流，典型目标平台为 Unity（C#）。保留无法可靠重建的信息，让工作可验证、可续接；文档与工具按任务需要使用。

## 选择工作方式

默认采用**日常协作**：围绕用户目标直接实现、验证和提交，不要求 OpenSpec、active change、`current.json` 或独立 Evaluator。

接续已有 OpenSpec change，或用户要求自动循环、队列调度和自动归档时，采用**自动循环**，遵守 `.harness/program.md`。复杂、跨模块或兼容性变更先明确设计与验收，可以选择 OpenSpec；复杂本身不强制启动循环。

工作方式按任务选择，不新增全仓库模式开关。存在空 `current.json` 或安装了 OpenSpec 不表示所有任务都进入循环。已有 change 的实现和评估必须继续走原流程；不得用日常协作绕过验收、角色隔离或未完成的人工步骤。

## 信息来源

- 工作规则：本文件；`AGENTS.md` 只引用。
- 实际实现：代码和测试。产品约定在项目现有产品文档维护唯一版本，并从 `ARCHITECTURE.md` 链接；采用 OpenSpec 的行为以 `openspec/specs/` 为规格来源。
- 当前结构：`ARCHITECTURE.md` / `docs/architecture/`；长期决策与经验：`docs/adr/` / `docs/knowledge/`。
- 日常验证：优先引用测试输出、CI、提交或 PR，需持久保留的本地日志放 `.harness/evidence/`。不重复抄录已有证据。
- 自动循环状态：`.harness/current.json`；变更设计与任务：`openspec/changes/<id>/`；验证事实：对应 `verification.json`，CLI 与看板共用 `harness_verification.py`，不得另写解析器。

## 日常协作

1. 运行 `pwd`、`git status --short` 和 `git log --oneline -5`，确认目录、已有修改与近期工作。保护用户的未提交修改。
2. 读取相关架构、产品约定；接续未完成工作时读取对应交接并核对适用提交。有相关 OpenSpec change 时先确认其范围，属于该 change 的工作转入自动循环流程。
3. 明确目标、范围和验证方式。小任务直接执行；行为有歧义或影响较大时，先用现有设计文档澄清，避免重复创建多套计划。
4. 按风险执行构建、测试或人工验收。需要真实 Unity 验证时运行 `./init.sh`（Windows：`.\init.ps1`），按需设置 `UNITY_PROJECT_DIR`、`RUN_UNITY_IMPORT`、`RUN_EDITMODE` 或 `RUN_PLAYMODE`。环境探针通过不等于功能验证通过。
5. 报告完成行为、实际验证结果、未验证部分和必要限制，安全后提交本次改动，Unity `.meta` 随资源提交。

不要求每轮更新 `current.json`、勾任务表或填写验证 JSON。只有未完成且需要跨会话继续时，才写 `.harness/checkpoints/<topic>/<YYYYMMDD>[-<label>].md`，省略可从 Git 恢复的文件清单。记录目标约束、关键决定、失败尝试、阻塞、下一步和证据链接；完成后标记已完成，长期结论移入对应文档，不重写历史检查点。

架构、长期质量、债务、风险或可复用经验变化时更新相关文档，见 `docs/quality/README.md`；普通任务无需逐项填写“无需更新”。

## 自动循环

1. 用 `.harness/scripts/harness status`（Windows：`harness.ps1 status`）恢复 active、候选、上下文与漂移状态，不再手工拼接重复信息。状态错误先查明并修复。
2. 读取 active change 的 `proposal.md`、`tasks.md`、`program.md` 和相关架构；评分卡仅读取相关领域。没有 active 时可规划候选，进入该循环的实现前必须选定唯一 active change。
3. 状态通过现有 CLI / dashboard 维护；候选集合由 `harness sync-candidates` 派生。执行者仅补充工具不能推导的上下文、generator 身份、阻塞与恢复信息，不手抄派生进度。普通会话不修改这些循环状态。
4. 使用 `harness next` 调度；Generator 与 Evaluator 必须由不同 agent、不同模型承担，写入边界和身份断言以 `.harness/program.md` 为准。Generator 不写验证终态或评估证据，Evaluator 不改实现或任务。
5. 实现和自动验证完成但待人工的 change 可释放 active，保留可恢复的 gated 上下文，不阻塞下一个 change。候选阶段仅做调研和设计规划。
6. Evaluator 按约定运行真实验证，通过 `harness check` 记录 `verification.json` 与证据；预筛质量文档，按触发结果更新长期记录。按需生成 checkpoint。
7. `harness ready` 计算就绪度，`harness lint` 运行归档门槛；七项判据和归档回滚要求见 `.harness/program.md`。就绪后 `harness autoclose` 通过完整 close 自动归档，保留全部门槛，不直接调用 `openspec archive`。未作答的人工步骤继续阻塞。

自动循环使用 OpenSpec、`current.json`、`program.md` 与 `verification.json`。保留它们的 schema、身份、依赖和回滚语义；能力索引由 `sync-feature-index.py` 派生，人工仅维护 overrides。普通任务无须维护这些可选工具的数据文件。

## 两种方式共同遵守

- 不因代码已写、任务已勾选就声称完成；不伪造验证或代答人工步骤。
- 不悄悄修改需求、放宽验收或削弱测试。相关基础验证失败时先查原因，无关失败说明影响，避免扩大修复范围。
- 只推进授权范围。日常任务与循环任务不得冲突；并行执行用隔离工作区或明确文件边界，active 状态不是 Git 并发锁。
- 优先使用持久文件恢复已确认事实；用户的新指令优先，并把会影响后续工作的决定落到对应文档。
