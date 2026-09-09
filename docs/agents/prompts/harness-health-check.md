# Harness Health Check Prompt

用途：按需检查项目入口、交接与证据是否可恢复。默认只读，允许写下述扫描报告。

## Codex Prompt

```text
为 <PROJECT_NAME> 执行 Harness Health Check，不实现产品功能或修复无关代码。

1. 读取 AGENTS.md / CLAUDE.md，运行 pwd、git status --short、git log --oneline -5。
2. 检查相关项目入口、文档链接与未完成工作的交接。只有需要 Unity 验证时才运行 init.sh / init.ps1。
3. 日常协作不要求 OpenSpec。未初始化本身不是故障，不要自动初始化或创建状态副本。
4. 若存在 OpenSpec change 或用户要求检查自动循环，运行 harness status 和 harness ready，直接查询任务与就绪度；状态错误报告出来，不自动修复。遗留 current 只按 index.md 检查是否有未迁移的重要信息，不把它当运行状态。
5. 对已有 change 检查设计、program、verification.json 与真实证据；检查身份冲突、缺失证据、依赖和明确 blocker。待人工状态从未作答步骤推导，无需维护执行槽。
6. 本扫描不执行 close / autoclose，不代答人工步骤；自动归档交由已授权循环按 .harness/program.md 执行，不直接 openspec archive。
7. 写入 .harness/evidence/agent-gc/<DATE>/harness-health-check/report.md，包含提交 SHA、实际命令结果、发现、影响与建议。没有问题时写 Status: healthy。
```
