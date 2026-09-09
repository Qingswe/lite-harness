# 从 OpenSpec 查询，移除 current

日期：2026-09-09

本决策替代同日“默认日常协作，按需采用自动循环”中保留 current 的部分。

## 决策

删除模板 current；CLI 和看板直接读取 OpenSpec change、tasks、verification，不读写全局状态文件。执行目标以 `harness next <change>` 的参数传入，不保存 active 或候选成员关系。旧 JSON API 的 current 字段仅是兼容性的内存查询结果，不是文件或可写接口。

program.md 的可选 harness-metadata 块只保存不能推导的 generated_by、depends_on 和 blockers，拒绝 current_task、phase 等进度副本。身份缺失时不能证明独立评估，终态自动步骤必须被门槛拒绝；身份、依赖和阻塞随 change 一起归档。

删除 reset-current、sync-candidates、归档后的 current 清理和看板状态维护按钮。已有采用项目按 index.md 迁移有效信息；旧文件不作为运行输入，也不自动覆盖或删除用户内容。模板自身为空状态，直接移除。

## 验证与边界

- 更新后的 159 项回归测试通过：保留任务、验证、人工步骤、角色隔离与归档门槛测试；移除只针对已废弃状态写入/重置接口的用例，以 OpenSpec 查询、无写入、元数据校验及归档后自然消失的测试替代。
- 43 条看板 tokens / layout / nav / graphs / roles 契约通过；模板没有真实 evidence，未执行依赖真实生成物的 evidence 组。
- Bash 与 JavaScript 语法、status 和 next CLI 查询通过。
- 无 PowerShell 运行时，Windows wrapper 未实机运行；两平台子命令集合由回归测试校验。未执行 Unity 验证，本次不涉及 Unity 工程。

生命周期与查询不提供并发锁；同时执行不同任务仍需隔离工作区。没有全局副本后，归档无需“清理恢复点”，后续查询自然只包含未归档 change。
