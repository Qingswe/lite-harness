# Dashboard Updater Parity

`.harness/update-manifest.txt` 声明 `.harness/dashboard/`、`.harness/scripts/`、`.harness/templates/` 和 `docs/agents/` 由 lite-harness updater 管理。当前项目从 2026-07-24 起依赖以下本地模板行为：

- `.harness/current.json` schema v2：canonical `candidate_changes` + `change_context`。
- schema v1 annotated candidate 的无损兼容读取，以及未知条目阻止 mutation。
- active owner 冲突返回 `409`；release 保留 durable recovery context。
- dashboard 独立显示 active、candidate 和 lifecycle phase，并使用 `harness close` 术语。
- health check 接受具有 phase、next action 和 checkpoint/evidence 的健康 released slot。
- Windows/Unix `reset-current` 生成相同 schema v2。
- 状态投影、schema 校验、lifecycle 推导与写回逻辑集中在 `.harness/scripts/harness_state.py`；`server.py` 只保留 HTTP 层并委派给它（`optimize-harness-context-and-execution`，2026-07-26）。
- `harness status [--json]` / `harness.ps1 status [-Json]` 由同一个 `harness_state.py` 提供，包含 current.json ↔ `openspec/changes/` 的漂移检测，并在漂移或状态错误时以非零码退出。
- `list_evidence` 同时覆盖平铺 `<change>*` 文件与 `.harness/evidence/<change>/` 子目录。
- `harness close` 在两个平台上都以非交互方式归档（`-y` / `--yes`），并支持 `--skip-specs` / `-SkipSpecs`；归档成功后调用 `harness_state.py finalize-close` 收尾 `current.json`。
- `current.json` 的 schema 只在 `harness_state.py` 的 `CURRENT_STATE_FIELDS` 定义（15 个字段，含 `deleted_files` / `last_change_note` / `verification_summary`）；两个平台的 `reset-current` 都委派给它，脚本内不得再出现字面量 JSON 模板。
- `change_context` 使用结构化字段（`CONTEXT_FIELDS`），摘要上限 `CONTEXT_SUMMARY_MAX = 80`；`harness status` 会报告不合规条目。
- `harness sync-candidates` 按 `openspec/changes/` 重写候选成员关系；`status` 只报告漂移不写状态。
- verify / close 的门槛检查集中在 `.harness/scripts/harness_checks.py`（`human-checks` 正向断言、`doc-refs`、`skills`、`probe-needed`），两个平台都调用它，不各自实现正则。
- `init.sh` / `init.ps1` 支持 `SKIP_OPENSPEC_LIST=1`；`verify` 内部调用探针时使用它避免重复 `openspec list`。
- checkpoint 只接受 `.harness/checkpoints/<change>/<YYYYMMDD>[-<label>].md`；证据新增一律写入 `.harness/evidence/<change>/`。
- **循环化（2026-07-30，`simplify-harness-change-artifacts`）**：`verification.md` + `human-checks.md` 合并为 `verification.json`，`quality-contract.md` 改为 `program.md`；三份旧模板已删除。
- `verification.json` 与 `program.md` 的解析、校验、写入、渲染只在 `.harness/scripts/harness_verification.py`；`harness_checks.py`、`harness_state.py`、`dashboard/server.py` 全部委派，测试断言三者拿到同一个模块对象。
- 关闭门槛集中在 `harness_checks.py` 的 `close_gate()`；`harness lint` 与 `harness close` 调用同一函数，两平台也调用同一函数，shell / PowerShell 内不再各写一份任务完成度、必需文件与质量文档断言。
- 就绪度由七项判据计算（含证据路径存在性、评估规则覆盖、角色隔离、质量文档预筛），且**包含 lint**——否则会出现 ready 说可关、lint 说不行的分裂，自动归档会先打 tag 再在门槛处中止。
- 人工写入的 lifecycle phase 只能收紧：仅当它声称 `ready_to_close` / `complete` 而计算判定未就绪时才被覆盖；其余 phase 一律采信人工。
- 角色隔离三重强制：agent 工具白名单、提交级断言（不存在同时置终态又改实现文件的提交）、`evaluated_by` 身份校验。
- `harness close` 前建立 `harness/pre-close/<change>` tag；建不出回滚点必须中止归档。`harness autoclose` 按依赖顺序归档全部就绪 change。
- 新增子命令两平台一致：`ready` / `next` / `lint` / `check` / `render` / `autoclose`；测试断言两个 wrapper 的子命令集合相同。
- 质量文档判断改为 `prescreen-quality-docs.py` 从 diff 预筛，默认「无需更新」，未触发条目不产出说明文字。
- 存量迁移由 `migrate-change-artifacts.py` 执行：既有结论无损保留，缺失字段标注「迁移时补录」，并为每个迁移过的 change 追加一条 `M1` 人工确认步骤（迁移结论豁免了逐条证据路径要求，代价是这一次人工确认）。
- 看板步骤编辑改为 step id 寻址（取代行号 + 原始整行乐观锁），新增 `/api/ready` 与就绪度视图，与 `harness ready` 共用实现。
- **呈现层契约（2026-08-02，`refresh-harness-dashboard-visual-language`）**：单文件 `index.html` 拆成 `index.html` / `theme.css` / `app.js` / `graph.js`，`server.py` 增加**只认 `WEB_DIR` 下裸文件名 `.css` / `.js`** 的静态路由（先解码再校验，不复用 `DOC_ALLOW`）。
- `theme.css` 是全部视觉变量的唯一定义处：非中性色相恰好三种（`--act` / `--pass` / `--fail`），`pending` 与 `waived` 用中性灰的实心点与空心环区分而不占彩色配额；正文字体栈以 `Arial, Helvetica` 起头；行高不低于 1.4；间距 px 值都是 8 的倍数；`:root` 之外没有颜色字面量。
- `/api/state` 新增 `nav_tree`（服务端派生的三层折叠导航，一级展开二级收起）、`graphs.dependency`、`graphs.modules`，`/api/state` 在 HTTP 层并入 `graphs.data_flow`；每个 change 新增 `verification_flow`。
- `build_library()` 的四个目录**全部递归**。`quality` 曾是非递归的，`docs/quality/pitfalls/` 下三篇文档因此从未出现在看板里。
- `parse_verification_steps()` 除 `item` 外还带出 `how` 与 `pass_when` 原名。只留改名后的 `item` 会让 `hv.step_summary()` 找不到字段，把所有自动步骤摘要成「该步骤未写明要求」。
- `server.py` 的 `DATA_FLOW` 与 `registered_routes()` 成对存在：新增 route 却没登记会让 `check-dashboard-contract.py graphs` 失败。删掉其中一个等于关掉防漂移。
- 新增 `.harness/scripts/check-dashboard-contract.py`（子命令 `tokens` / `nav` / `graphs` / `evidence` / `roles` / `all`，可一次跑多组，`--json` 产出证据）。**未实现的断言组一律报失败**，不是跳过。

