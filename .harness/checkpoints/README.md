# Checkpoints

这里存放会话结束、上下文压缩前或重要状态切换时生成的恢复摘要。

路径规则（唯一形式，不接受平铺文件名）：

```text
.harness/checkpoints/<change>/<YYYYMMDD>[-<label>].md
```

- 目录名必须是 canonical change id，不携带摘要或阶段说明。
- 文件名里的 `<label>` 才用来区分同一天的多个 checkpoint，例如
  `20260714-yarn-tmp-remediation.md`。
- 不要用 `<change>-<摘要>-<日期>.md` 这类平铺命名：change id 与摘要混在一起后，
  任何按 id 定位 checkpoint 的脚本都会失配。参见
  `docs/knowledge/pitfalls/canonical-harness-identifiers-must-not-carry-summaries.md`。

checkpoint 只记录下一轮恢复所需的信息：

- 当前 active OpenSpec change
- 正在推进的 task
- 已真实运行的验证
- 未解决 blocker
- 下一步最小可执行动作
- 重要但尚未验证的假设

不要在这里复制 `openspec/specs/`、`proposal.md` 或 `tasks.md` 的完整内容。
