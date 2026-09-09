# AGENTS.md

完整的 agent 工作规则以根目录 [CLAUDE.md](CLAUDE.md) 为唯一权威源，适用于所有 coding agent。

默认使用日常协作：确认目标、实现、验证和提交。无需为普通任务创建 OpenSpec change、选择 active 执行槽或更新 `current.json`。

接续已有 OpenSpec change 或用户要求自动循环时，按 `CLAUDE.md` 的自动循环规则执行。已有规格、质量契约和人工检查不能因流程选择而绕过。

开工先读 `CLAUDE.md`，确认目录和 Git 状态；自动循环另用 `harness status` 恢复状态。
