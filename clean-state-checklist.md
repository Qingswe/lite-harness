# 干净状态检查清单

- [ ] 标准启动路径仍然可用
- [ ] 标准验证路径仍然可运行
- [ ] `.harness/current.json` 已记录唯一执行中 change、候选 change、当前 task、blocker 和 next action
- [ ] 候选 change 没有修改实现代码、当前产品事实或最终验证结论
- [ ] 需要交接时已生成 `.harness/checkpoints/<change>/<timestamp>.md`
- [ ] `.harness/feature-index.json` 只作为能力索引，没有复制任务和证据
- [ ] 当前 change 的 `verification.md` 记录了真实运行过的验证
- [ ] 当前 change 的 `verification.md` 已按 `docs/quality/README.md` 记录“质量文档判断”
- [ ] 当前 change 的 `human-checks.md` 没有被 AI 假装完成的人工检查
- [ ] 没有任何半成品步骤处于未记录状态
- [ ] 变更完成时通过 `.harness/scripts/harness close <change>` 归档，没有直接运行 `openspec archive`
- [ ] 下一轮会话无需人工修复即可继续
