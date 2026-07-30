#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把迁移前的三份流程文档合并为 program.md + verification.json。

  quality-contract.md ─┐
  verification.md      ├─> program.md + verification.json
  human-checks.md     ─┘

**不得推断结论**：既有 `passed` / `waived` 保持原状态、原操作者、原日期；新格式
要求而原记录缺失的字段一律标注「迁移时补录」，不得编造看似合理的内容——编造比
留空危险，因为它无法与真实结论区分。

迁移后仍缺必填字段的步骤会挡住该 change 的归档就绪度。这是有意的：它把「这个
change 该关还是该放弃」变成必须回答的问题，而不是继续躺着。

  python3 .harness/scripts/migrate-change-artifacts.py [<change>...]
        [--root <path>] [--all] [--dry-run] [--keep-legacy]

不带 change 且不带 --all 时只列出可迁移的 change，不做任何改动。
归档区（openspec/changes/archive/）永不迁移。
"""

import json
import os
import re
import sys

_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
if _SELF_DIR not in sys.path:
    sys.path.insert(0, _SELF_DIR)

import harness_verification as hv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(_SELF_DIR))

TODO = "迁移时补录"

RISK_LEVELS = ("low", "medium", "high", "critical")

# verification.md 的证据列里可能夹着说明文字，只取像仓库路径的片段。
EVIDENCE_RE = re.compile(r"`([^`]+)`|([A-Za-z0-9_.][A-Za-z0-9_./-]*/[A-Za-z0-9_./-]+)")

QUALITY_DOC_RE = re.compile(r"`([^`]+)`\s*[：:]\s*`?(updated|not-needed)`?", re.I)


def configure_root(root):
    global ROOT
    ROOT = os.path.abspath(root)
    hv.configure_root(ROOT)


def change_dir(change_id):
    return os.path.join(ROOT, "openspec", "changes", change_id)


def read(path):
    try:
        return hv.read_text(path)
    except OSError:
        return ""


def table_rows(text, heading, min_cells=5):
    """取某小节里全部表格的数据行。

    注意「全部」：旧解析器只读第一张表，第二张表的行静默消失。迁移必须把所有
    行都带过来，否则会在迁移这一步重演同一个失效。
    """
    rows = []
    lines = hv.section_lines(text, heading) if heading else \
        text.replace("\r\n", "\n").split("\n")
    in_table = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(set(c) <= set("-: ") and c for c in cells):
            in_table = True          # 分隔行：其后是数据行
            continue
        if not in_table:
            continue                  # 表头行
        if len(cells) >= min_cells:
            rows.append(cells)
    return rows


def bullets(text, heading):
    out = []
    for line in hv.section_lines(text, heading):
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        item = stripped.lstrip("-").strip()
        if item and item.lower() not in ("无", "无。", "n/a", "none", ""):
            out.append(item)
    return out


# 只有指向证据目录或确实存在于仓库里的路径才算证据。旧「证据」列里混着
# `Save/HexCellData.cs` 这类代码引用，把它们当成证据会凭空造出"证据缺失"。
EVIDENCE_ROOTS = (".harness/evidence/", ".harness/checkpoints/", "openspec/")


def extract_evidence(cell):
    """返回 (证据路径, 未被识别为证据的原文)。"""
    paths = []
    for m in EVIDENCE_RE.finditer(cell or ""):
        raw = (m.group(1) or m.group(2) or "").strip()
        if not raw or " " in raw or "/" not in raw:
            continue
        candidate = raw.rstrip("；;，,。")
        if candidate.startswith(EVIDENCE_ROOTS) or os.path.exists(
                os.path.join(ROOT, candidate)):
            paths.append(candidate)
    return paths


# 结论必须取「结果」列的开头 token，不能用子串搜索：`passed 8/8，0 failed`
# 和 `passed：...0 个 error CS/编译失败标记` 都含 failed/失败，子串匹配会把两条
# 通过的记录判成失败。仓库在 NEGATIVE_RE 那里已经踩过同一个坑。
RESULT_RE = (
    (re.compile(r"^\**\s*`?(passed|pass|ok|通过)\b", re.I), "passed"),
    (re.compile(r"^\**\s*`?(failed|fail|失败|未通过)\b", re.I), "failed"),
    (re.compile(r"^\**\s*`?(waived|豁免)\b", re.I), "waived"),
)


def classify_result(result):
    text = (result or "").strip().lstrip("|").strip()
    for pattern, status in RESULT_RE:
        if pattern.match(text):
            return status
    return "pending"


TASK_ID_RE = re.compile(r"^\d+(\.\d+)*([~-]\d+(\.\d+)*)?$")


def task_ids(cell):
    """从旧「对应任务」列取任务号。

    该列常混着散文（"Visibility 判定"、"地图生成"）。按分隔符切完就全塞进
    tasks，会让字段指向不存在的任务；只保留看起来像任务号的片段。
    """
    out = []
    for token in re.split(r"[、,，/\s]+", cell or ""):
        token = token.strip().rstrip("\\").strip()
        if token and TASK_ID_RE.match(token):
            out.append(token)
    return out


def parse_risk(text):
    for line in hv.section_lines(text, "风险等级"):
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        item = stripped.lstrip("-").strip().replace("**", "")
        label, sep, value = item.partition("：")
        if not sep:
            label, sep, value = item.partition(":")
        if not sep or label.strip() not in ("等级", "风险等级", "level"):
            continue
        for token in re.split(r"[\s`（(]", value):
            if token.strip().lower() in RISK_LEVELS:
                return token.strip().lower()
    return None


# --------------------------------------------------------------------------
# program.md
# --------------------------------------------------------------------------

def build_program(change_id, contract_text, rules):
    risk = parse_risk(contract_text)
    risk_note = "；".join(bullets(contract_text, "风险等级")) or ""
    observability = bullets(contract_text, "可观测性")
    rollback = bullets(contract_text, "回滚方式")
    skipped = bullets(contract_text, "AI 无法自行验证的内容")

    out = ["# Program — %s" % change_id, ""]
    out.append("> 本文件由 `migrate-change-artifacts.py` 从 "
               "`quality-contract.md` 迁移而来。标注「%s」的字段是原记录没有的"
               "内容，需要人工补齐后本 change 才能达到归档就绪。" % TODO)
    out.append("")

    out.append("## 风险等级")
    out.append("")
    if risk:
        out.append("- 等级：`%s`" % risk)
    else:
        out.append("- 等级：`low`")
        out.append("- **%s**：原 `quality-contract.md` 未声明有效等级，"
                   "此处按最低档迁移，请人工核对。" % TODO)
    if risk_note:
        out.append("- 风险说明：%s" % risk_note.replace("等级：`%s`" % risk, "").strip("；"))
    out.append("")

    if risk in ("medium", "high", "critical"):
        out.append("## 约束")
        out.append("")
        if observability or rollback:
            for item in observability:
                out.append("- 可观测性：%s" % item)
            for item in rollback:
                out.append("- 回滚方式：%s" % item)
        else:
            out.append("- **%s**：原记录未声明可观测性与回滚方式。" % TODO)
        out.append("")

    out.append("## 评估规则")
    out.append("")
    out.append("| id | 规则 | 通过依据 |")
    out.append("| --- | --- | --- |")
    for rule_id, description in rules:
        out.append("| `%s` | %s | 见 `verification.json` 中引用本规则的步骤 |"
                   % (rule_id, description))
    out.append("")

    if risk in ("high", "critical"):
        out.append("## 停止条件")
        out.append("")
        out.append("- 完成：全部步骤为 `passed` 或 `waived`，七项就绪判据成立。")
        out.append("- 阻塞：**%s**，原记录未声明阻塞条件。" % TODO)
        out.append("- 需人工：存在 `role: human` 且未作答的步骤。")
        out.append("")

    out.append("## 不验证及理由")
    out.append("")
    if skipped:
        for item in skipped:
            out.append("- %s" % item)
    else:
        out.append("- **%s**：原记录未声明不验证范围。" % TODO)
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------
# verification.json
# --------------------------------------------------------------------------

def migrated_identity():
    """迁移进来的结论没有评估身份可追溯，如实标注而不是编造一个。"""
    return {"agent": "pre-migration", "model": "unknown"}


def build_steps(verification_text, checks_text):
    steps = []
    counter = 1

    for cells in table_rows(verification_text, "验证记录"):
        command, result, evidence_cell, tasks_cell = cells[0], cells[1], cells[2], cells[3]
        note = cells[4] if len(cells) > 4 else ""
        if not command or command in ("命令或检查",):
            continue
        status = classify_result(result)
        evidence = extract_evidence(evidence_cell)
        # 证据列里没被识别成路径的内容不能丢，折进 note 保留原文。
        if evidence_cell and not evidence:
            note = ("%s（原证据列：%s）" % (note, evidence_cell)).strip("（）") \
                if note else "原证据列：%s" % evidence_cell
        step = {
            "id": "V%d" % counter,
            "role": "evaluator",
            "tasks": task_ids(tasks_cell),
            "rule": "R1",
            "how": command,
            "pass_when": "%s：原记录只保存了结果未声明通过标准。原结果：%s"
                         % (TODO, result[:120] or "（空）"),
            "fail_when": "%s：原记录未声明失败标准，请补充最可能出现的错法。"
                         % TODO,
            "status": status,
            "operator": None,
            "date": None,
            "evaluated_by": migrated_identity() if status != "pending" else None,
            "evidence": evidence,
            "note": note or None,
        }
        steps.append(step)
        counter += 1

    for cells in table_rows(checks_text, "检查项"):
        status, item, operator, date_value = cells[0], cells[1], cells[2], cells[3]
        note = cells[4] if len(cells) > 4 else ""
        status = status.strip().lower()
        if status not in hv.STATUSES:
            continue
        evidence = extract_evidence(note)
        step = {
            "id": "H%d" % (len(steps) - counter + 2 + len(
                [s for s in steps if s["role"] == "human"])),
            "role": "human",
            "tasks": [],
            "rule": "R2",
            "observe": "%s：原检查项未声明观察对象。原文：%s" % (TODO, item[:160]),
            "pass_when": "%s：原检查项未声明通过标准。原文：%s" % (TODO, item[:160]),
            "fail_when": "%s：原检查项未声明失败标准，请补充最可能出现的错法。"
                         % TODO,
            "needs_human_because": "%s：原记录未声明为何需要人。" % TODO,
            "status": status,
            "operator": operator or None,
            "date": date_value if hv.DATE_RE.match(date_value or "") else None,
            "evaluated_by": ({"agent": "human", "model": "human"}
                             if status in hv.TERMINAL_STATUSES else None),
            "evidence": evidence,
            "note": note or None,
        }
        steps.append(step)

    # 人工步骤的 id 单独连号，避免上面表达式在边界情况下产生重复。
    human_index = 1
    for step in steps:
        step["migrated"] = True
        if step["role"] == "human":
            step["id"] = "H%d" % human_index
            human_index += 1

    # 迁移进来的结论豁免了「必须有证据路径」，因此必须有人在归档前确认它们仍
    # 然成立——否则自动归档会把无人复核的历史结论直接关掉。
    concluded = [s for s in steps if s["status"] != "pending"]
    if concluded:
        steps.append({
            "id": "M1",
            "role": "human",
            "tasks": [],
            "rule": "R0",
            "observe": "本 change 的 verification.json 中 %d 条标记 migrated "
                       "的历史结论（迁移自 verification.md 与 human-checks.md）"
                       % len(concluded),
            "pass_when": "逐条看过后确认这些历史结论今天仍然成立，可以据此归档",
            "fail_when": "存在结论已经不成立的条目（依赖的代码已改、验证的行为"
                         "已变、或当时的通过其实没被真正验证）——请指出是哪一条",
            "needs_human_because": "旧格式没有记录逐条证据路径，AI 无法复算这些"
                                   "结论；豁免证据要求的代价就是这一次人工确认",
            "status": "pending",
            "operator": None,
            "date": None,
            "evaluated_by": None,
            "evidence": [],
            "note": None,
        })
    return steps


def build_quality_docs(verification_text):
    triggered = []
    for line in hv.section_lines(verification_text, "质量文档判断"):
        m = QUALITY_DOC_RE.search(line)
        if not m:
            continue
        doc, verdict = m.group(1), m.group(2).lower()
        if verdict != "updated":
            continue          # 未触发的条目不再产出说明文字：沉默即未触发。
        _label, _sep, reason = line.partition("理由：")
        triggered.append({"doc": doc,
                          "reason": reason.strip() or "%s：原记录未写理由。" % TODO})
    return triggered


def parse_conclusion(verification_text):
    for line in hv.section_lines(verification_text, "最终结论"):
        stripped = line.strip().lstrip("-").strip().strip("`")
        for token in ("passed", "failed", "pending", "waived"):
            if stripped.lower().startswith(token):
                # waived 不是记录级结论，收敛到 passed 之外的保守取值。
                return "passed" if token == "passed" else "pending"
    return "pending"


def build_verification(change_id, verification_text, checks_text, steps):
    env = {}
    for line in hv.section_lines(verification_text, "环境"):
        stripped = line.strip().lstrip("-").strip()
        label, sep, value = stripped.partition("：")
        if not sep:
            label, sep, value = stripped.partition(":")
        if not sep:
            continue
        key = {"日期": "date", "操作系统": "os", "Unity 版本": "unity"}.get(
            label.strip())
        if key:
            env[key] = value.strip() or None

    baseline = None
    for line in hv.section_lines(verification_text, "环境"):
        if "提交" in line:
            m = re.search(r"`?([0-9a-f]{7,40})`?", line)
            if m:
                baseline = m.group(1)

    # 旧记录只有一个全局日期，没有逐行日期。把它补给已得出结论但缺日期的步骤
    # 是如实迁移，不是编造：那确实是这批结论被记录的日期。
    for step in steps:
        if step["status"] != "pending" and not step.get("date"):
            step["date"] = env.get("date")

    return {
        "schema_version": 1,
        "change": change_id,
        "baseline_commit": baseline,
        "environment": {"os": env.get("os"), "unity": env.get("unity"),
                        "date": env.get("date")},
        "note": "由 migrate-change-artifacts.py 从 verification.md + "
                "human-checks.md 迁移。标注「%s」的字段是原记录没有的内容，"
                "需人工补齐；既有结论的状态与操作者未被改写。" % TODO,
        "steps": steps,
        "uncovered": bullets(verification_text, "未覆盖内容"),
        "quality_docs": {
            "prescreen_run": None,
            "triggered": build_quality_docs(verification_text),
        },
        "conclusion": {
            "status": parse_conclusion(verification_text),
            "note": "%s：迁移自旧记录，关闭前需按新判据复核。" % TODO,
        },
    }


# --------------------------------------------------------------------------
# 驱动
# --------------------------------------------------------------------------

def migratable():
    base = os.path.join(ROOT, "openspec", "changes")
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if name == "archive":
            continue          # 归档区是历史，永不迁移。
        if not os.path.isdir(os.path.join(base, name)):
            continue
        if hv.legacy_artifacts(name):
            out.append(name)
    return out


def migrate(change_id, dry_run=False, keep_legacy=False):
    directory = change_dir(change_id)
    contract_text = read(os.path.join(directory, "quality-contract.md"))
    verification_text = read(os.path.join(directory, "verification.md"))
    checks_text = read(os.path.join(directory, "human-checks.md"))

    steps = build_steps(verification_text, checks_text)
    rules = []
    if any(s["rule"] == "R0" for s in steps):
        rules.append(("R0", "迁移进来的历史结论经人工确认今天仍然成立"))
    if any(s["role"] != "human" for s in steps):
        rules.append(("R1", "自动验证按记录执行（%s：原记录无评估规则）" % TODO))
    if any(s["role"] == "human" and s["rule"] == "R2" for s in steps):
        rules.append(("R2", "人工验证按记录执行（%s：原记录无评估规则）" % TODO))
    if not rules:
        # 没有任何步骤时也要给出一条规则，否则新 change 无从起步。
        rules.append(("R1", "%s：原记录没有任何验证步骤，需要重新声明评估规则"
                      % TODO))

    program = build_program(change_id, contract_text, rules)
    verification = build_verification(change_id, verification_text,
                                      checks_text, steps)

    if dry_run:
        return {"change": change_id, "steps": len(steps),
                "human": sum(1 for s in steps if s["role"] == "human"),
                "written": False}

    with open(os.path.join(directory, "program.md"), "wb") as fh:
        fh.write(program.encode("utf-8"))
    body = json.dumps(verification, ensure_ascii=False, indent=2) + "\n"
    with open(os.path.join(directory, "verification.json"), "wb") as fh:
        fh.write(body.encode("utf-8"))

    removed = []
    if not keep_legacy:
        for name in hv.LEGACY_FILES:
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                os.remove(path)
                removed.append(name)

    return {"change": change_id, "steps": len(steps),
            "human": sum(1 for s in steps if s["role"] == "human"),
            "removed": removed, "written": True}


USAGE = """用法:
  migrate-change-artifacts.py [<change>...] [--all] [--dry-run]
                              [--keep-legacy] [--root <path>]
