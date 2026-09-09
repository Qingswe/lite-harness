# lite-harness

面向长时运行 coding agent 的轻量工作流脚手架。默认直接实现、验证和提交，按需保留交接、决策与经验。需要自动循环时，可选用 [OpenSpec](https://github.com/Fission-AI/OpenSpec) 与 harness 的状态调度、独立评估和自动归档。

本仓库以 Unity（C#）为典型应用场景，harness 机制本身与语言无关，可适配其他技术栈。

> 本仓库的工作流参考 [walkinglabs/learn-harness-engineering](https://github.com/walkinglabs/learn-harness-engineering)，在其基础上进行了裁剪与改造。

## 采用方式

将本仓库内容复制到**目标项目的根目录**即可启用工作流。无需单独安装本包，也不依赖特定的包管理器集成。

复制完成后，请在目标项目根目录执行以下步骤：

1. 合并项目已有的 agent 指令，按实际情况填写 `ARCHITECTURE.md`。
2. 按 `CLAUDE.md` 的日常协作流程开始任务，无需安装 OpenSpec 或维护 `current.json`。选择自动循环时，再初始化 OpenSpec 并使用现有 harness 工具维护状态。
3. 参阅 [index.md](index.md) 了解变更创建、执行与归档的完整流程。
4. 如需定期运行后台 Codex 任务，参阅 [docs/agents/README.md](docs/agents/README.md) 与 [docs/agents/background-codex-tasks.md](docs/agents/background-codex-tasks.md)。

## 日常协作（默认）

确认目标与 Git 状态，读取相关代码和约定，实施改动并运行必要验证，安全后提交。只有未完成工作需要交接时才创建 checkpoint；长期结论归入架构、ADR 或知识文档。有长期质量变化才更新质量记录，不为小任务生成整套文档。

复杂变更先明确设计与验收，可选择 OpenSpec。接续已有 change 或运行自动循环时继续遵守原有质量契约和角色边界，不能绕过人工检查。保留的空 `current.json` 是兼容自动循环的模板，不是日常任务必须更新的状态。

## 自动循环的信息来源（可选）

本工作流遵循单一权威来源原则：一种信息只对应一个权威来源，其余文件仅作引用，不得重复维护副本。

```text
项目原则 → 当前产品事实 → 变更设计 → 执行状态 → 验证证据 → 知识归档
```

| 层级 | 权威来源 |
| --- | --- |
| 项目原则 | `CLAUDE.md`（`AGENTS.md` 引用） |
| 当前产品事实 | `openspec/specs/` |
| 变更设计 | `openspec/changes/<id>/`（proposal、design、spec 增量、tasks） |
| 执行状态 | `.harness/current.json`（唯一 active 执行槽、候选 change 与恢复点） |
| 验证证据 | 对应 change 的 `verification.json`、`.harness/evidence/` |
| 知识归档 | `openspec/archive/`、`docs/adr/`、`docs/knowledge/` |

**OpenSpec** 负责定义 WHAT（产品行为、变更提案、任务清单、归档事实）；**Harness** 负责管理 HOW（恢复点、checkpoint、约束与评估规则、验证证据、角色边界、归档就绪度）。

循环里有两个角色，由不同 agent、不同模型承担：**Generator** 推进实现并勾任务，**Evaluator** 判定验证步骤并写证据。谁都不能做对方那一半——自动归档下这条独立性是唯一挡住自批作业的东西。角色契约写在客户端中立的 `.harness/program.md`。

## 可选工具依赖

| 依赖 | 用途 | 说明 |
| --- | --- | --- |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) | 规格与变更管理 | 仅自动循环需要；提供 `openspec validate`、`openspec list`、`openspec archive` 等命令 |
| Python 3 | 本地看板（Dashboard） | 仅使用标准库，无需额外安装依赖 |
| Bash / PowerShell | 脚本执行 | 仓库同时提供 `.sh` 与 `.ps1` 入口 |

OpenSpec 安装示例：

```bash
npm install -g @fission-ai/openspec@latest
openspec init
```

## 自动循环

仅对进入自动循环的任务，使用 `harness status` 恢复状态，读取 active change 的设计、任务和评估规则，再由 `harness next` 分派 Generator / Evaluator。需要真实 Unity 验证时才运行环境探针。完整规则以 [CLAUDE.md](CLAUDE.md) 与 [.harness/program.md](.harness/program.md) 为准。

### 执行规则

- `openspec/changes/` 下可并存多个候选 change，但候选阶段仅做调研、proposal、design、spec 草案与 tasks 规划。
- 同一时间仅允许一个 active 执行 change：`.harness/current.json` 中的 `active_change` 为唯一执行槽；仅该 change 可进行实现、更新 `openspec/specs/`、写入本轮自动验证证据。
- 实现和自动验证已完成但仍等待人工检查的 change，可以从 active 执行槽释放出来，等 `verification.json` 中 `role: human` 的步骤被人工作答后由循环自动 close。
- 无运行证据时不得标记任务完成；不得通过修改 `tasks.md` 勾选状态或削弱测试来掩盖未完成工作。
- 归档由就绪度驱动：七项判据全部成立时 `harness autoclose` 自动执行，不需要人工逐个确认归档动作。取消的是归档动作的确认，不是人工步骤本身——任何未作答的 `role: human` 步骤都会让就绪度为假。任何情况下都不要直接调用 `openspec archive`。

完整规则见 [AGENTS.md](AGENTS.md) 与 [CLAUDE.md](CLAUDE.md)。

## 自动循环的 Harness 命令

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

## 后台 Codex 任务

模板提供一组可直接复制给 Codex 的后台任务 Prompt，用于定期扫描架构漂移、agent 残留、质量文档过期和 Unity 资源完整性风险：

- [docs/agents/README.md](docs/agents/README.md)：任务体系、推荐接入顺序和运行原则。
- [docs/agents/background-codex-tasks.md](docs/agents/background-codex-tasks.md)：如何把 Prompt 实装为每日、每周或发布前任务。
- [docs/agents/prompts/](docs/agents/prompts/)：Harness Health Check、Quality Docs GC、Architecture Drift Scan、Agent Residue Scan、Refactor PR Candidate 和 Unity Asset Integrity 的可复制 Prompt。

这些任务默认先产出报告和证据；只有低风险、范围清晰、验证路径明确的问题才建议自动创建小型 draft PR。

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

升级已有项目时，需手动合并 `CLAUDE.md` / `AGENTS.md` 及 `.harness/program.md` 的适用范围 的日常协作规则；更新器不覆盖这些项目自有规则。不要删除旧 current、change 或验证记录来迁移，也不要取消已有验收要求。

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
    ├── agents/                # 后台 Codex 任务和 Prompt
    ├── quality/               # 质量文档更新规则、scorecard、tech-debt、risks
    └── knowledge/             # 知识归档与踩坑记录
```

## 自动循环的归档门槛

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
