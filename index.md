# 模板使用指南（Unity 版）

这套模板专为 Unity（C# + Unity Test Framework）项目准备。它的目标不是增加文档数量，而是建立一条清晰的权威来源链：

```text
项目原则 -> 当前产品事实 -> 变更设计 -> 执行状态 -> 验证证据 -> 知识归档
```

核心规则：一种信息只能有一个权威来源，其他文件只能引用它，不能复制它。

> 前提：本机已通过 Unity Hub 安装并激活目标 Unity 版本，项目已添加 Unity Test Framework 包，并有 EditMode / PlayMode 测试 assembly。

## 权威来源

| 层级 | 权威来源 | 职责 |
| --- | --- | --- |
| 项目原则 | `AGENTS.md` / `CLAUDE.md` | agent 工作规则、完成门槛、收尾纪律 |
| 当前产品事实 | `openspec/specs/` | 已建立的用户可观察行为 |
| 变更设计 | `openspec/changes/<change>/` | 候选或 active change 的 proposal、spec 增量、design、tasks、质量契约 |
| 执行状态 | `.harness/current.json` | 唯一 active 执行 change、候选 change、当前 task、blocker、next action |
| 验证证据 | 对应 change 的 `verification.md`、`human-checks.md`、`.harness/evidence/` | 实际跑过的验证与人工检查 |
| 知识归档 | `openspec/archive/`、`docs/adr/`、`docs/knowledge/` | 已完成变更、长期决策、踩坑记录 |

## 推荐目录

```text
/
├── AGENTS.md
├── CLAUDE.md
├── ARCHITECTURE.md
├── init.ps1
├── init.sh
├── openspec/
├── .harness/
│   ├── current.json
│   ├── feature-index.json
│   ├── checkpoints/
│   ├── evidence/
│   ├── templates/
│   └── scripts/
└── docs/
    ├── architecture/
    ├── adr/
    ├── quality/
    └── knowledge/
```

## 怎么开始

1. 在项目根目录运行 `openspec init`，初始化 OpenSpec。
2. 根据项目实际情况填写 `.harness/current.json`、`.harness/feature-index.json` 和 `ARCHITECTURE.md`。
3. 为第一个候选变更创建 `openspec/changes/<change>/`，至少包含 `proposal.md`、`tasks.md` 和 spec 增量草案。
4. 候选 change 可以有多个；它们只做调研、proposal、design、spec 草案和 tasks 规划。
5. 选定唯一 active change 后，从 `.harness/templates/` 复制 `quality-contract.md`、`verification.md`、`human-checks.md`，并把 `.harness/current.json.active_change` 指向它。
6. 运行平台入口做环境探针：Windows 用 `.\init.ps1`，Unix/macOS/Linux 用 `./init.sh`。Unity 导入、编译、EditMode 和 PlayMode 验证按 active change 的 `quality-contract.md` 显式要求执行。

## OpenSpec 与 Harness 分工

OpenSpec 负责 WHAT：产品行为、变更提案、任务清单、归档后的当前事实。

Harness 负责运行态和证据：当前恢复点、checkpoint、质量契约、验证证据、人工检查、收尾命令。

工作循环：

1. `openspec list` 查看所有候选和 active change。
2. 候选阶段可以并行调研多个 change，但只更新各自的 proposal、design、spec 草案、tasks 草案、风险和参考资料。
3. 晋升前确认候选 change 范围不与当前 active change 冲突，任务和验证路径清晰。
4. 把唯一 active change 写入 `.harness/current.json.active_change`，读取它的 `proposal.md`、`tasks.md`、`quality-contract.md`。
5. 实现一条 task。
6. 运行验证并写入 `verification.md`。
7. 需要人工确认的内容写入 `human-checks.md`。
8. 更新 `.harness/current.json` 和 checkpoint。
9. 实现和自动验证完成后，如仍待人工检查，可先释放 `active_change`，让下一个 change 进入 active 执行槽。
10. 人工检查通过或 waived 后，由人工明确指定 change，再运行 `.harness/scripts/harness close <change>`。

不要直接运行 `openspec archive <change>`；归档必须经过 `harness close` 的检查。

## 关键文件

### `.harness/current.json`

覆盖式当前恢复点。只保留新会话恢复所需的最小信息：唯一 active 执行 change（`active_change`）、候选 change、当前 task、最后验证 task、working files、blocker、next action、dirty assumptions、last checkpoint。

`active_change` 是唯一执行槽；它仍保留这个字段名以兼容现有脚本和 agent 习惯，但语义是 active execution change。候选 change 不进入执行槽，不能改实现代码或写最终验证结论。实现和自动验证已完成但仍待人工检查的 change 可以不是 active，它只等待 `human-checks.md` 被人工更新后再 close。

### `.harness/feature-index.json`

能力索引，不是任务管理器。每项只保存 capability 与 OpenSpec spec 的映射、成熟度、质量等级、活跃变更和最近验证提交。

不要在这里写详细验证步骤、证据或 tasks 状态。

### `.harness/templates/`

存放变更级模板：

- `quality-contract.md`：实施前质量要求。
- `verification.md`：实施后真实验证证据。
- `human-checks.md`：Unity 编辑器、Prefab、真机等人工检查。
- `checkpoint.md`：会话恢复摘要。

### `docs/quality/`

长期质量聚合：

- `README.md`：质量文档更新触发条件。
- `scorecard.md`：领域与架构层评分。
- `tech-debt.md`：长期技术债。
- `risks.md`：长期风险。

单次变更的完整测试日志不写进全局质量文档。每次 close 前必须在 `verification.md` 的“质量文档判断”中说明是否更新这些长期文档；如果长期评分、技术债、风险或知识归档被触发，就同步更新对应文件。

### `init.ps1` / `init.sh`

跨平台环境探针。默认只检查当前目录、OpenSpec、Unity 项目结构和 Unity 可执行文件；只有显式设置 `RUN_UNITY_IMPORT`、`RUN_EDITMODE`、`RUN_PLAYMODE` 或 `RUN_START_COMMAND` 时才执行对应 Unity 动作。它不负责归档。

验证与归档请直接使用 `.harness/scripts/harness verify|close <change>`。

### `.harness/scripts/harness`

包装命令：

- `.harness/scripts/harness verify <change>`：校验 OpenSpec、检查变更级质量文件，并运行平台环境探针。
- `.harness/scripts/harness close <change>`：在 verify 通过、tasks 完成、human checks 无 pending/failed，且 `verification.md` 已记录“质量文档判断”后执行 `openspec archive <change>`；close 必须由人工明确指定 change，不要求该 change 仍占用 active 执行槽。

## 收尾检查

每次结束前确认：

- `.harness/current.json` 已更新；已完成但待人工检查的 change 不应继续占用 active 执行槽。
- 必要时已生成 `.harness/checkpoints/<change>/<timestamp>.md`。
- `verification.md` 记录了真实运行的验证。
- `human-checks.md` 中 AI 不能验证的项目没有被假装完成。
- 已按 `docs/quality/README.md` 判断是否需要更新 `scorecard.md`、`tech-debt.md`、`risks.md` 和 `docs/knowledge/`。
- 变更通过人工检查后，只按人工明确指令通过 `harness close` 归档。
- `.meta` 文件与 Unity 资源改动一起提交。

## 暂缓事项

第一版只定义 hook 边界，不强制实现完整 Claude Code hook 系统。等 `.harness/current.json`、`verification.md`、`human-checks.md` 格式稳定后，再实现 `SessionStart`、`PreCompact`、`Stop` 等 hook。
