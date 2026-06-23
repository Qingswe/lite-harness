# Harness 看板（Dashboard）

集中查看并编辑各 change 的**任务复选框**与**人工检查项（human-checks）**，直接在网页上勾选 / 切状态 / 填备注，按原格式写回文件；也可手动设置 / 释放 `active_change`、管理候选 change。看板不降低 `harness close` 的校验门槛，同时只读预览检查点、验证记录、证据与项目级质量/知识文档。

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
- **人工检查**：`human-checks.md` 表格，`状态` 下拉（pending / passed / failed / waived），可编辑 操作者 / 日期 / 证据备注，日期带「今天」按钮；卡片标题旁有状态计数。
- **执行槽**：在 change 详情页将某个 change 设为 active、取消 active，或加入 / 移出候选列表。已实现并通过自动验证但仍待人工检查的 change 可以取消 active，等人工检查后再按明确指令 close。

**只读预览：**

- **顶部横幅**（`.harness/current.json`）：`active_change`、`current_task`、`last_verified_task`、`blockers`、`next_action`、候选与已归档 change；可取消当前 active，可折叠查看 `working_files`、`dirty_assumptions`、最近检查点。
- **每个 change 卡片**：验证记录 `verification.md`、该 change 的检查点 `.harness/checkpoints/<id>/*.md`、证据 `.harness/evidence/<id>*`，按需懒加载并以轻量 Markdown 渲染。
- **项目质量与知识**：`.harness/feature-index.json` 能力索引表，以及 `docs/quality/`、`docs/knowledge/`、`docs/adr/`、`docs/architecture/` 下的文档预览。

## 设计要点

- **零依赖**：仅用 Python 3 标准库，无需 `pip install`、无前端构建、无 CDN，可离线。
- **安全写回**：任务和人工检查按行号定位 + 乐观锁（提交携带原始整行，文件被外部改动则返回 `409` 并自动刷新），只改目标行；active/candidate 操作只写 `.harness/current.json`，并清理旧执行上下文，避免 stale task 误导下一轮 agent。
- **只读预览有白名单**：`/api/doc` 仅允许读取 `openspec/changes/`、`.harness/checkpoints/`、`.harness/evidence/`、`docs/`、`.harness/feature-index.json` 之内的文件，并做路径越界防护。
- **格式对齐**：复选框与人工检查表格格式与 `.harness/scripts/harness.ps1` 的校验正则、`.harness/templates/human-checks.md` 模板一致。

## 文件

- `server.py` —— HTTP 服务与 API（`/api/state`、`/api/current`、`/api/task`、`/api/human-check`、`/api/doc`）
- `index.html` —— 单页 UI（原生 JS/CSS + 轻量 Markdown 渲染）
- `serve.ps1` / `serve.sh` —— 启动器（自定位，文件夹改名也不受影响）
