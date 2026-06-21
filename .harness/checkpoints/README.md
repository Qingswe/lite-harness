# Checkpoints

这里存放会话结束、上下文压缩前或重要状态切换时生成的恢复摘要。

推荐路径：

```text
.harness/checkpoints/<change>/<YYYYMMDD-HHMMSS>.md
```

checkpoint 只记录下一轮恢复所需的信息：

- 当前 active OpenSpec change
- 正在推进的 task
- 已真实运行的验证
- 未解决 blocker
- 下一步最小可执行动作
- 重要但尚未验证的假设

不要在这里复制 `openspec/specs/`、`proposal.md` 或 `tasks.md` 的完整内容。
