# Harness 循环宪法

本文件定义循环怎么跑：角色边界、归档策略、回滚规则与预算。它是**客户端中立**
的权威——Claude Code 的 `.claude/agents/` 定义、其他客户端的等价配置，都只是
它在某个客户端上的实现。两者冲突时以本文件为准。

每个 change 自己的约束与评估规则在 `openspec/changes/<id>/program.md`，本文件
不重复它们。

---

## 1. 两条判据

> **一件事应该由人做，当且仅当 AI 无法为它产出可复查的证据。**

> **一条约束应该是机械的，当且仅当它能被断言；否则它只是措辞。**

第一条决定什么写成 `role: human`。第二条决定角色隔离怎么实现——因为归档是自动
的，Evaluator 的独立性是唯一挡住自批作业的东西，所以它必须靠可断言的事实强制，
不能靠角色指令里的措辞。

## 2. 角色

| | Generator | Evaluator |
| --- | --- | --- |
| 读 | 本 change 的 `program.md ## 约束`、`design.md`、`specs/`、`tasks.md` | 本 change 的 `program.md ## 评估规则`、`verification.json`、diff、`tasks.md`（只读） |
| 写 | 实现代码、`tasks.md` 复选框 | `verification.json` 的步骤结论、`.harness/evidence/<change>/*` |
| 禁写 | `verification.json` 的步骤状态、证据文件 | 实现代码、`tasks.md` |
| 模型 | 与 Evaluator 不同 | 与 Generator 不同 |

**Evaluator 不以任务已勾选作为通过依据。** Generator 勾了复选框不构成证据；
结论只能来自 `program.md` 的评估规则与 Evaluator 自己跑出来的结果。

### 2.1 三重机械强制

隔离由三道互不依赖的检查保证，任一道单独失效不致使隔离整体失效：

1. **工具白名单**——限制各角色可写的路径。只在支持子代理的客户端生效，因此
   不能是唯一一道。
2. **提交级断言**——不存在同时把某步骤翻成 `passed` 又修改了实现文件的提交。
   与客户端无关，是最硬的一道。
3. **身份校验**——`evaluated_by.{agent,model}` 必填，且不得等于本 change 的
   generator 身份（记录在 `.harness/current.json`）。同模型自评被直接拒绝。

三道都依赖仓库里可复查的事实，不依赖执行体自述。

## 3. 循环

```
harness next --json      → 目标 change、目标 task、该派的角色
  ├─ role=generator      → 推进 tasks.md，写实现
  ├─ role=evaluator      → 按评估规则跑检查，写 verification.json 步骤结论与证据
  └─ 就绪度为真          → 打 ratchet tag → harness close（自动）→ 取下一个候选
```

**状态归脚本，编排归客户端。** `harness next` 与 `harness ready` 与
`harness status` 共用同一份状态投影；编排层不得自行推导执行状态或就绪度。

## 4. 归档

### 4.1 就绪度七项判据

全部满足才成立，任一项不满足时必须指出是哪一项：

1. `tasks.md` 全部勾选。
2. `openspec validate <id> --strict` 通过。
3. `verification.json` 全部步骤为 `passed` 或 `waived`，`waived` 均有 `note`。
4. 步骤引用的每个证据路径真实存在。
5. `program.md` 的每条评估规则至少被一个已通过或已豁免的步骤覆盖。
6. 质量文档预筛已运行，被触发的条目均有人工理由。
7. 角色隔离校验通过。

人工写入的 lifecycle phase **只能收紧不能放宽**：人工更保守时采信人工，人工
更宽松时采信计算结果并报告矛盾。

### 4.2 自动归档

就绪度为真时自动执行 `harness close`，不要求人工逐个确认归档动作。

三条不可让步的边界：

- **`role: human` 步骤仍然阻塞。** 自动归档取消的是归档动作的人工确认，不是
  人工步骤本身。带 `pending` 人工步骤的 change 永远到不了自动归档。
- **门槛断言不被跳过。** 就绪度只驱动触发；`harness close` 仍跑完整门槛。
  就绪度实现有缺陷时，门槛是最后一道。
- **归档前建立回滚点。** 打 `harness/pre-close/<change>` tag，回滚是一条命令。
  成功推进 main，失败可退回——ratchet 模式。

### 4.3 何时该由人介入

自动归档不改变这三件事仍然属于人：**产品品味、风险承担、选择做什么。**
循环停在 `role: human` 步骤时，它在等的就是这三者之一。

## 5. 预算与停止

- 每次循环调用有迭代上限；达到上限时写 checkpoint 并停止，不得无限推进。
- 基础验证在起点就失败时，先修基础状态，不在坏的起点上叠新功能。
- 同一 change 的同一 task 连续失败达到阈值时停止并记为 blocked，不重复尝试。
- 循环不得绕过 OpenSpec：发现的问题若会改变产品行为、规格事实或评估规则，
  应先创建 candidate change，而不是直接改代码。

## 6. 每轮必须留下的东西

- `verification.json` 的步骤结论与真实存在的证据。
- `.harness/current.json` 的恢复点。
- 仍然损坏或未验证的内容、未解决的风险或 blocker。

没有可运行证据时不得声称完成；不得因为"代码已经写了"就勾掉任务；不得通过改
`tasks.md` 勾选或重写需求来隐藏未完成工作；不得为了"看起来完成"而删除或削弱
测试。
