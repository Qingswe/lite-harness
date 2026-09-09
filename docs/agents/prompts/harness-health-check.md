# Harness Health Check Prompt

用途：按需检查项目入口、交接与证据是否可恢复。默认只读，允许写下述扫描报告。

## Codex Prompt

```text
为 <PROJECT_NAME> 执行 Harness Health Check，不实现产品功能或修复无关代码。

1. 读取 AGENTS.md / CLAUDE.md，运行 pwd、git status --short、git log --oneline -5。
2. 检查相关项目入口、文档链接与未完成工作的交接。只有需要 Unity 验证时才运行 init.sh / init.ps1。
3. 日常协作不要求 OpenSpec、current 或 active。缺少它们、空执行槽或闲置模板日期旧本身不是故障，不要自动初始化或重置状态。
4. 若存在 OpenSpec change 或用户要求检查自动循环，运行 harness status 和 harness ready，使用共享状态投影检查漂移与就绪度；状态错误报告出来，不自动修复。存在非空 current 指向缺失 change 时同样检查，不把它误认为未启用循环。
5. 对已有 change 检查设计、program、verification.json 与真实证据；记录已释放但缺少可恢复上下文、身份冲突、人工 phase 比计算就绪度更宽松等问题。待人工 change 释放 active 且保留恢复信息是健康状态。
6. 本扫描不执行 close / autoclose，不代答人工步骤；自动归档交由已授权循环按 .harness/program.md 执行，不直接 openspec archive。
7. 写入 .harness/evidence/agent-gc/<DATE>/harness-health-check/report.md，包含提交 SHA、实际命令结果、发现、影响与建议。没有问题时写 Status: healthy。
```
