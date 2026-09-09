# CLAUDE.md

本仓库面向长时运行的 coding agent 工作流，典型目标平台为 Unity（C#）。保留无法可靠重建的信息，让工作可验证、可续接；文档与工具按任务需要使用。

## 选择工作方式

默认采用**日常协作**：围绕用户目标直接实现、验证和提交，不要求 OpenSpec 或独立 Evaluator。

接续已有 OpenSpec change，或用户要求自动循环、队列调度和自动归档时，采用**自动循环**，遵守 `.harness/program.md`。复杂、跨模块或兼容性变更先明确设计与验收，可以选择 OpenSpec；复杂本身不强制启动循环。

工作方式按任务选择，不新增全仓库模式开关。安装了 OpenSpec 不表示所有任务都进入循环。已有 change 的实现和评估必须继续走原流程；不得用日常协作绕过验收、角色隔离或未完成的人工步骤。

## 信息来源

- 工作规则：本文件；`AGENTS.md` 只引用。
- 实际实现：代码和测试。产品约定在项目现有产品文档维护唯一版本，并从 `ARCHITECTURE.md` 链接；采用 OpenSpec 的行为以 `openspec/specs/` 为规格来源。
- 当前结构：`ARCHITECTURE.md` / `docs/architecture/`；长期决策与经验：`docs/adr/` / `docs/knowledge/`。
- 日常验证：优先引用测试输出、CI、提交或 PR，需持久保留的本地日志放 `.harness/evidence/`。不重复抄录已有证据。
- 任务和进度从 `openspec/changes/<id>/tasks.md`、`verification.json` 实时查询，不维护全局状态文件。实现者身份、依赖和明确阻塞放在该 change 的 `program.md` 可选元数据块；格式见模板。CLI 与看板共用解析器。

## 日常协作

1. 运行 `pwd`、`git status --short` 和 `git log --oneline -5`，确认目录、已有修改与近期工作。保护用户的未提交修改。
2. 读取相关架构、产品约定；接续未完成工作时读取对应交接并核对适用提交。有相关 OpenSpec change 时先确认其范围，属于该 change 的工作转入自动循环流程。
3. 明确目标、范围和验证方式。小任务直接执行；行为有歧义或影响较大时，先用现有设计文档澄清，避免重复创建多套计划。
4. 按风险执行构建、测试或人工验收。需要真实 Unity 验证时运行 `./init.sh`（Windows：`.\init.ps1`），按需设置 `UNITY_PROJECT_DIR`、`RUN_UNITY_IMPORT`、`RUN_EDITMODE` 或 `RUN_PLAYMODE`。环境探针通过不等于功能验证通过。
5. 报告完成行为、实际验证结果、未验证部分和必要限制，安全后提交本次改动，Unity `.meta` 随资源提交。

不要求普通任务勾任务表或填写验证 JSON。只有未完成且需要跨会话继续时，才写 `.harness/checkpoints/<topic>/<YYYYMMDD>[-<label>].md`，省略可从 Git 恢复的文件清单。记录目标约束、关键决定、失败尝试、阻塞、下一步和证据链接；完成后标记已完成，长期结论移入对应文档，不重写历史检查点。

架构、长期质量、债务、风险或可复用经验变化时更新相关文档，见 `docs/quality/README.md`；普通任务无需逐项填写“无需更新”。

## 自动循环

1. 用 `openspec list` 或 `.harness/scripts/harness status` 查询现有 change、任务与验证进度。查询不写状态。没有 change 时可先做设计规划，不需要建立执行槽。
2. 读取目标 change 的 `proposal.md`、`tasks.md`、`program.md` 和相关架构；用 `harness next <change> --json` 查询下一步。目标作为参数传入，不持久化 active 或候选列表。
3. Generator 与 Evaluator 使用不同 agent、不同模型。身份记录在目标 `program.md` 的 `harness-metadata.generated_by`，依赖和明确阻塞也只在该 change 记录。进度、当前任务、工作文件和阶段不手动复制。
4. Generator 写实现和 tasks；Evaluator 按 `.harness/program.md` 运行真实验证，用 `harness check` 记录结论和证据，不改实现。未完成的人工步骤继续阻塞，无需占用或释放执行槽。
5. 质量文档仍按循环契约预筛；按需写交接。`harness ready` / `lint` 计算和校验完整门槛，就绪后由 `autoclose` / `close` 建立回滚点并归档，不直接调用 `openspec archive`。归档后查询自然不再列出该 change，无需同步或清理状态副本。

能力索引继续由 `sync-feature-index.py` 派生，人工仅维护 overrides。旧状态文件的迁移见 `index.md`，不再创建或维护 `.harness/current.json`。

## 两种方式共同遵守

- 不因代码已写、任务已勾选就声称完成；不伪造验证或代答人工步骤。
- 不悄悄修改需求、放宽验收或削弱测试。相关基础验证失败时先查原因，无关失败说明影响，避免扩大修复范围。
- 只推进授权范围。日常任务与循环任务不得冲突；并行执行用隔离工作区或明确文件边界，查询结果不是 Git 并发锁。
- 优先使用持久文件恢复已确认事实；用户的新指令优先，并把会影响后续工作的决定落到对应文档。
