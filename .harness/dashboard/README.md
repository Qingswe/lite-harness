# Harness 看板（Dashboard）

看板是自动循环的可选工具，日常协作无需启动看板或选择 active。已有状态、身份、验证与归档契约保持有效；空执行槽本身不是普通任务的阻塞。

集中查看并编辑各 change 的**任务复选框**与 `verification.json` 的**验证步骤**，直接在网页上勾选 / 切状态 / 填备注，写回文件；也可手动设置 / 释放 `active_change`、管理候选 change。看板不降低 `harness close` 的校验门槛，也不提供直接 archive，同时只读预览归档就绪度、检查点、验证记录、证据与项目级质量/知识文档。

呈现层的属性由 `.harness/scripts/check-dashboard-contract.py` 断言，不靠印象判断：色相配额、字体栈、行高、8px 栅格、对比度、导航点击深度、流程图与步骤的一一对应、三张关系图与源数据的集合相等。改样式或改导航前先读它。

## 启动

根目录快捷方式（推荐）：

```powershell
.\board.cmd            # Windows 双击或命令行，默认 8777，自动开浏览器
.\board.cmd -Port 9000
```

```bash
./board.sh            # Unix / Git Bash，默认 8777
./board.sh 9000
```

或直接调用：

```powershell
.\.harness\dashboard\serve.ps1 -Port 8777 [-NoBrowser]
```

```bash
.harness/dashboard/serve.sh 8777
python .harness/dashboard/server.py --port 8777 [--root <repo>]
```

`--root` 可指向任意 harness 仓库根（默认自动定位为 `dashboard` 上两级目录），方便在一个仓库里预览另一个仓库。

然后浏览器打开 <http://127.0.0.1:8777>。按 `Ctrl+C` 停止。

## 能做什么

**可编辑：**

- **任务**：`tasks.md` 复选框，点击即写回（`- [ ]` ↔ `- [x]`），就地更新进度条、卡片不折叠。
- **验证步骤**：`verification.json` 的步骤，`状态` 下拉（pending / passed / failed / waived），可编辑 操作者 / 日期 / 证据备注，日期带「今天」按钮；按 `role` 分组且 `role: human` 高亮，卡片标题旁有状态计数。人工步骤的判定契约（`observe` / `pass_when` / `fail_when` / `needs_human_because`）随步骤展示，不必回去翻文件。
- **执行槽**：在 change 详情页将某个 change 设为 active、释放 active，或加入 / 移出候选列表。设置 active 时若已有另一 owner，API 返回 `409` 而不覆盖；释放时保留 phase、blockers、next action 与 checkpoint，只清理工作文件等执行瞬态。
- **生命周期**：执行槽、候选成员关系与 lifecycle phase 是三个独立维度。overview 分别列出实施中、待人工、待用户指示、可关闭和已规划候选；`active_change=null` 且存在可恢复的 gated change 是健康状态。

**只读预览：**

- **顶部横幅**（`.harness/current.json`）：`active_change`、`current_task`、`blockers`、`next_action`、canonical candidates、`verification_summary` 与已归档 change；可释放当前 active，可折叠查看迁移详情、`working_files`、`dirty_assumptions`、最近检查点。
- **每个 change 卡片**：验证记录 `verification.json`（同时渲染 `program.md` 的评估规则）、该 change 的检查点 `.harness/checkpoints/<id>/*.md`、证据 `.harness/evidence/<id>*`，按需懒加载并以轻量 Markdown 渲染。
- **项目质量与知识**：`.harness/feature-index.json` 能力索引表，以及 `docs/quality/`、`docs/knowledge/`、`docs/adr/`、`docs/architecture/` 下的文档预览（四个目录都递归列举）。
- **分层导航**：侧栏是服务端派生的三层折叠树（`/api/state` 的 `nav_tree`）。一级分组首屏展开、二级收起，任意 change / 文档 / 证据集最多两次点击可达；展开状态存 `localStorage`，不写 `current.json`。
- **图形**：change 详情页有验证流程图（评估规则 → 步骤 → 归档结论），概览页有归档依赖图，「系统结构」页有脚本模块依赖图与 API 数据流图。每张图下方都有等价的文字表达，图形渲染失败时流程仍然完整可读。

## 设计要点

