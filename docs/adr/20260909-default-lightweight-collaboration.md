# 默认日常协作，按需采用自动循环

日期：2026-09-09

## 背景与决策

普通任务被要求维护 OpenSpec、执行槽和评估记录，产生了与任务复杂度不匹配的成本。新版 current 同时承载身份、依赖和循环状态，直接删除会损坏自动循环。

默认采用日常协作，只有未完成且需要继续时记录交接；复杂任务先明确设计，按需选用 OpenSpec。现有 change 继续走自动循环，保留独立评估、人工步骤、就绪度与回滚门槛。不新增模式配置文件，具体边界以根目录 `CLAUDE.md` 为准。

## 取舍与迁移

循环状态、验证 schema 与门槛算法保持不变；日常任务不再维护这些状态。环境探针在未初始化 OpenSpec 时跳过列表调用。后台扫描依据适用工作方式检查，不能把未启用工具当成故障。

更新器不会覆盖项目自有的 CLAUDE.md、AGENTS.md 与 .harness/program.md，已有项目需要手动合并规则及循环适用范围。保留已有状态和验收记录；不重置 current、不批量归档。若需要恢复强制循环，应明确修改项目规则，而不是恢复旧提示词。

## 验证

- 修改前后均运行 `python3 -m unittest discover -s .harness/dashboard/tests -q`，168 项通过。
- 看板 tokens / layout / nav / graphs / roles 契约共 43 条通过；未运行依赖真实证据的 evidence 组，模板没有对应生成物。
- Bash 语法检查、仓库环境探针、harness status 通过。
- 临时隔离目录验证：未初始化跳过 OpenSpec，已初始化调用 list，显式跳过仍有效，未创建 current。
- PowerShell 未实机运行（本机无 pwsh）；本仓库不是 Unity 项目，未执行 Unity 导入或测试。
