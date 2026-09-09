# 模板使用指南

工作规则以根目录 `CLAUDE.md` 为唯一权威源。本指南说明工具选择和文件用途。

## 默认：日常协作

复制模板并合并项目规则，填写 `ARCHITECTURE.md`，确认本次目标和验证方式即可开始。无需 OpenSpec 初始化、active 执行槽、verification JSON 或每轮更新 current。

局部修复直接实现和验证；复杂行为先用项目已有设计文档澄清目标、非目标和验收。代码和测试描述实际实现，产品约定只维护一份，从架构入口链接。CI、测试输出和 PR 已有证据直接引用。

## 跨会话交接

仅为未完成且需要继续的工作创建 `.harness/checkpoints/<topic>/<YYYYMMDD>[-<label>].md`，从 `.harness/templates/checkpoint.md` 取用相关项。记录难以重建的约束、决定、失败尝试、阻塞和下一步。不要复制 Git 文件清单或任务表；完成后标记已完成，长期结论移入 ADR 或知识文档，旧时点记录不回溯改写。

日常 topic 是稳定的任务名，不必对应 OpenSpec change。自动循环仍使用 canonical change id 作为目录名，供看板定位。日常交接直接读文件，无需看板索引。

## 可选：自动循环

需要队列调度、独立评估和自动归档时，安装 OpenSpec CLI 并执行 `openspec init`。为候选 change 准备 proposal、必要的 design、spec 增量和 tasks，从 `.harness/templates/` 准备 `program.md` 与 `verification.json`。按 `CLAUDE.md` 和 `.harness/program.md` 执行。

- `harness status`：恢复状态、漂移与近期提交；`sync-candidates` 从实际目录同步候选集合。
- `harness next`：给客户端下一项任务与角色；状态由脚本计算，客户端不重复推导。
- `harness check` / `render`：记录评估结论 / 渲染供人阅读，事实来源为 JSON。
- `harness ready` / `lint`：就绪度与完整门槛；`verify` 检查规格、结构并按契约决定 Unity 探针。
- `harness autoclose` / `close`：通过完整门槛和回滚点后归档；`rollback` 恢复归档前状态。

Unix 入口为 `.harness/scripts/harness`，Windows 为 `.harness/scripts/harness.ps1`，具体参数见各自 help。日常协作不调用这些归档入口。

`.harness/current.json` 保留 schema、generator 身份、依赖与 per-change context，由循环工具维护派生状态，执行者只补无法推导的上下文；不要在普通会话更新它。`reset-current` 会清空状态，不是迁移或日常收尾步骤。`.harness/feature-index.json` 由 `sync-feature-index.py` 派生，人工只维护 overrides。

现有 change 继续遵守全部既定要求，不能换成日常协作来跳过评估或人工步骤。日常任务若与其范围冲突，应回到对应 change；并发采用隔离工作区，active 不是文件锁。

## 验证与知识

`init.sh` / `init.ps1` 是跨平台 Unity 环境探针，支持仓库根、`UnityProject/` 和 `UNITY_PROJECT_DIR`。未初始化 OpenSpec 时跳过可选列表检查。只有显式设置 Unity 动作变量才运行导入或测试；探针不等于功能验证。

长期架构、决策和经验分别放在 `docs/architecture/`、`docs/adr/`、`docs/knowledge/`。质量记录按 `docs/quality/README.md` 的触发条件更新。日常任务无需创建预筛 JSON，自动循环保留预筛门槛。

## 升级与后台任务

更新器保留项目自己的 agent 规则、状态和事实文件；升级后需手动合并新版 `CLAUDE.md` / `AGENTS.md`。保留已有 current、change、验证与历史记录，新任务按需要选择流程，无需批量迁移。

后台 Prompt 位于 `docs/agents/`。未启用 OpenSpec、没有 active 或 current 未更新本身不是日常任务的故障。只读扫描保持只读，扫描发现不自动扩大实现授权；涉及已有 change 的修复遵守原流程。
