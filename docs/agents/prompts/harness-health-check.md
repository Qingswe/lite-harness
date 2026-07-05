# Harness Health Check Prompt

用途：每日检查 lite-harness 工作流是否处于可恢复、可验证、可审查状态。

建议频率：每日，或每次长期后台任务启动前。

默认权限：只读；允许写 `.harness/evidence/agent-gc/<DATE>/harness-health-check/report.md`。

## Codex Prompt

```text
你正在为 <PROJECT_NAME> 执行 Harness Health Check。目标是发现 workflow 骨架是否健康，不要实现产品功能，不要修复无关代码。

请遵守以下规则：

1. 先读取 `AGENTS.md` / `CLAUDE.md`。
2. 运行并记录：
   - `pwd`
   - `git status --short`
   - `git log --oneline -5`
   - `openspec list`
   - Unix/macOS/Linux: `./init.sh`
   - Windows: `.\init.ps1`
3. 读取 `.harness/current.json`，检查：
   - `active_change` 是否唯一。
   - `candidate_changes` 是否与 active change 冲突。
   - `current_task`、`blockers`、`next_action` 是否能让下一轮无猜测恢复。
   - `last_updated` 是否明显过期。
4. 如果存在 active change，读取：
   - `openspec/changes/<active_change>/proposal.md`
   - `tasks.md`
   - `quality-contract.md`
   - `verification.md`
   - `human-checks.md`
5. 检查这些异常：
   - OpenSpec 未初始化或 `openspec list` 失败。
   - active change 缺必需文件。
   - `tasks.md` 有已勾选项但 `verification.md` 没有对应证据。
   - `human-checks.md` 有 pending/failed，但 active slot 已被错误释放。
   - `.harness/current.json` 指向不存在的 change。
   - `.harness/current.json` 被暂存进 Git，且不是有意更新模板状态。
6. 不要直接运行 `openspec archive`。
7. 默认不要修改文件。若发现可机械修复的问题，只在报告里给出建议；除非用户明确允许，否则不自动修复。

输出：

- 写入 `.harness/evidence/agent-gc/<DATE>/harness-health-check/report.md`。
- 报告包含：提交 SHA、命令结果摘要、发现列表、严重级别、建议下一步。
- 如果没有问题，明确写 `Status: healthy`。
```
