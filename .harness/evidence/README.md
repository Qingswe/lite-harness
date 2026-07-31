# Evidence

这里存放验证证据的索引或生成物引用，例如 Unity Test Framework 结果、编译日志、截图说明或人工验收记录。

证据原则：

- 变更级结论写在 `openspec/changes/<change>/verification.json`，由 `harness check` 写入。
- 本目录只保存可复查的原始证据或证据索引。
- 不用聊天记录替代证据。
- 未覆盖的验证必须明确记录，不能用“看起来正常”代替。

## 存放规则

- **新证据一律写入 `.harness/evidence/<change>/` 子目录**，文件名描述内容与日期，例如
  `.harness/evidence/<change>/group1-correctness-2026-07-26.json`。
- 历史上存在平铺的 `<change>-*.ext` 文件，保留不动；`harness status` 与 dashboard
  的证据列举同时覆盖两种布局。
- 截图等大文件优先放进 change 子目录；归档后如体积成为负担，再考虑迁出或走 LFS。
- 子目录内可以放 `README.md` 说明，它不计入证据列表。
