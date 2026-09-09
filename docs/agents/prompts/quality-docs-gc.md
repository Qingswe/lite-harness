# Quality Docs GC Prompt

用途：定期检查并更新长期质量文档，让质量等级、技术债和风险记录不漂移。

建议频率：每日或每周。

默认权限：允许修改 `docs/quality/`、`docs/knowledge/` 和 `.harness/evidence/agent-gc/`；不允许改产品代码。

## Codex Prompt

```text
你正在为 <PROJECT_NAME> 执行 Quality Docs GC。目标是更新长期质量状态，不要实现产品功能，不要扩大范围。

请遵守以下规则：

1. 读取 `AGENTS.md` / `CLAUDE.md`、`docs/quality/README.md`、`docs/quality/scorecard.md`、`docs/quality/tech-debt.md`、`docs/quality/risks.md`。
2. 运行并记录：
   - `pwd`
   - `git status --short`
   - `git log --oneline -5`
   - `openspec list`
   - `./init.sh` 或 `.\init.ps1`
3. 检查 OpenSpec archive 和 active/candidate changes：
   - 已 close 的 change 是否缺 `docs/knowledge/changes/` 摘要。
   - `verification.json` 的 `quality_docs` 是否缺 `prescreen_run`，或被触发的条目缺人工理由。
     预筛只对**触发**举证；未触发的条目沉默即结论，不要求补写说明。
   - `scorecard.md` 的评级是否能引用证据。
   - `tech-debt.md` 是否有无来源、无建议处理、长期未更新的 open 项。
   - `risks.md` 是否有无缓解方式、无上次更新时间、影响范围过宽但没有 owner 的项。
4. 只有在能引用证据时，才更新 `scorecard.md`；更新必须遵守 `docs/quality/README.md` 的「评分卡写法约束」——单元格 ≤ 120 字符，日期条目写入 `docs/quality/scorecard-history.md` 而不是 `scorecard.md`。
5. 技术债和风险可以新增、关闭或改状态，但必须写明来源：
   - OpenSpec change
   - 验证报告
   - 扫描报告
   - 人工确认
6. 不要因为一次普通测试通过就机械提高评分。
7. 不要直接修改产品代码。
8. 不要直接运行 `openspec archive`。

输出：

- 写入 `.harness/evidence/agent-gc/<DATE>/quality-docs-gc/report.md`。
- 如有文档修改，创建分支 `codex/gc-quality-docs-<DATE>`。
- PR 描述必须列出每个质量文档改动对应的证据路径。
- 如果发现需要产品修复的问题，不要修代码；创建或建议 OpenSpec candidate change。
```
