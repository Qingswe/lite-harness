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
| 验证证据 | 对应 change 的 `verification.json`、`.harness/evidence/` |
| 知识归档 | `openspec/archive/`、`docs/adr/`、`docs/knowledge/` |

**OpenSpec** 负责定义 WHAT（产品行为、变更提案、任务清单、归档事实）；**Harness** 负责管理 HOW（恢复点、checkpoint、约束与评估规则、验证证据、角色边界、归档就绪度）。

循环里有两个角色，由不同 agent、不同模型承担：**Generator** 推进实现并勾任务，**Evaluator** 判定验证步骤并写证据。谁都不能做对方那一半——自动归档下这条独立性是唯一挡住自批作业的东西。角色契约写在客户端中立的 `.harness/program.md`。

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
3. 运行 `openspec list` 查看变更列表；读取 active change 的 `proposal.md`、`tasks.md`、`program.md`。
4. 查阅 `git log --oneline -5` 了解近期提交。
5. 读取相关 `ARCHITECTURE.md`、`docs/architecture/` 与 `docs/quality/scorecard.md`。
6. 运行 `init.ps1`（Windows）或 `init.sh`（Unix / macOS / Linux）执行环境探针。

随后仅围绕当前 active change 逐条推进 `tasks.md`，直至实现和自动验证完成、释放 active 执行槽，或被明确记录为 blocked。

### 执行规则

- `openspec/changes/` 下可并存多个候选 change，但候选阶段仅做调研、proposal、design、spec 草案与 tasks 规划。
- 同一时间仅允许一个 active 执行 change：`.harness/current.json` 中的 `active_change` 为唯一执行槽；仅该 change 可进行实现、更新 `openspec/specs/`、写入本轮自动验证证据。
- 实现和自动验证已完成但仍等待人工检查的 change，可以从 active 执行槽释放出来，等 `verification.json` 中 `role: human` 的步骤被人工作答后由循环自动 close。
- 无运行证据时不得标记任务完成；不得通过修改 `tasks.md` 勾选状态或削弱测试来掩盖未完成工作。
- 归档由就绪度驱动：七项判据全部成立时 `harness autoclose` 自动执行，不需要人工逐个确认归档动作。取消的是归档动作的确认，不是人工步骤本身——任何未作答的 `role: human` 步骤都会让就绪度为假。任何情况下都不要直接调用 `openspec archive`。

完整规则见 [AGENTS.md](AGENTS.md) 与 [CLAUDE.md](CLAUDE.md)。

## Harness 命令

```bash
.harness/scripts/harness status            # active 槽、候选、blocker、next action、漂移，一次给全
.harness/scripts/harness ready             # 现在能归档哪些，其余各差哪一件事、责任方是谁
.harness/scripts/harness next  --json      # 循环的下一个动作：哪个 change、哪条 task、该派哪个角色
.harness/scripts/harness lint  <change>    # 与 close 完全相同的门槛断言，但不归档，任何时刻可跑
.harness/scripts/harness check <change> <step> <status> --commit
                                           # 按步骤标识写验证结论，单独成一个提交
.harness/scripts/harness render <change>   # 把 verification.json 渲染成 markdown 供人阅读
.harness/scripts/harness verify <change>   # OpenSpec 严格校验、仓库结构检查与环境探针
.harness/scripts/harness autoclose         # 归档全部就绪的 change，按依赖顺序
.harness/scripts/harness rollback <change> # 把仓库退回某次归档之前；有残留就报错，不算成功
```

Windows 环境可使用 `.harness/scripts/harness.ps1`。

## 更新 Harness 模板

已采用本仓库的项目，可以从 GitHub 拉取最新模板文件并同步到项目根目录：

```bash
.harness/scripts/update-harness          # Unix / macOS / Git Bash，默认只预览
.harness/scripts/update-harness --apply  # 确认后实际同步
```

```powershell
.\update-harness.cmd        # Windows，默认只预览
.\update-harness.cmd -Apply # 确认后实际同步
```

更新器默认从 `https://github.com/Qingswe/lite-harness.git` 的 `main` 分支读取 `.harness/update-manifest.txt`，只同步 harness 管理的脚本、看板、模板和流程说明文件。它不会默认覆盖项目事实或执行状态文件，例如 `AGENTS.md`、`CLAUDE.md`、`ARCHITECTURE.md`、`README.md`、`.harness/current.json`、`.harness/feature-index.json`、`openspec/` 与长期质量记录。

实际同步时会先把被覆盖的文件备份到 `.harness/backups/harness-update-<timestamp>/`。可通过 `--ref <tag-or-branch>` / `-Ref <tag-or-branch>` 固定更新来源。

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
│   ├── program.md             # 循环宪法：角色边界、归档策略、回滚规则与预算
│   ├── templates/             # program / verification / checkpoint
│   ├── checkpoints/           # 会话交接快照
│   ├── evidence/              # 验证证据
│   ├── scripts/               # harness status | ready | next | lint | check | close ...
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
- `verification.json` 全部步骤为 `passed` 或 `waived`，`waived` 均有说明。
- 步骤引用的每个证据路径真实存在。
- `program.md` 的每条评估规则至少被一个已通过或已豁免的步骤覆盖。
- 质量文档预筛已运行，被触发的条目均有人工理由。
- 角色隔离校验通过：不存在同时改实现又把步骤置为终态的提交，且 `evaluated_by` 不等于本 change 的 generator 身份。

这七项由 `harness ready` 计算，全部成立才自动归档。**人工写入的 lifecycle phase 只能收紧不能放宽**——声称可归档但计算判定未就绪时，采信计算结果并报告是哪一项判据。就绪度只驱动触发；`harness close` 仍执行完整门槛断言，就绪度误报时它是最后一道。

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 发布。

## 参考与致谢

- [OpenSpec](https://github.com/Fission-AI/OpenSpec) — 规格与变更管理 CLI。
- [learn-harness-engineering](https://github.com/walkinglabs/learn-harness-engineering) — 本仓库工作流的设计参考来源。
