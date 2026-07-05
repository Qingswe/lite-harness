# Agent Residue Scan Prompt

用途：扫描 Codex 或其他 agent 容易留下的低质量残留，并区分“可机械清理”和“需要设计判断”的问题。

建议频率：每日或每周。

默认权限：只读；允许写 `.harness/evidence/agent-gc/<DATE>/agent-residue-scan/report.md`。低风险问题可按需交给 `refactor-pr-candidate`。

## Codex Prompt

```text
你正在为 <PROJECT_NAME> 执行 Agent Residue Scan。目标是发现 AI 残留，不要进行宽泛重构。

请遵守以下规则：

1. 读取 `AGENTS.md` / `CLAUDE.md`、`ARCHITECTURE.md`、`docs/quality/README.md`。
2. 运行并记录：
   - `pwd`
   - `git status --short`
   - `git log --oneline -5`
   - `openspec list`
   - `./init.sh` 或 `.\init.ps1`
3. 扫描这些残留信号：
   - `TODO`、`FIXME`、`HACK`、`temporary`、`quick fix`、`guess`、`yolo`。
   - 未结构化或临时 `Debug.Log`。
   - 重复 helper、一次性 util、命名模糊的 wrapper。
   - 手写 JSON/dictionary 字段探测，未验证边界。
   - catch 后吞异常或仅打印日志。
   - 测试中硬编码时序、随机 sleep、过宽 mock。
   - 文档中的占位符没有被目标项目替换。
4. 每个发现必须分类：
   - `mechanical-cleanup`：可安全机械清理。
   - `needs-design`：需要 OpenSpec candidate change 或架构判断。
   - `acceptable`：有上下文说明，暂不处理。
5. 不要自动修改代码。
6. 不要把所有关键词命中都当成问题，必须结合上下文判断。

输出：

- 写入 `.harness/evidence/agent-gc/<DATE>/agent-residue-scan/report.md`。
- 报告包含：发现、证据、分类、建议下一步。
- 对 `mechanical-cleanup` 项，给出最多 3 个可交给 `refactor-pr-candidate` 的小 PR 候选。
```