## Upstream 状态

- 本文件随模板分发：行为清单与回归清单由模板侧拥有（路径见
  `.harness/update-manifest.txt`）。采用项目运行 updater 后按本清单核对，
  出现语义回退先查模板侧是不是被改了回去。
- 回植实录：
  - PR <https://github.com/Qingswe/lite-harness/pull/1>（2026-07-27）：schema v2 /
    lifecycle 工作、共享状态层与 `harness status`。
  - PR <https://github.com/Qingswe/lite-harness/pull/2>（2026-07-30）：loop
    engineering——`verification.json` / `program.md` 循环化、角色隔离、就绪度
    计算与自动归档。
  - PR <https://github.com/Qingswe/lite-harness/pull/3>（2026-08-24）：dashboard
    呈现层拆分（`index.html` / `theme.css` / `app.js` / `graph.js`）、
    `check-dashboard-contract.py`、`nav_tree` 与三张关系图、证据分类
    （`kind` / `source` / `date`）与 roles 档案（`harness_roles.py` +
    `.harness/roles.json` 入清单）。
  - PR <https://github.com/Qingswe/lite-harness/pull/4>（2026-08-24）：通用
    JSON-Schema 子集校验工具 `.harness/scripts/validate-json-schema-subset.py`
    （`type` / `const` / `enum` / `minLength` / `pattern` / `minItems` / `items` /
    `required` / `properties` / `additionalProperties` / 本地 `$ref`），供各采用
    项目校验 repository-owned harness evidence JSON。
- **采用项目专属内容会被 updater 覆盖**：`.harness/roles.json` 里的真实人名、
    `docs/knowledge/pitfalls/README.md` 里项目自己的条目，每轮更新后从
    `.harness/backups/harness-update-<时间戳>/` 恢复即可，属于预期行为，不是回归。

## 更新后回归清单

1. 运行 `python -m unittest discover -s .harness/dashboard/tests -p "test_*.py" -v`（**168 项基线**；含 `test_harness_verification.py`、`test_harness_loop.py`、`test_static_route.py` 与 `test_dashboard_contract.py`。此前文档里写的 119 是过期数字）。
2. 比较 `.harness/scripts/harness` 与 `.harness/scripts/harness.ps1` 的子命令、选项与 schema 字段；确认两者都通过 `harness_state.py` 取状态。
3. 确认 README/health-check 没有恢复“pending human checks 必须占用 active”或“dashboard 可直接 archive”的旧语义。
4. 在 dashboard 检查 released human/direction-gated change、迁移 warning 和 active conflict。
5. 确认 `harness ready` 与 `harness lint` 对同一个 change 结论不矛盾；确认未迁移的 change 被报错而不是显示成零 pending。
6. 确认 `harness close` 在归档前真的打了 `harness/pre-close/<change>` tag，并至少演练过一次 `git reset --hard` 回滚。
7. 运行 `python3 .harness/scripts/check-dashboard-contract.py all`，全部通过（**52 条断言**，六组：tokens / layout / nav / graphs / evidence / roles）。updater 若把 `index.html` 还原成单文件、把 `theme.css` 的 token 覆盖掉、把字号改回散装 px、删掉 `/api/evidence-file` 或 `/api/roles`、把步骤行的操作者改回自由文本框、或把证据分类退回无 `kind` 的形态，这一步会立刻报红。
8. 确认 `.harness/scripts/harness` 与 `harness.ps1` 的子命令集合仍然相同（含 `check` 与 `roles` 两个透传命令）。这条由 `test_harness_state.py` 解析两个文件的分发分支断言，不再是一份硬编码名单——名单式断言看不见它没列出的子命令，`check` 曾因此在 PowerShell 侧缺失很久。

> 模板仓库自身没有证据文件，`check-dashboard-contract.py all` 的 evidence 组
> （B1-1 ~ B1-6）预期报红——「空证据目录必须报红」是有意设计（见
> `test_dashboard_contract.py` 的 `test_empty_repo_fails_instead_of_passing`）。
> 采用项目在自己的真实证据上应跑出 52/52；在刚克隆的模板副本上看到那 5 条
> 失败不是回归。
