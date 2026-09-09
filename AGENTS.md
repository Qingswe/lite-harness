# AGENTS.md

这个仓库面向长时运行的 coding agent 工作流，目标平台是 Unity（C#）。目标不是尽快产出代码，而是让每一轮会话结束后，下一轮仍然能无猜测地继续。

## 规则在哪里

**完整的 agent 工作规则以根目录 `CLAUDE.md` 为唯一权威源**，适用于所有 coding agent，不限于 Claude Code。开工前必须读它，内容包括：

- 权威来源链与"一种信息只能有一个权威来源"原则
- 固定工作循环（`pwd` → `harness status` → 读 active change 的设计与任务 → 架构与质量文档 → 按契约决定环境探针）
- 工作规则：唯一 active 执行槽、候选 change 的边界、证据纪律、归档必须经 `harness close`
- 必需文件清单
- 完成门槛与结束前的收尾步骤

本文件不复制这些条目。若两者出现分歧，以 `CLAUDE.md` 为准，并把分歧当作待修的漂移处理。

## 起步

```bash
pwd
.harness/scripts/harness status
```

其余步骤见 `CLAUDE.md` 的「固定工作循环」。
