# Agent Automation Docs

这里存放给 Codex 或其他 coding agent 使用的长期自动化说明。后台扫描按授权范围运行，不要求项目启用 OpenSpec；涉及已有 change 时继续遵守其流程。

## 适用场景

这些文档适用于已经采用 lite-harness 的目标项目：

- 需要定期扫描 agent 残留、架构漂移、质量文档过期或 Unity 资源风险。
- 希望 Codex 后台任务能生成小型重构 PR，而不是等技术债积累到一次大清理。
- 希望每次自动化都有明确输出位置、验证证据和人工审查入口。

## 文档结构

```text
docs/agents/
├── README.md
├── background-codex-tasks.md
└── prompts/
    ├── README.md
    ├── harness-health-check.md
    ├── quality-docs-gc.md
    ├── architecture-drift-scan.md
    ├── agent-residue-scan.md
    ├── refactor-pr-candidate.md
    └── unity-asset-integrity.md
```

## 推荐接入顺序

1. 先启用 `harness-health-check`，检查项目入口、交接和证据；仅对已启用的自动循环检查 OpenSpec 与状态。
2. 再启用 `quality-docs-gc`，让 `scorecard.md`、`tech-debt.md`、`risks.md` 不会变成过期摆设。
3. 然后启用 `architecture-drift-scan` 和 `agent-residue-scan`，开始捕捉偏离黄金原则的模式。
4. 最后启用 `refactor-pr-candidate`，只针对已经被扫描任务确认的小范围问题发起 PR。
5. Unity 项目进入真实资源阶段后，再启用 `unity-asset-integrity`。

## 运行原则

- 后台任务默认先产出报告，不直接改产品行为。
- 只有低风险、范围很窄、验证路径清楚的问题，才允许自动创建重构 PR。
- 如果问题超出扫描或小重构授权，先报告并提出设计建议；涉及已有规格或质量契约时，按对应 change 流程处理，不直接扩大实现范围。
- 所有自动化输出都必须写入可审查位置，例如 `.harness/evidence/agent-gc/<date>/`、`docs/quality/` 或新的 OpenSpec change。
- 定时任务不得直接运行 `openspec archive`；归档一律走 `.harness/scripts/harness close <change>`，并由就绪度驱动（见 `.harness/program.md`）。定时任务本身不得代答 `role: human` 步骤。
