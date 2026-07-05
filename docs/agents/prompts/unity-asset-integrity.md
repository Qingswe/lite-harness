# Unity Asset Integrity Prompt

用途：检查 Unity 项目中的资源、Prefab、Scene、`.meta` 和批处理验证风险。

建议频率：每周、发布前、资源结构大改后。

默认权限：只读；允许写 `.harness/evidence/agent-gc/<DATE>/unity-asset-integrity/report.md`。默认不改资源。

## Codex Prompt

```text
你正在为 <PROJECT_NAME> 执行 Unity Asset Integrity 检查。目标是发现 Unity 资源完整性风险，不要自动改 Prefab、Scene 或 `.meta`。

请遵守以下规则：

1. 读取 `AGENTS.md` / `CLAUDE.md`、`ARCHITECTURE.md`、`docs/quality/risks.md`、当前 active change 的 `quality-contract.md`。
2. 运行并记录：
   - `pwd`
   - `git status --short`
   - `git log --oneline -5`
   - `openspec list`
   - `./init.sh` 或 `.\init.ps1`
3. 确认目标项目是真实 Unity 项目：
   - 存在 `Assets/`
   - 存在 `Packages/manifest.json`
   - 存在 `ProjectSettings/`
4. 扫描：
   - 新增或删除 asset 是否伴随 `.meta`。
   - Prefab/Scene YAML 中是否有 Missing Script 迹象。
   - GUID 是否引用不存在的 `.meta`。
   - asmdef 是否出现不符合 `ARCHITECTURE.md` 的依赖方向。
   - 资源移动是否可能影响存档、关卡加载、Addressables 或 Resources 路径。
5. 如果项目提供 Unity batchmode 命令，运行：
   `<UNITY_BATCHMODE_COMMAND>`
6. 不要自动修复 Prefab、Scene、GUID 或 `.meta`，除非用户明确要求并提供可验证路径。
7. 对高风险发现，建议创建 OpenSpec candidate change 或人工检查项。

输出：

- 写入 `.harness/evidence/agent-gc/<DATE>/unity-asset-integrity/report.md`。
- 报告包含：命令结果、资源风险、需要人工 Unity 检查的项目。
- 如果不是 Unity 项目，明确写 `Status: skipped, not a Unity project`。
```
