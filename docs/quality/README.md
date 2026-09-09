# Quality Docs Update Policy

`docs/quality/` 记录长期质量状态，不记录单次变更的完整验证日志。单次变更的命令、结果和证据仍写在 `openspec/changes/<change>/verification.json`。

每次 `harness close <change>` 前，必须先跑一次机器预筛：

```
python3 .harness/scripts/prescreen-quality-docs.py <change> --write
```

预筛把结果写进 `verification.json` 的 `quality_docs`。**举证责任在脚本一侧**：默认结论是「无需更新」，脚本必须从 diff 证明某条触发了，触发的条目才要求人工写理由。未触发的条目不产出任何说明文字——沉默即未触发。

## 评分卡写法约束

`docs/quality/scorecard.md` 是**当前状态快照**，会被 agent 在会话中按领域读取，因此必须保持紧凑：

- 单个表格单元格**不超过 120 字符**。写不下的细节放进对应 change 的 `verification.json`，单元格只留结论和指针（spec 路径、风险/技术债编号、知识文档）。
- **不要在 `scorecard.md` 里追加按日期的更新记录**。每次评分变化的日期条目、理由和详细证据写进 `docs/quality/scorecard-history.md`，倒序排在最前。
- 两张矩阵的列数必须与表头一致；缺项写 `-`，不要省略分隔符，否则后续列会整体错位。
- 评分变化必须能引用验证证据或明确的架构变化；不要因为一次普通通过的任务就机械调整评分。

## 更新触发条件

下列条件分两类。**机械可判定**的由预筛脚本从 diff 计算，是 `prescreen-quality-docs.py` 的权威来源；**需人工判断**的脚本只提问、不代为结论。

| 文档 | 判定方式 | 机械判据 |
| --- | --- | --- |
| `scorecard.md` | 机械 | 实现路径与测试路径同时变化；或实现变化而测试未变（未验证面积扩大） |
| `tech-debt.md` | 机械 | diff 新增 `TODO` / `FIXME` / `HACK` / `XXX` / `临时` / `workaround` 标记 |
| `risks.md` | 机械 | 触及序列化格式、存档 schema、Prefab、shader、渲染管线（与风险等级下限同一组判据） |
| `docs/knowledge/changes/` | 机械 | 每个 close 的 change 恒触发 |
| `docs/adr/` | 人工 | 是否值得为本次技术选择立一条 ADR |
| `docs/knowledge/pitfalls/` | 人工 | 本轮是否踩到了可复现、容易重复发生的坑 |

下面各节说明每条判据背后的意图；改动判据时必须同步改 `prescreen-quality-docs.py`，两者不得漂移。

### `scorecard.md`

更新时同时遵守上面的「评分卡写法约束」。当本次变更让某个产品领域或架构层的长期状态发生明显变化时更新：

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

只在问题会跨越当前 change 存活时写入；一次性失败或已修复问题留在 `verification.json` 即可。

### `risks.md`

当问题可能影响多个变更、发布质量或核心系统可靠性时更新：

- 存档兼容、资源 GUID、Prefab 引用、序列化迁移等 Unity 长期风险。
- 核心战斗、经济、存档、关卡加载等高影响路径。
- 性能预算、平台差异、人工验收不可替代的风险。
- 反复出现但尚未形成明确修复计划的问题。

### `docs/knowledge/changes/`

每个已 close 的 change 都建议生成一条短摘要，引用：

- `openspec/changes/archive/<change>/`
- 关键验证证据
- 影响到的 capability
- 后续风险或无需更新质量文档的理由

### `docs/knowledge/pitfalls/`

当踩到可复现、容易重复发生的 Unity 或 agent 工作流问题时更新，例如 Prefab Missing Script、`.meta` 漏提交、PlayMode 与 EditMode 行为差异、环境探针误判。

## 不更新的情况

**不需要逐条撰写「无需更新，原因是……」。** 未被预筛触发的条目不产出说明文字。

「没有更新 docs」仍然是可审查的结论，但审查对象换了：过去审查的是人写的辩护词（实测 6 条判断全是 `not-needed`，填写它们不需要判断力），现在审查的是 `verification.json` 里 `quality_docs.prescreen_run` 这一次真实的预筛运行。预筛没跑过会被 `harness lint` 拦住；被触发却没写理由也会被拦住。
