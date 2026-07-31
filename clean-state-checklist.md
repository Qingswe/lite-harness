# 干净状态检查清单

- [ ] 标准启动路径仍然可用
- [ ] 标准验证路径仍然可运行
- [ ] `.harness/current.json` 已记录唯一 active change、候选 change、当前 task、blocker 和 next action
- [ ] 候选 change 没有修改实现代码、当前产品事实或最终验证结论
- [ ] 需要交接时已生成 `.harness/checkpoints/<change>/<YYYYMMDD>[-<label>].md`（目录名是 canonical change id，不带摘要）
- [ ] `.harness/feature-index.json` 只作为能力索引，没有复制任务和证据；`sync-feature-index.py --check` 通过
- [ ] `.harness/scripts/harness lint <change>` 通过（它已机械覆盖：必需文件、任务完成度、验证记录终态、证据路径存在、规则覆盖、风险下限、角色隔离、质量文档预筛）
- [ ] `verification.json` 中没有由 AI 代答的 `role: human` 步骤——这一条机器判不了，只能靠人自己守
- [ ] 没有任何半成品步骤处于未记录状态
- [ ] 变更完成时通过 `.harness/scripts/harness close <change>` 归档，没有直接运行 `openspec archive`
- [ ] 下一轮会话无需人工修复即可继续
