# Harness 看板（Dashboard）

集中查看并编辑各 change 的**任务复选框**与 `verification.json` 的**验证步骤**，直接在网页上勾选 / 切状态 / 填备注，写回文件；也可手动设置 / 释放 `active_change`、管理候选 change。看板不降低 `harness close` 的校验门槛，也不提供直接 archive，同时只读预览归档就绪度、检查点、验证记录、证据与项目级质量/知识文档。

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
- **项目质量与知识**：`.harness/feature-index.json` 能力索引表，以及 `docs/quality/`、`docs/knowledge/`、`docs/adr/`、`docs/architecture/` 下的文档预览。

## 设计要点

- **零依赖**：仅用 Python 3 标准库，无需 `pip install`、无前端构建、无 CDN，可离线。
- **安全写回**：任务复选框按行号定位 + 乐观锁（提交携带原始整行，文件被外部改动则返回 `409` 并自动刷新），只改目标行；验证步骤按**步骤标识**寻址而非行号——JSON 里步骤位置会变，标识不会，并发冲突同样返回 `409`。active/candidate 操作只写 `.harness/current.json`；schema v1 annotated candidates 只在前缀能解析时迁移，未知项阻止 mutation，避免静默丢数据。
- **关闭语义**：看板只显示归档就绪度与阻塞归因，不直接 archive。七项判据全部成立时由 `.harness/scripts/harness autoclose` 自动归档；就绪度视图与 `harness ready` 共用同一份状态投影，不各写一份推导。
- **只读预览有白名单**：`/api/doc` 仅允许读取 `openspec/changes/`、`.harness/checkpoints/`、`.harness/evidence/`、`docs/`、`.harness/feature-index.json` 之内的文件，并做路径越界防护。
- **不自带解析**：验证记录的读写全部委派 `.harness/scripts/harness_verification.py`，看板不维护第二份解析实现——两份分叉解析器曾让同一份记录在 CLI 与看板给出不同结论。

## 文件

- `server.py` —— HTTP 服务与 API（`/api/state`、`/api/ready`、`/api/current`、`/api/task`、`/api/verification-step`、`/api/doc`）
- `index.html` —— 单页 UI（原生 JS/CSS + 轻量 Markdown 渲染）
- `serve.ps1` / `serve.sh` —— 启动器（自定位，文件夹改名也不受影响）
- `UPDATER-PARITY.md` —— updater ownership、模板版本与回归检查清单