- **零依赖**：仅用 Python 3 标准库，无需 `pip install`、无前端构建、无 CDN，可离线。图形是手写的分层 SVG 渲染器（`graph.js`，约 170 行），不引 mermaid 或 d3——本仓库只需要分层 DAG 一种图，而离线可用是承重属性。
- **观感属性也要可断言**：「审美好」「层级清晰」不能直接判定，所以每一条都换成能从仓库文件算出来的代理指标（色相簇数、点击深度、节点数与步骤数相等、边集与源数据相等）。`.harness/program.md` 第 1 节第二条判据：不能被断言的约束只是措辞。
- **图不手绘**：三张关系图的边都由源数据计算。手绘的架构图会漂移，而漂移的图比没有图更糟——它让人对着一个不再成立的结构做决定。`DATA_FLOW` 是唯一需要人写的一份，因此配了防漂移断言：新增 route 却没登记就会让契约脚本失败。
- **安全写回**：任务复选框按行号定位 + 乐观锁（提交携带原始整行，文件被外部改动则返回 `409` 并自动刷新），只改目标行；验证步骤按**步骤标识**寻址而非行号——JSON 里步骤位置会变，标识不会，并发冲突同样返回 `409`。active/candidate 操作只写 `.harness/current.json`；schema v1 annotated candidates 只在前缀能解析时迁移，未知项阻止 mutation，避免静默丢数据。
- **关闭语义**：看板只显示归档就绪度与阻塞归因，不直接 archive。七项判据全部成立时由 `.harness/scripts/harness autoclose` 自动归档；就绪度视图与 `harness ready` 共用同一份状态投影，不各写一份推导。
- **静态路由比预览白名单更窄**：只接受 `WEB_DIR` 下不含路径分隔符的 `.css` / `.js`，并且先百分号解码再校验。刻意不复用 `DOC_ALLOW`——那份白名单服务于文档预览，扩大到能读脚本目录等于把 `.harness/scripts/` 也变成可下载。
- **只读预览有白名单**：`/api/doc` 仅允许读取 `openspec/changes/`、`.harness/checkpoints/`、`.harness/evidence/`、`docs/`、`.harness/feature-index.json` 之内的文件，并做路径越界防护。
- **路径校验只有一份**：`/api/doc` 与 `/api/evidence-file` 共用 `harness_state._resolve_allowed()`。它先百分号解码再判定（否则 `%2e%2e%2f` 只会因为文件不存在而恰好失败），并用 `realpath` 跟进软链（`normpath` 只做字符串折叠，跟不进软链）。两份路径校验迟早分叉，分叉的那份就是漏洞。
- **证据文件端点比预览更窄**：`/api/evidence-file` 只允许 `.harness/evidence/` 之内的文件，返回原始字节并带 `X-Content-Type-Options: nosniff` 与 `Content-Security-Policy: default-src 'none'`。SVG 只经 `<img src>` 载入，**绝不 innerHTML**——SVG 里可以写 `<script>`，作为图片载入时浏览器不执行它。
- **证据分类是全函数**：`kind` 的兜底是 `other-<ext>` 而不是 `unclassified`；历史平铺布局的文件 `source` 取 `legacy-flat`。一个「未分类」筐会立刻装进所有不好归类的东西，然后按类型筛选就永远漏；两种布局漏掉任一种都会让证据从筛选结果里消失。
- **操作者是选出来的，不是打出来的**：步骤行的操作者是从 `.harness/roles.json` 生成的下拉，外加一个「自定义…」兜住不在档案里的外部工具。侧栏底部的角色切换只改变预填对象。预填解决「不用打字」，选择解决「不用记得有哪些人」——档案本来就是为后者维护的。
- **角色档案不是身份凭证**：`.harness/roles.json` 只提供 `operator` 与备注模板。看板写回路径不接受也不传递 `evaluated_by`，AI evaluator 的身份只能由真实 Evaluator 经 `harness check` 写入。`harness_roles.PROFILE_FIELDS` 从结构上拒绝任何多余字段，不靠服务端记得过滤。
- **不自带解析**：验证记录的读写全部委派 `.harness/scripts/harness_verification.py`，看板不维护第二份解析实现——两份分叉解析器曾让同一份记录在 CLI 与看板给出不同结论。

## 文件

- `server.py` —— HTTP 服务与 API（`/api/state`、`/api/ready`、`/api/current`、`/api/task`、`/api/verification-step`、`/api/doc`、`/api/evidence-file`、`GET/POST /api/roles`），以及静态路由与 `DATA_FLOW` 声明
- `index.html` —— DOM 骨架
- `theme.css` —— 全部设计变量与样式；颜色字面量只允许出现在 `:root`
- `app.js` —— 视图渲染与写回（原生 JS + 轻量 Markdown 渲染）
- `graph.js` —— 分层有向图的 SVG 渲染器
- `serve.ps1` / `serve.sh` —— 启动器（自定位，文件夹改名也不受影响）
- `UPDATER-PARITY.md` —— updater ownership、模板版本与回归检查清单
