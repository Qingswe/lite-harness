# Architecture Drift Scan Prompt

用途：扫描代码和文档是否偏离项目黄金原则，尤其是 Unity 分层、provider/adapter 使用和共享 util 的边界。

建议频率：每周。

默认权限：只读；允许写 `.harness/evidence/agent-gc/<DATE>/architecture-drift-scan/report.md`。默认不发 PR。

## Codex Prompt

```text
你正在为 <PROJECT_NAME> 执行 Architecture Drift Scan。目标是发现架构漂移并生成审查报告，不要直接重构。

请遵守以下规则：

1. 读取 `AGENTS.md` / `CLAUDE.md`、`ARCHITECTURE.md`、`docs/architecture/`、`docs/adr/`、`docs/quality/scorecard.md`。
2. 运行并记录：
   - `pwd`
   - `git status --short`
   - `git log --oneline -5`
   - `openspec list`
   - `./init.sh` 或 `.\init.ps1`
3. 如果是 Unity 项目，按项目实际结构检查：
   - asmdef 依赖方向。
   - 文件夹/命名空间是否暗示反向依赖。
   - UI 是否绕过 Runtime/Service。
   - Runtime MonoBehaviour 是否承载本该在 Service 或 ScriptableObject Config 中的业务规则。
   - Scene/Prefab 是否承载隐式业务规则。
   - 外部系统是否绕过 provider 或 adapter。
4. 检查共享 util：
   - 是否混入领域逻辑。
   - 是否有重复 helper。
   - 是否存在手写探测数据结构、未验证边界或猜测式字段访问。
5. 对每个发现执行“证据约束”：
   - 给出文件路径和行号。
   - 说明偏离了哪条项目原则或 ADR。
   - 说明影响：正确性、可维护性、测试稳定性、agent 可读性。
   - 给出建议动作：ignore、document、candidate change、small refactor PR。
6. 不要修改代码。
7. 不要创建宽泛重构建议。每个建议都必须能收敛到一个小 PR 或一个 OpenSpec candidate change。

输出：

- 写入 `.harness/evidence/agent-gc/<DATE>/architecture-drift-scan/report.md`。
- 报告最后给出 Top 3 建议，并标注：
  - `small-pr`
  - `candidate-change`
  - `needs-human-decision`
- 如果没有发现漂移，明确写 `Status: no architecture drift found`。
```
