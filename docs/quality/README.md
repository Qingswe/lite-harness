# Quality Docs Update Policy

`docs/quality/` 记录长期质量状态，不记录单次变更的完整验证日志。单次变更的命令、结果和证据仍写在 `openspec/changes/<change>/verification.md`。

每次 `harness close <change>` 前，必须在当前 change 的 `verification.md` 中记录一次“质量文档判断”：哪些质量文档需要更新，哪些不需要，以及理由。

## 更新触发条件

### `scorecard.md`

当本次变更让某个产品领域或架构层的长期状态发生明显变化时更新：

- 正确性、测试覆盖、可维护性、文档完整性或风险等级发生变化。
- 原本不稳定的路径经过验证后变稳定。
- 新增功能扩大了未验证面积或人工检查负担。
- 重构改变了 agent 理解代码的难度。

不要因为一次普通通过的任务就机械调整评分；评分必须能引用验证证据或明确的架构变化。

### `tech-debt.md`

当本次变更留下了不会立即解决、但未来必须追踪的问题时更新：

- 为了保持范围纪律而延期的修复。
- 临时 workaround、重复代码、测试缺口或迁移债务。
- 当前 change 不能解决，但后续 change 需要接手的问题。

只在问题会跨越当前 change 存活时写入；一次性失败或已修复问题留在 `verification.md` 即可。

### `risks.md`

当问题可能影响多个变更、发布质量或核心系统可靠性时更新：

- 存档兼容、资源 GUID、Prefab 引用、序列化迁移等 Unity 长期风险。
- 核心战斗、经济、存档、关卡加载等高影响路径。
- 性能预算、平台差异、人工验收不可替代的风险。
- 反复出现但尚未形成明确修复计划的问题。

### `docs/knowledge/changes/`

每个已 close 的 change 都建议生成一条短摘要，引用：

- `openspec/archive/<change>/`
- 关键验证证据
- 影响到的 capability
- 后续风险或无需更新质量文档的理由

### `docs/knowledge/pitfalls/`

当踩到可复现、容易重复发生的 Unity 或 agent 工作流问题时更新，例如 Prefab Missing Script、`.meta` 漏提交、PlayMode 与 EditMode 行为差异、环境探针误判。

## 不更新的情况

如果本次变更没有改变长期质量状态，也要在 `verification.md` 的“质量文档判断”中写明：

- `scorecard.md`：无需更新，原因是……
- `tech-debt.md`：无需更新，原因是……
- `risks.md`：无需更新，原因是……
- `docs/knowledge/changes/`：已更新或暂不需要，原因是……

这能让“没有更新 docs”成为可审查的结论，而不是遗漏。
