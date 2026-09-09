# Background Codex Tasks

这份文档说明如何把 `docs/agents/prompts/` 中的 Prompt 实装为周期性 Codex 后台任务。它保持平台中立：无论使用 Codex Web、Codex CLI、GitHub Actions、内部调度器，任务边界和输出契约都应该一致。

## 核心模型

后台任务分三类：

| 类型 | 目标 | 是否改代码 | 典型输出 |
| --- | --- | --- | --- |
| Scan | 发现偏差、过期文档、残留风险 | 否 | 报告、issue、candidate change |
| Update | 更新质量等级或长期质量记录 | 可改文档 | `docs/quality/*`、knowledge 摘要 |
| Refactor | 针对明确问题发起小 PR | 可改代码 | 小型 PR、验证记录、证据 |

不要把所有任务都做成 Refactor。大多数后台 Codex 任务应该先是 Scan，只有证据稳定、风险低、范围小的问题才进入 Refactor。

## 推荐频率

| 任务 | 频率 | 触发方式 | 备注 |
| --- | --- | --- | --- |
| Harness Health Check | 每日 | 定时 + 手动 | 最先启用，发现流程骨架是否坏掉 |
| Quality Docs GC | 每日或每周 | 定时 | 可直接改质量文档，但必须引用证据 |
| Architecture Drift Scan | 每周 | 定时 | 默认只报告，不直接改代码 |
| Agent Residue Scan | 每日或每周 | 定时 | 可开小 PR 清理明显残留 |
| Refactor PR Candidate | 每周或按需 | 由扫描报告触发 | 只处理一个窄问题 |
| Unity Asset Integrity | 每周、发布前 | 定时 + 发布前 | 需要真实 Unity 项目和可用批处理环境 |

## 标准任务设置

每个定时 Codex 任务都应该配置这些输入：

- 工作目录：目标项目根目录。
- 基础指令：遵守 `AGENTS.md` / `CLAUDE.md`，先读取 `.harness/current.json`，运行 `openspec list` 和平台探针。
- Prompt：复制 `docs/agents/prompts/<task>.md` 中的完整 Prompt。
- 输出目录：`.harness/evidence/agent-gc/<YYYY-MM-DD>/<task>/`。
- 分支策略：需要改文件时使用 `codex/gc-<task>-<YYYYMMDD>`。
- PR 策略：自动 PR 默认 draft；只有低风险文档修正或机械清理才可标 ready。

## 推荐流水线

### 每日

1. 运行 Harness Health Check。
2. 运行 Agent Residue Scan。
3. 如果有低风险残留，生成一个小型 draft PR。
4. 如果发现流程或质量文档问题，记录报告并通知人工。

### 每周

1. 运行 Quality Docs GC。
2. 运行 Architecture Drift Scan。
3. 从扫描报告中挑选一个最小重构候选。
4. 运行 Refactor PR Candidate。

### 发布前

1. 运行 Harness Health Check。
2. 运行 Quality Docs GC。
3. 运行 Unity Asset Integrity。
4. 人工作答 `verification.json` 中 `role: human` 的步骤与高风险项。

## 输出约定

报告文件建议使用：

```text
.harness/evidence/agent-gc/<YYYY-MM-DD>/<task>/
├── report.md
├── commands.txt
├── findings.json
└── screenshots-or-unity-logs/
```

`report.md` 至少包含：

- 运行日期和提交 SHA。
- 读取了哪些权威来源。
- 执行了哪些命令。
- 发现的问题和严重级别。
- 是否修改文件。
- 是否创建 PR 或 OpenSpec candidate change。
- 剩余风险和需要人工判断的内容。

## 何时创建 OpenSpec candidate change

满足任一条件时，不要直接发重构 PR，应先创建 candidate change：

- 可能改变产品行为。
- 会修改 `openspec/specs/`。
- 需要新增或削弱 `program.md` 的约束或评估规则。
- 涉及存档、经济、战斗、关卡加载、资源 GUID 或 Prefab 结构。
- 需要人工 Unity 检查才能判断正确性。

## 何时允许小 PR

满足全部条件时，可以由后台 Codex 发起小型 PR：

- 修改范围可以在一个审查会话内读完。
- 不改变产品行为。
- 验证命令明确且已经运行。
- 没有 pending 的人工检查。
- PR 描述引用了扫描报告和证据路径。
