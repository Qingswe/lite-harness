# 模板使用指南（Unity 版）

这套模板专为 Unity（C# + Unity Test Framework）项目准备。它的目标不是增加文档数量，而是建立一条清晰的权威来源链：

```text
项目原则 -> 当前产品事实 -> 变更设计 -> 执行状态 -> 验证证据 -> 知识归档
```

分工：**OpenSpec 负责 WHAT**（产品行为、变更提案、任务清单、归档后的当前事实）；**Harness 负责运行态和证据**（当前恢复点、checkpoint、质量契约、验证证据、人工检查、收尾命令）。

本文件只说明**每个文件是什么、放什么**。工作规则、权威来源链、工作循环、完成门槛和收尾步骤都以根目录 `CLAUDE.md` 为唯一权威源，这里不复制。

> 前提：本机已通过 Unity Hub 安装并激活目标 Unity 版本，项目已添加 Unity Test Framework 包，并有 EditMode / PlayMode 测试 assembly。

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
    ├── agents/
    ├── quality/
    └── knowledge/
```

## 初始化

1. 在项目根目录运行 `openspec init`，初始化 OpenSpec。
2. 根据项目实际情况填写 `.harness/current.json` 和 `ARCHITECTURE.md`。
3. 为第一个候选变更创建 `openspec/changes/<change>/`，至少包含 `proposal.md`、`tasks.md` 和 spec 增量草案。
4. 选定 active change 后，从 `.harness/templates/` 复制 `quality-contract.md`、`verification.md`、`human-checks.md`。

日常工作循环见 `CLAUDE.md`。

## 关键文件

### `.harness/current.json`

覆盖式当前恢复点。只保留新会话恢复所需的最小信息：唯一 active 执行 change（`active_change`）、候选 change、当前 task、最后验证 task、working files、blocker、next action、dirty assumptions、last checkpoint。

`active_change` 是唯一执行槽；它仍保留这个字段名以兼容现有脚本和 agent 习惯，但语义是 active execution change。候选 change 不进入执行槽，不能改实现代码或写最终验证结论。实现和自动验证已完成但仍待人工检查的 change 可以不是 active，它只等待 `human-checks.md` 被人工更新后再 close。

### `.harness/feature-index.json`

能力索引，不是任务管理器。每项只保存 capability 与 OpenSpec spec 的映射、成熟度、质量等级、活跃变更和最近验证提交。

骨架由 `.harness/scripts/sync-feature-index.py` 从 `openspec/specs/` 派生（`--check` 只校验是否同步）；人工只维护 `overrides` 中的 `title`、`domain`、`maturity`、`quality` 和 `last_verified_commit`。不要手工编辑 `features` 数组。

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

单次变更的完整测试日志不写进全局质量文档；触发条件与「质量文档判断」的写法见 `docs/quality/README.md`。

### `init.ps1` / `init.sh`

跨平台环境探针。默认只检查当前目录、OpenSpec、Unity 项目结构（仓库根或默认 `UnityProject/`，可用 `UNITY_PROJECT_DIR` 覆盖）和 Unity 可执行文件；只有显式设置 `RUN_UNITY_IMPORT`、`RUN_EDITMODE`、`RUN_PLAYMODE` 或 `RUN_START_COMMAND` 时才执行对应 Unity 动作。它不负责归档。

### `.harness/scripts/harness`

包装命令：

- `harness status [--json]`：一次输出会话恢复所需的执行状态——active 槽、候选 change 与 lifecycle phase、blocker、next action、任务进度、证据数量、漂移告警和最近提交。漂移或状态错误时以非零码退出。
- `harness sync-candidates`：按 `openspec/changes/` 的实际内容重写候选集合。候选成员关系不由人工维护，per-change context 原样保留。
- `harness verify <change>`：校验 OpenSpec、检查变更级质量文件，并运行平台环境探针。
- `harness close <change> [--skip-specs]`：在 verify 通过、tasks 完成、human checks 无 pending/failed，且 `verification.md` 已记录「质量文档判断」后执行 `openspec archive`，随后自动收尾 `.harness/current.json`。`--skip-specs` 用于 infra、工具或纯文档变更。
- `harness reset-current`：清空 `.harness/current.json`，只保留可恢复的空执行槽。

Windows 用 `.\.harness\scripts\harness.ps1`，选项名为 `-SkipSpecs` 与 `-Json`。

### `.harness/scripts/harness_state.py`

状态层的唯一实现：current.json 的 schema 定义、schema 校验、lifecycle 推导、证据列举、漂移检测与状态写回。`.harness/dashboard/server.py` 与两个平台的 `harness` 脚本都调用它，不各自重写。

### `.harness/scripts/sync-feature-index.py`

从 `openspec/specs/` 重新生成 `.harness/feature-index.json` 骨架；`--check` 只检查是否已同步，不写文件。

## 后台 Codex 任务

如果项目希望像垃圾回收一样持续偿还 agent 残留和架构漂移，使用 `docs/agents/` 中的后台任务 Prompt。应用方式见 `docs/agents/background-codex-tasks.md`。

定时任务不得绕过 OpenSpec：如果发现的问题会改变产品行为、规格事实或质量契约，应先创建 candidate change，而不是直接让后台任务改代码。

## 暂缓事项

第一版只定义 hook 边界，不强制实现完整 Claude Code hook 系统。等 `.harness/current.json`、`verification.md`、`human-checks.md` 格式稳定后，再实现 `SessionStart`、`PreCompact`、`Stop` 等 hook。
