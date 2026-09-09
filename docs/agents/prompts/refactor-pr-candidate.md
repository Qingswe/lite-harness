# Refactor PR Candidate Prompt

用途：把扫描报告中一个低风险、范围明确的问题实装成小型 PR。

建议频率：每周，或由扫描报告人工触发。

默认权限：允许改代码和相关测试；必须创建分支和验证证据。只处理一个问题。

## Codex Prompt

```text
你正在为 <PROJECT_NAME> 执行 Refactor PR Candidate。目标是处理一个已经被扫描报告确认的小范围问题，并发起可快速审查的 PR。

输入：

- 扫描报告路径：<SCAN_REPORT_PATH>
- 候选问题 ID：<FINDING_ID>
- 最大范围：<MAX_PR_SCOPE>

请遵守以下规则：

1. 读取 `AGENTS.md` / `CLAUDE.md`、扫描报告、相关 `ARCHITECTURE.md` 或 `docs/adr/`。
2. 运行并记录：
   - `pwd`
   - `git status --short`
   - `git log --oneline -5`
   - 仅涉及已启用的自动循环时运行 `harness status`，不要为扫描初始化 OpenSpec。
   - 需要 Unity 验证时运行 `./init.sh` 或 `.\init.ps1`。
3. 判断是否允许直接 PR：
   - 不改变产品行为。
   - 不修改 `openspec/specs/`。
   - 不削弱验证。
   - 不需要人工 Unity 检查才能判断正确性。
   - 范围能在一个短 PR 中审查。
4. 如果不满足以上条件，停止实现，改为报告并提出设计建议；已有 OpenSpec 范围按 change 流程处理。
5. 创建分支 `codex/gc-refactor-<FINDING_ID>-<DATE>`。
6. 只处理该 finding，不顺手清理其他问题。
7. 修改后运行最小必要验证，并把命令和结果写入：
   `.harness/evidence/agent-gc/<DATE>/refactor-pr-candidate/report.md`
8. 如果修复属于已有 change，转入该 change 流程，遵守角色分离；其他任务也须避免与进行中的工作冲突。
9. 不要直接运行 `openspec archive`。

输出：

- 一个小型 PR。
- PR 描述包含：
  - 解决的问题。
  - 扫描报告路径。
  - 改动文件。
  - 验证命令和结果。
  - 剩余风险。
- 如果没有创建 PR，报告中说明停止原因和建议下一步。
```