"""


def main(argv):
    args = list(argv[1:])
    root = None
    changes = []
    do_all = dry_run = keep_legacy = False
    while args:
        arg = args.pop(0)
        if arg == "--root":
            root = args.pop(0) if args else None
            if root is None:
                sys.stderr.write(USAGE)
                return 2
        elif arg.startswith("--root="):
            root = arg.split("=", 1)[1]
        elif arg == "--all":
            do_all = True
        elif arg == "--dry-run":
            dry_run = True
        elif arg == "--keep-legacy":
            keep_legacy = True
        elif arg.startswith("-"):
            sys.stderr.write(USAGE)
            return 2
        else:
            changes.append(arg)

    if root:
        if not os.path.isdir(root):
            sys.stderr.write("错误: --root 不是目录: %s\n" % root)
            return 2
        configure_root(root)

    available = migratable()
    if not changes and not do_all:
        print("可迁移的 change (%d)：" % len(available))
        for name in available:
            print("  %s  （%s）" % (name, "、".join(hv.legacy_artifacts(name))))
        print("\n加 --all 迁移全部，或指定 change 名。加 --dry-run 只预览。")
        return 0

    targets = available if do_all else changes
    for change_id in targets:
        if not os.path.isdir(change_dir(change_id)):
            sys.stderr.write("跳过：找不到 %s\n" % change_id)
            continue
        result = migrate(change_id, dry_run=dry_run, keep_legacy=keep_legacy)
        print("%-52s 步骤 %2d（人工 %d）%s"
              % (result["change"], result["steps"], result["human"],
                 "  [dry-run]" if dry_run else
                 "  删除 " + "、".join(result.get("removed") or []) or ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
