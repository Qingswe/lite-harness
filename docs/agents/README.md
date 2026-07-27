# Agent Automation Docs

这里存放给 Codex 或其他 coding agent 使用的长期自动化说明。目标不是替代 OpenSpec change 流程，而是把“熵与垃圾收集”做成可重复运行的后台任务。

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

1. 先启用 `harness-health-check`，保证 OpenSpec、`.harness/current.json`、初始化探针和 active change 状态可恢复。
2. 再启用 `quality-docs-gc`，让 `scorecard.md`、`tech-debt.md`、`risks.md` 不会变成过期摆设。
3. 然后启用 `architecture-drift-scan` 和 `agent-residue-scan`，开始捕捉偏离黄金原则的模式。
4. 最后启用 `refactor-pr-candidate`，只针对已经被扫描任务确认的小范围问题发起 PR。
5. Unity 项目进入真实资源阶段后，再启用 `unity-asset-integrity`。

## 运行原则

- 后台任务默认先产出报告，不直接改产品行为。
- 只有低风险、范围很窄、验证路径清楚的问题，才允许自动创建重构 PR。
- 如果问题会改变产品行为、规格事实或质量契约，必须先创建 OpenSpec candidate change。
- 所有自动化输出都必须写入可审查位置，例如 `.harness/evidence/agent-gc/<date>/`、`docs/quality/` 或新的 OpenSpec change。
- 定时任务不得直接运行 `openspec archive`；close 仍由人工明确触发 `.harness/scripts/harness close <change>`。
