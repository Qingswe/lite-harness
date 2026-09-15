# 模板使用指南

工作规则以根目录 `CLAUDE.md` 为唯一权威源。本指南说明工具选择和文件用途。

## 默认：日常协作

复制模板并合并项目规则，填写 `ARCHITECTURE.md`，确认本次目标和验证方式即可开始。无需 OpenSpec 初始化、verification JSON 或执行状态副本。

局部修复直接实现和验证；复杂行为先用项目已有设计文档澄清目标、非目标和验收。代码和测试描述实际实现，产品约定只维护一份，从架构入口链接。CI、测试输出和 PR 已有证据直接引用。

轻量化评审原文与增量采纳结论（默认日常协作及移除 current 已完成）见 [docs/proposals/](docs/proposals/README.md)。

> 前提：本机已通过 Unity Hub 安装并激活目标 Unity 版本，项目已添加 Unity Test Framework 包，并有 EditMode / PlayMode 测试 assembly。

仅为未完成且需要继续的工作创建 `.harness/checkpoints/<topic>/<YYYYMMDD>[-<label>].md`，从 `.harness/templates/checkpoint.md` 取用相关项。记录难以重建的约束、决定、失败尝试、阻塞和下一步。不要复制 Git 文件清单或任务表；完成后标记已完成，长期结论移入 ADR 或知识文档，旧时点记录不回溯改写。

日常 topic 是稳定的任务名，不必对应 OpenSpec change。自动循环仍使用 canonical change id 作为目录名，供看板定位。日常交接直接读文件，无需看板索引。

需求、Spec/AC 冲突处理与项目角色权限统一遵循 `CLAUDE.md` 的“需求、验收与项目角色”。普通小修无需额外角色；采用多角色流程时，由项目已有权威文档声明权限。工具就绪或归档不代替约定的 QA 和 Done 确认。

## 可选：自动循环

需要队列调度、独立评估和自动归档时，安装 OpenSpec CLI 并执行 `openspec init`。为候选 change 准备 proposal、必要的 design、spec 增量和 tasks，从 `.harness/templates/` 准备 `program.md` 与 `verification.json`。按 `CLAUDE.md` 和 `.harness/program.md` 执行。

- `harness status`：直接查询 OpenSpec 任务、验证状态与近期提交，无需同步候选。
- `harness next <change>`：查询指定 change 的下一项任务与角色；状态由脚本计算，客户端不重复推导。
- `harness check` / `render`：记录评估结论 / 渲染供人阅读，事实来源为 JSON。
- `harness ready` / `lint`：就绪度与完整门槛；`verify` 检查规格、结构并按契约决定 Unity 探针。
- `harness autoclose` / `close`：通过完整门槛和回滚点后归档；`rollback` 恢复归档前状态。

Unix 入口为 `.harness/scripts/harness`，Windows 为 `.harness/scripts/harness.ps1`，具体参数见各自 help。日常协作不调用这些归档入口。

不保存全局 active、候选、进度或当前任务。身份、依赖和明确阻塞按 `.harness/templates/program.md` 的格式写在 change 的 `program.md`，其他状态实时查询。已有 change 的评估和人工门槛继续保留；并行任务使用隔离工作区，查询结果不提供文件锁。

### 旧 current 迁移

本模板已移除旧 current 状态文件（原 `.harness/` 下的 `current.json`），运行时不读取、不覆盖它；reset-current、sync-candidates 和看板状态写入入口已移除。旧调用方应改用只读 status 和 `next <change>`。

已采用项目升级前检查旧文件：把每个 change 的 `generated_by`、`depends_on`、仍有效的明确 blocker 移入对应 `program.md` 元数据块；只把无法重建的决定和下一步放进交接。不要迁移候选集合、任务进度、文件清单或 active。尚未表达在验证步骤中的人工约束必须保留为 blocker。对无法关联到 change 的内容先人工核对，不能直接丢弃。

确认有效信息已转移后删除旧文件。查询不使用旧文件，旧文件存在也不会覆盖 OpenSpec 事实。归档时元数据随 change 一起归档，不需要第二次状态收尾。

## 验证与知识

`init.sh` / `init.ps1` 是跨平台 Unity 环境探针，支持仓库根、`UnityProject/` 和 `UNITY_PROJECT_DIR`。未初始化 OpenSpec 时跳过可选列表检查。只有显式设置 Unity 动作变量才运行导入或测试；探针不等于功能验证。

长期架构、决策和经验分别放在 `docs/architecture/`、`docs/adr/`、`docs/knowledge/`。质量记录按 `docs/quality/README.md` 的触发条件更新。日常任务无需创建预筛 JSON，自动循环保留预筛门槛。

## 升级与后台任务

更新器按 manifest 同步脚本、看板、模板和本指南，保留项目自己的 agent 规则、状态和事实文件。升级后手动合并新版 `CLAUDE.md` 的需求验收与项目角色规则、`.harness/program.md` 的循环适用范围和验收边界，`AGENTS.md` 继续引用根规则；保留项目已有角色政策，不因模板更新重置权限。按上面的迁移说明转移旧状态中的有效信息，保留 change、验证与历史记录。

后台 Prompt 位于 `docs/agents/`。未启用 OpenSpec 本身不是日常任务的故障。只读扫描保持只读，扫描发现不自动扩大实现授权；涉及已有 change 的修复遵守原流程。
