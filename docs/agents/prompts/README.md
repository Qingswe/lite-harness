# Background Task Prompts

本目录存放可直接复制给 Codex 的后台任务 Prompt。每个 Prompt 都假设目标项目已经采用 lite-harness，并且根目录存在 `AGENTS.md`、`.harness/current.json`、`init.sh` 或 `init.ps1`。

## 使用方式

1. 在目标项目根目录启动 Codex 任务。
2. 复制对应文件中的“Codex Prompt”整段内容。
3. 为任务设置合适频率，参考 `docs/agents/background-codex-tasks.md`。
4. 如果任务会改文件，要求 Codex 使用 `codex/gc-<task>-<date>` 分支，并创建 draft PR。
5. 审查 PR 时优先看报告、验证证据和是否遵守 OpenSpec active change 规则。

## Prompt 变量

复制 Prompt 时可以替换这些变量：

| 变量 | 含义 |
| --- | --- |
| `<PROJECT_NAME>` | 目标项目名 |
| `<DATE>` | 运行日期，建议 `YYYY-MM-DD` |
| `<TASK_NAME>` | 后台任务名 |
| `<MAX_PR_SCOPE>` | 单个 PR 允许的最大范围，例如 `one module or one docs folder` |
| `<UNITY_BATCHMODE_COMMAND>` | 目标项目的 Unity 批处理命令 |

## 权限建议

- Scan 类 Prompt：默认只读，允许写 `.harness/evidence/agent-gc/` 报告。
- Update 类 Prompt：允许改 `docs/quality/` 和 `docs/knowledge/`，但必须引用证据。
- Refactor 类 Prompt：允许改代码，但只能处理一个明确问题，并必须跑验证。
