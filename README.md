# lite-harness

面向长时运行 coding agent 的轻量工作流脚手架。本仓库将 [OpenSpec](https://github.com/Fission-AI/OpenSpec) 的规格与变更管理，与文件驱动的 harness（执行状态、验证证据、质量归档）相结合，使跨会话协作具备可恢复、可验证、可审计的执行纪律。

本仓库以 Unity（C#）为典型应用场景，harness 机制本身与语言无关，可适配其他技术栈。

> 本仓库的工作流参考 [walkinglabs/learn-harness-engineering](https://github.com/walkinglabs/learn-harness-engineering)，在其基础上进行了裁剪与改造。

## 采用方式

将本仓库内容复制到**目标项目的根目录**即可启用工作流。无需单独安装本包，也不依赖特定的包管理器集成。

复制完成后，请在目标项目根目录执行以下步骤：

1. 安装 [OpenSpec CLI](https://github.com/Fission-AI/OpenSpec)，并运行 `openspec init` 完成初始化。
2. 按项目实际情况填写 `ARCHITECTURE.md`、`.harness/current.json` 与 `.harness/feature-index.json`。
3. 参阅 [index.md](index.md) 了解变更创建、执行与归档的完整流程。

## 核心理念

本工作流遵循单一权威来源原则：一种信息只对应一个权威来源，其余文件仅作引用，不得重复维护副本。

```text
项目原则 → 当前产品事实 → 变更设计 → 执行状态 → 验证证据 → 知识归档
```

| 层级 | 权威来源 |
| --- | --- |
| 项目原则 | `AGENTS.md` / `CLAUDE.md` |
| 当前产品事实 | `openspec/specs/` |
| 变更设计 | `openspec/changes/<id>/`（proposal、design、spec 增量、tasks） |
| 执行状态 | `.harness/current.json`（唯一 active 执行槽、候选 change 与恢复点） |
| 验证证据 | 对应 change 的 `verification.md`、`human-checks.md`、`.harness/evidence/` |
| 知识归档 | `openspec/archive/`、`docs/adr/`、`docs/knowledge/` |

**OpenSpec** 负责定义 WHAT（产品行为、变更提案、任务清单、归档事实）；**Harness** 负责管理 HOW（恢复点、checkpoint、质量契约、验证证据、人工检查、收尾命令）。

## 前置依赖

| 依赖 | 用途 | 说明 |
| --- | --- | --- |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) | 规格与变更管理 | 必装；提供 `openspec validate`、`openspec list`、`openspec archive` 等命令 |
| Python 3 | 本地看板（Dashboard） | 仅使用标准库，无需额外安装依赖 |
| Bash / PowerShell | 脚本执行 | 仓库同时提供 `.sh` 与 `.ps1` 入口 |

OpenSpec 安装示例：

```bash
npm install -g @fission-ai/openspec@latest
openspec init
```

## 工作循环

每轮 agent 会话建议按以下顺序恢复上下文：

1. 确认当前工作目录为项目根目录。
2. 读取 `.harness/current.json`，确认 `active_change`、候选 change、当前 task、blocker 与 next action。
3. 运行 `openspec list` 查看变更列表；读取 active change 的 `proposal.md`、`tasks.md`、`quality-contract.md`。
4. 查阅 `git log --oneline -5` 了解近期提交。
5. 读取相关 `ARCHITECTURE.md`、`docs/architecture/` 与 `docs/quality/scorecard.md`。
6. 运行 `init.ps1`（Windows）或 `init.sh`（Unix / macOS / Linux）执行环境探针。

随后仅围绕当前 active change 逐条推进 `tasks.md`，直至实现和自动验证完成、释放 active 执行槽，或被明确记录为 blocked。

### 执行规则

- `openspec/changes/` 下可并存多个候选 change，但候选阶段仅做调研、proposal、design、spec 草案与 tasks 规划。
- 同一时间仅允许一个 active 执行 change：`.harness/current.json` 中的 `active_change` 为唯一执行槽；仅该 change 可进行实现、更新 `openspec/specs/`、写入本轮自动验证证据。
- 实现和自动验证已完成但仍等待人工检查的 change，可以从 active 执行槽释放出来，待人工在 dashboard 中处理 `human-checks.md` 后再按明确指令 close。
- 无运行证据时不得标记任务完成；不得通过修改 `tasks.md` 勾选状态或削弱测试来掩盖未完成工作。
- 变更归档须由人工明确指定 change，并通过 `.harness/scripts/harness close <id>` 执行，不得直接调用 `openspec archive`。

完整规则见 [AGENTS.md](AGENTS.md) 与 [CLAUDE.md](CLAUDE.md)。

## Harness 命令

```bash
.harness/scripts/harness verify <change>   # OpenSpec 严格校验、变更级质量文件检查与环境探针
.harness/scripts/harness close  <change>   # 在 verify 通过、tasks 完成、human-checks 无 pending/failed、
                                           # 且 verification.md 已记录质量文档判断后执行归档
```

Windows 环境可使用 `.harness/scripts/harness.ps1`。

## 看板（Dashboard）

本地网页工具，用于集中查看与勾选各 change 的任务项及人工检查项，手动设置 / 释放 active change，管理候选 change，并只读预览 checkpoint、验证记录、证据与质量文档：

```powershell
.\board.cmd            # Windows，默认端口 8777
```

```bash
./board.sh             # Unix / Git Bash，默认端口 8777
```

启动后在浏览器访问 <http://127.0.0.1:8777>。详见 [.harness/dashboard/README.md](.harness/dashboard/README.md)。

## 目录结构

```text
/
├── AGENTS.md / CLAUDE.md      # 项目原则与 agent 工作规则
├── ARCHITECTURE.md            # 系统顶层架构地图
├── index.md                   # 模板使用指南（详细说明）
├── init.ps1 / init.sh         # 跨平台环境探针
├── board.cmd / board.sh       # 看板快捷启动
├── openspec/                  # 规格、变更设计与归档（由 OpenSpec 管理）
├── .harness/
│   ├── current.json           # 当前恢复点（唯一 active 执行槽）
│   ├── feature-index.json     # 能力索引（非任务管理器）
│   ├── templates/             # quality-contract / verification / human-checks / checkpoint
│   ├── checkpoints/           # 会话交接快照
│   ├── evidence/              # 验证证据
│   ├── scripts/               # harness verify | close
│   └── dashboard/             # 本地看板
└── docs/
    ├── architecture/  adr/    # 架构说明与架构决策记录
    ├── quality/               # 质量文档更新规则、scorecard、tech-debt、risks
    └── knowledge/             # 知识归档与踩坑记录
```

## 完成门槛

变更仅在满足以下全部条件后方可归档：

- `tasks.md` 中所有任务均已勾选完成。
- `openspec validate <id> --strict` 校验通过。
- 质量契约要求的自动验证均已执行，证据已写入 `verification.md` 与 `.harness/evidence/`。
- `human-checks.md` 中须人工确认的项目状态为 `passed` 或已明确 `waived`。
- `verification.md` 已记录质量文档判断，且相关长期质量或知识文档已同步更新。
- `.harness/current.json` 与 checkpoint 已更新至最新状态；若仍待人工检查，应已释放 active 执行槽并记录后续 close 条件。

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 发布。

## 参考与致谢

- [OpenSpec](https://github.com/Fission-AI/OpenSpec) — 规格与变更管理 CLI。
- [learn-harness-engineering](https://github.com/walkinglabs/learn-harness-engineering) — 本仓库工作流的设计参考来源。
