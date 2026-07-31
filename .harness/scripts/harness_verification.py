#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verification.json 与 program.md 的唯一解析、校验、写入与渲染实现。

`harness_checks.py`、`harness_state.py` 与 `dashboard/server.py` 全部委派到这里，
不得各自再写一份解析。历史上 human-checks.md 有两份解析器，两份都只读第一张
表格，导致第二张表的行对状态计数与关闭门槛同时不可见——本模块的存在就是为了
让那类失效不可能重现。

只依赖标准库。

  python3 .harness/scripts/harness_verification.py lint <change> [--root <p>]
  python3 .harness/scripts/harness_verification.py counts <change> [--root <p>]
  python3 .harness/scripts/harness_verification.py render <change> [--root <p>]
  python3 .harness/scripts/harness_verification.py set <change> <step> <status>
        [--by <operator>] [--date <YYYY-MM-DD>] [--note <text>]
        [--evidence <path>]... [--agent <name>] [--model <name>]
        [--expect <status>] [--root <p>]

退出码：0 通过；1 检查失败；2 用法错误；3 乐观锁冲突。
"""

import json
import os
import re
import sys
from datetime import date

_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_SELF_DIR))

SCHEMA_VERSION = 1

ROLES = ("evaluator", "human", "external")
STATUSES = ("pending", "passed", "failed", "waived")
TERMINAL_STATUSES = ("passed", "waived")

RISK_LEVELS = ("low", "medium", "high", "critical")

# 每个步骤都必须有的字段。
REQUIRED_ALWAYS = ("id", "role", "rule", "pass_when", "fail_when", "status")
# 按 role 追加的必填字段。
REQUIRED_BY_ROLE = {
    "evaluator": ("how",),
    "human": ("observe", "needs_human_because"),
    "external": ("how",),
}

# program.md 按风险等级要求的小节。
#「必须验证」与「不验证及理由」成对：只留否定的一半，读者无从判断覆盖面。
#「可观测性与回滚」与风险等级无关——出问题时去哪看、怎么退回，低风险一样要答。
SECTIONS_LOW = ("风险等级", "必须验证", "不验证及理由", "可观测性与回滚",
                "评估规则")
SECTIONS_HIGH = SECTIONS_LOW + ("约束", "停止条件")

# 整节内容都是这些说法时，视为占位填写而非真实内容。
PLACEHOLDER_VALUES = (
    "", "-", "—", "无", "无。", "不适用", "不适用。", "本轮无", "本轮无。",
    "n/a", "na", "none", "tbd", "待补", "待补。",
)

# 规则标识：表格首列或 bullet 开头的 `R1` / `C2` 这类短标识。
RULE_ID_RE = re.compile(r"^`?\*{0,2}([A-Z][A-Za-z0-9_-]{0,15})\*{0,2}`?$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

# 取反检测用：归一化时丢弃的标点与空白。
_PUNCT_RE = re.compile(
    r"[\s。，、；：,.;:!?！？「」『』\"'`（）()\[\]【】<>《》\-—_/\\|~*]+")

_LEADING_NEG = ("没有", "不能", "未能", "不是", "無", "not", "no",
                "不", "未", "没", "非", "否")
_TRAILING_NEG = ("不成立", "未成立", "未通过", "不通过", "不满足", "未满足",
                 "不符合", "未符合", "未达到", "不达到", "不达标", "为假",
                 "失败", "isfalse", "fails", "failed")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class VerificationFormatError(ValueError):
    """verification.json 无法作为规范记录解析。

    调用方 MUST 把它当作失败上报，MUST NOT 退化成"解析不到步骤所以没有未完成项"。
    """


class StepConflict(ValueError):
    """写入时步骤的当前状态与调用方预期不一致。"""


def configure_root(root):
    global ROOT
    ROOT = os.path.abspath(root)


def read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8")


def change_dir(change_id):
    return os.path.join(ROOT, "openspec", "changes", change_id)


def verification_path(change_id):
    return os.path.join(change_dir(change_id), "verification.json")


def program_path(change_id):
    return os.path.join(change_dir(change_id), "program.md")


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


# --------------------------------------------------------------------------
# 迁移前形态检测
# --------------------------------------------------------------------------

LEGACY_FILES = ("verification.md", "human-checks.md", "quality-contract.md")


def legacy_artifacts(change_id):
    """返回该 change 仍存在的迁移前文档。"""
    return [name for name in LEGACY_FILES
            if os.path.isfile(os.path.join(change_dir(change_id), name))]


# --------------------------------------------------------------------------
# program.md
# --------------------------------------------------------------------------

def section_lines(text, heading):
    """取某个 Markdown 小节的正文行（到下一个同级或更高级标题为止）。"""
    lines = text.replace("\r\n", "\n").split("\n")
    start = None
    level = None
    for idx, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if not m:
            continue
        if start is None and m.group(2).strip() == heading:
            start = idx + 1
            level = len(m.group(1))
        elif start is not None and len(m.group(1)) <= level:
            return lines[start:idx]
    return lines[start:] if start is not None else []


def _table_cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator_row(cells):
    return bool(cells) and all(set(c) <= set("-: ") and c for c in cells)


def parse_rules(text):
    """从「评估规则」小节取 {规则 id: 规则描述}。

    同时接受表格形态（首列是 id）与 bullet 形态（`- \\`R1\\` 描述`）。
    """
    rules = {}
    order = []
    for line in section_lines(text, "评估规则"):
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = _table_cells(stripped)
            if len(cells) < 2 or _is_separator_row(cells):
                continue
            m = RULE_ID_RE.match(cells[0])
            if not m or cells[0].lower() in ("id", "规则", "编号"):
                continue
            rule_id = m.group(1)
            if rule_id not in rules:
                order.append(rule_id)
            rules[rule_id] = cells[1]
        elif stripped.startswith("-"):
            item = stripped.lstrip("-").strip()
            head, _sep, rest = item.partition(" ")
            m = RULE_ID_RE.match(head.rstrip("：:"))
            if not m:
                continue
            rule_id = m.group(1)
            if rule_id not in rules:
                order.append(rule_id)
            rules[rule_id] = rest.strip()
    return rules, order


def parse_risk_level(text):
    """从「风险等级」小节取声明的等级。找不到时返回 None。"""
    for line in section_lines(text, "风险等级"):
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        item = stripped.lstrip("-").strip()
        label, sep, value = item.partition("：")
        if not sep:
            label, sep, value = item.partition(":")
        if not sep or label.strip().strip("*") not in ("等级", "风险等级", "level"):
            continue
        token = value.strip().strip("`").split()[0].strip("`，,。") if value.strip() else ""
        if token.lower() in RISK_LEVELS:
            return token.lower()
    return None


def _section_is_placeholder(text, heading):
    body = [l.strip() for l in section_lines(text, heading)]
    content = [l for l in body if l and not l.startswith(">")]
    if not content:
        return True
    for line in content:
        value = line.lstrip("-*").strip().strip("`").lower()
        # 表格行与多字段行不视为占位。
        if line.startswith("|"):
            return False
        if value not in PLACEHOLDER_VALUES:
            return False
    return True


def parse_program(change_id):
    """返回 {path, exists, text, risk_level, rules, rule_order, headings}。"""
    path = program_path(change_id)
    if not os.path.isfile(path):
        return {"path": rel(path), "exists": False, "text": "",
                "risk_level": None, "rules": {}, "rule_order": [],
                "headings": []}
    text = read_text(path)
    rules, order = parse_rules(text)
    headings = [m.group(2).strip()
                for m in (HEADING_RE.match(l)
                          for l in text.replace("\r\n", "\n").split("\n"))
                if m]
    return {"path": rel(path), "exists": True, "text": text,
            "risk_level": parse_risk_level(text), "rules": rules,
            "rule_order": order, "headings": headings}


# --------------------------------------------------------------------------
# verification.json
# --------------------------------------------------------------------------

def load_verification(change_id):
    """读并做最小结构断言。格式不合规时抛 VerificationFormatError。"""
    path = verification_path(change_id)
    if not os.path.isfile(path):
        legacy = legacy_artifacts(change_id)
        if legacy:
            raise VerificationFormatError(
                "%s 缺少 verification.json，仍是迁移前形态（%s）；"
                "运行 .harness/scripts/migrate-change-artifacts.py 迁移"
                % (change_id, "、".join(legacy)))
        raise VerificationFormatError("找不到 %s" % rel(path))

    try:
        with open(path, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
    except ValueError as exc:
        raise VerificationFormatError("%s 解析失败: %s" % (rel(path), exc))

    if not isinstance(data, dict):
        raise VerificationFormatError("%s 顶层必须是对象" % rel(path))
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise VerificationFormatError(
            "%s 的 schema_version 为 %r，本实现只支持 %d"
            % (rel(path), version, SCHEMA_VERSION))
    steps = data.get("steps")
    if not isinstance(steps, list):
        raise VerificationFormatError("%s 的 steps 必须是数组" % rel(path))
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            raise VerificationFormatError(
                "%s 的 steps[%d] 必须是对象" % (rel(path), idx))
    return data


def parse_statuses(blob):
    """从一段 verification.json 文本取 {step id: status}。

    供角色隔离检查读取历史修订用。**解析必须留在本模块**：调用方自己
    json.loads 再摸 id/status，就又造出了第二份解析实现——那正是首表截断
    bug 的成因。调用方只负责把 blob 取来。
    """
    if not blob:
        return {}
    try:
        data = json.loads(blob)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(s.get("id")): str(s.get("status") or "").lower()
            for s in data.get("steps", []) if isinstance(s, dict)}


def parse_step_identities(blob):
    """从一段 verification.json 文本取 {step id: evaluated_by.agent}。

    与 parse_statuses 一样，解析留在本模块；调用方只负责取 blob。
    """
    if not blob:
        return {}
    try:
        data = json.loads(blob)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for step in data.get("steps", []):
        if not isinstance(step, dict):
            continue
        identity = step.get("evaluated_by") or {}
        agent = identity.get("agent") if isinstance(identity, dict) else None
        out[str(step.get("id"))] = str(agent or "").strip().lower()
    return out


def parse_migrated_flags(blob):
    """从一段 verification.json 文本取 {step id: 是否为迁移步骤}。"""
    if not blob:
        return {}
    try:
        data = json.loads(blob)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(s.get("id")): bool(s.get("migrated"))
            for s in data.get("steps", []) if isinstance(s, dict)}


def step_counts(steps):
    counts = {name: 0 for name in STATUSES}
    for step in steps:
        status = str(step.get("status", "")).lower()
        if status in counts:
            counts[status] += 1
    return counts


def role_counts(steps):
    counts = {name: 0 for name in ROLES}
    for step in steps:
        role = str(step.get("role", "")).lower()
        if role in counts:
            counts[role] += 1
    return counts


def pending_human(steps):
    """未作答的人工步骤。带这类步骤的 change MUST NOT 达到归档就绪。"""
    return [step.get("id") for step in steps
            if str(step.get("role", "")).lower() == "human"
            and str(step.get("status", "")).lower() not in TERMINAL_STATUSES]


# --------------------------------------------------------------------------
# 取反检测
# --------------------------------------------------------------------------

def _normalize(text):
    return _PUNCT_RE.sub("", str(text or "")).lower()


def is_trivial_negation(pass_when, fail_when):
    """fail_when 是否只是 pass_when 的简单否定。

    取反等于没写：有用的失败标准描述"最可能出现的那种错法"，把注意力指向具体
    位置。这里只拦明显的机械取反，不试图判断语义质量。
    """
    p = _normalize(pass_when)
    f = _normalize(fail_when)
    if not p or not f:
        return False
    if f == p:
        return True
    for neg in _TRAILING_NEG:
        if f in (p + neg, neg + p):
            return True
    for neg in sorted(_LEADING_NEG, key=len, reverse=True):
        if f.startswith(neg) and f[len(neg):] == p:
            return True
    for neg in _LEADING_NEG + _TRAILING_NEG:
        if neg in f and f.replace(neg, "", 1) == p:
            return True
    return False


# --------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------

MIN_CRITERION_CHARS = 6


def _check_step_fields(step, idx, seen_ids, problems):
    label = step.get("id") or "steps[%d]" % idx

    for field in REQUIRED_ALWAYS:
        if not str(step.get(field) or "").strip():
            problems.append("步骤 %s 缺少必填字段 %s" % (label, field))

    step_id = str(step.get("id") or "").strip()
    if step_id:
        if step_id in seen_ids:
            problems.append("步骤标识 %s 重复；id 必须在文档内唯一" % step_id)
        seen_ids.add(step_id)

    role = str(step.get("role") or "").strip().lower()
    if role and role not in ROLES:
        problems.append("步骤 %s 的 role 为 %r，必须是 %s 之一"
                        % (label, step.get("role"), "/".join(ROLES)))
    for field in REQUIRED_BY_ROLE.get(role, ()):
        if not str(step.get(field) or "").strip():
            problems.append("步骤 %s 的 role 为 %s，缺少必填字段 %s"
                            % (label, role, field))

    status = str(step.get("status") or "").strip().lower()
    if status and status not in STATUSES:
        problems.append("步骤 %s 的 status 为 %r，必须是 %s 之一"
                        % (label, step.get("status"), "/".join(STATUSES)))

    pass_when = str(step.get("pass_when") or "").strip()
    fail_when = str(step.get("fail_when") or "").strip()
    if pass_when and len(_normalize(pass_when)) < MIN_CRITERION_CHARS:
        problems.append("步骤 %s 的 pass_when 过短，无法构成可证伪判据" % label)
    if fail_when and len(_normalize(fail_when)) < MIN_CRITERION_CHARS:
        problems.append("步骤 %s 的 fail_when 过短，无法描述具体错误表现" % label)
    if pass_when and fail_when and is_trivial_negation(pass_when, fail_when):
        problems.append(
            "步骤 %s 的 fail_when 只是 pass_when 的取反；取反等于没写，"
            "请描述最可能出现的那种错法" % label)

    if role == "human":
        observe = str(step.get("observe") or "").strip()
        if observe and len(_normalize(observe)) < MIN_CRITERION_CHARS:
            problems.append(
                "步骤 %s 的 observe 过短；观察对象必须具体到文件、场景、"
                "坐标或界面位置" % label)

    date_value = step.get("date")
    if date_value and not DATE_RE.match(str(date_value)):
        problems.append("步骤 %s 的 date 为 %r，必须是 YYYY-MM-DD"
                        % (label, date_value))

    return status, role, label


def _check_step_conclusion(step, label, status, problems):
    """已得出结论的步骤必须带证据与评估身份。"""
    if status not in TERMINAL_STATUSES and status != "failed":
        return

    evidence = step.get("evidence")
    if not isinstance(evidence, list):
        problems.append("步骤 %s 的 evidence 必须是数组" % label)
        evidence = []
    # migrated 步骤豁免"必须有证据路径"：旧格式从未记录过逐条证据路径，回溯
    # 要求它等于让全部存量 change 永久卡住。豁免只覆盖历史结论，新结论一律要
    # 证据；且每个迁移过的 change 另有一条人工步骤要求确认历史结论仍然成立。
    if not evidence and not step.get("migrated"):
        problems.append("步骤 %s 的状态为 %s 但没有引用任何证据" % (label, status))
    for item in evidence:
        path = str(item or "").strip()
        if not path:
            problems.append("步骤 %s 的 evidence 含空路径" % label)
            continue
        if not os.path.exists(os.path.join(ROOT, path)):
            problems.append("步骤 %s 引用了不存在的证据: %s" % (label, path))

    # operator 只对人工步骤必填：自动步骤的执行者身份由 evaluated_by 承载，
    # 两个字段都要求等于同一件事记两遍。
    if str(step.get("role") or "").lower() == "human" and not str(
            step.get("operator") or "").strip():
        problems.append("步骤 %s 的状态为 %s 但缺少 operator" % (label, status))
    if not str(step.get("date") or "").strip():
        problems.append("步骤 %s 的状态为 %s 但缺少 date" % (label, status))

    evaluated_by = step.get("evaluated_by")
    if not isinstance(evaluated_by, dict) or not str(
            evaluated_by.get("agent") or "").strip():
        problems.append(
            "步骤 %s 的状态为 %s 但缺少 evaluated_by.agent；"
            "评估身份是角色隔离校验的输入" % (label, status))
    elif not str(evaluated_by.get("model") or "").strip():
        problems.append("步骤 %s 的 evaluated_by 缺少 model" % label)

    if status == "waived" and not str(step.get("note") or "").strip():
        problems.append("步骤 %s 为 waived 但缺少豁免说明 note" % label)


def _check_program(change_id, steps, problems):
    """program.md 的分级结构、风险等级与规则双向覆盖。"""
    program = parse_program(change_id)
    if not program["exists"]:
        problems.append("找不到 %s；请从 .harness/templates/program.md 复制"
                        % rel(program_path(change_id)))
        return program

    risk = program["risk_level"]
    if risk is None:
        problems.append("program.md 的「风险等级」小节未声明有效等级（%s）"
                        % "/".join(RISK_LEVELS))
        required = SECTIONS_LOW
    elif risk in ("high", "critical"):
        required = SECTIONS_HIGH
    elif risk == "medium":
        required = SECTIONS_LOW + ("约束",)
    else:
        required = SECTIONS_LOW

    headings = set(program["headings"])
    for heading in required:
        if heading not in headings:
            problems.append("program.md 的风险等级为 %s，缺少必需小节「%s」"
                            % (risk, heading))

    # 分级的意义是"低风险不必写"，而不是"低风险写占位"。
    for heading in sorted(headings):
        if heading in ("风险等级", "评估规则"):
            continue
        if heading in required and _section_is_placeholder(program["text"], heading):
            problems.append(
                "program.md 的「%s」小节整节均为占位内容；"
                "请写入真实内容或按风险等级移除该小节" % heading)

    rules = program["rules"]
    if not rules:
        problems.append("program.md 的「评估规则」小节没有可识别的规则；"
                        "每条规则需要一个稳定标识供步骤引用")

    coverage = rule_coverage(program, steps)
    for rule_id, step_ids in sorted(coverage["unknown"].items()):
        problems.append("步骤 %s 引用的评估规则 %s 不存在于 program.md"
                        % ("/".join(str(s) for s in step_ids), rule_id))
    for rule_id in coverage["unreferenced"]:
        problems.append("评估规则 %s 没有任何步骤引用它；写了规则但没有步骤"
                        "覆盖等于没有评估" % rule_id)

    return program


def rule_coverage(program, steps):
    """评估规则与步骤的双向覆盖。

    `unreferenced` 是格式问题（写了规则却没有步骤引用它，lint 阶段就该拦）；
    `uncovered` 是就绪度问题（有步骤引用但尚未通过，实现期间正常存在）。
    两者必须分开，否则 lint 在实现完成前永远无法通过，「门槛随时可跑」就落空了。
    """
    rules = program["rules"]
    referenced = {}
    for step in steps:
        rule_id = str(step.get("rule") or "").strip()
        if not rule_id:
            continue
        referenced.setdefault(rule_id, []).append(step.get("id"))

    settled = {
        str(step.get("rule") or "").strip()
        for step in steps
        if str(step.get("status", "")).lower() in TERMINAL_STATUSES
    }

    return {
        "referenced": referenced,
        "unknown": {rule_id: step_ids
                    for rule_id, step_ids in referenced.items()
                    if rule_id not in rules},
        "unreferenced": [rule_id for rule_id in program["rule_order"]
                         if rule_id not in referenced],
        "uncovered": [rule_id for rule_id in program["rule_order"]
                      if rule_id in referenced and rule_id not in settled],
    }


def lint(change_id):
    """返回问题列表。空列表表示该 change 的验证记录与 program 契约成立。"""
    problems = []

    try:
        data = load_verification(change_id)
    except VerificationFormatError as exc:
        return [str(exc)]

    legacy = legacy_artifacts(change_id)
    if legacy:
        problems.append(
            "%s 同时存在 verification.json 与迁移前文档（%s）；"
            "两份事实来源必须收敛，请删除迁移前文档"
            % (change_id, "、".join(legacy)))

    steps = data["steps"]
    if not steps:
        problems.append("verification.json 没有任何步骤；至少要有一条明确结论")

    seen_ids = set()
    for idx, step in enumerate(steps):
        status, _role, label = _check_step_fields(step, idx, seen_ids, problems)
        _check_step_conclusion(step, label, status, problems)

        tasks = step.get("tasks")
        if tasks is not None and not isinstance(tasks, list):
            problems.append("步骤 %s 的 tasks 必须是数组" % label)

    declared = str(data.get("change") or "").strip()
    if declared and declared != change_id:
        problems.append("verification.json 的 change 字段为 %r，与目录名 %r 不一致"
                        % (declared, change_id))

    conclusion = data.get("conclusion")
    if not isinstance(conclusion, dict):
        problems.append("verification.json 缺少 conclusion 对象")
    else:
        status = str(conclusion.get("status") or "").lower()
        if status not in ("pending", "passed", "failed"):
            problems.append("conclusion.status 为 %r，必须是 pending/passed/failed"
                            % conclusion.get("status"))

    quality = data.get("quality_docs")
    if not isinstance(quality, dict):
        problems.append("verification.json 缺少 quality_docs 对象")
    else:
        triggered = quality.get("triggered")
        if triggered is not None and not isinstance(triggered, list):
            problems.append("quality_docs.triggered 必须是数组")
        else:
            # 只校验形状。「触发了但没写理由」是进度缺口不是格式缺陷，
            # 由 close 门槛的 check_quality_docs 单独报告并指名是哪一份文档；
            # 在这里再报一次只会让同一件事出现两行。
            for item in triggered or []:
                if not isinstance(item, dict):
                    problems.append("quality_docs.triggered 含非对象条目")

    _check_program(change_id, steps, problems)
    return problems


# --------------------------------------------------------------------------
# 就绪度（验证记录侧）
# --------------------------------------------------------------------------

SUMMARY_MAX = 96


def step_summary(step):
    """一行可执行摘要：不打开 change 目录也知道这一步要干什么。

    人工步骤取「看哪里 + 什么算通过」，自动步骤取执行方式——`harness ready` 只给
    步骤 id 时，人仍然得逐个打开目录才能判断，等于没有真正给出下一个动作。
    """
    role = str(step.get("role") or "").lower()
    if role == "human":
        parts = [step.get("observe"), step.get("pass_when")]
    else:
        parts = [step.get("how"), step.get("pass_when")]
    for raw in parts:
        text = " ".join(str(raw or "").split())
        # 迁移占位符没有信息量，跳过去找下一个字段。
        if text.startswith("迁移时补录"):
            text = text.split("原文：", 1)[-1].split("原结果：", 1)[-1].strip()
        if len(text) >= 8:
            return text[:SUMMARY_MAX] + ("…" if len(text) > SUMMARY_MAX else "")
    return "（该步骤未写明要求）"


def verification_readiness(change_id):
    """验证记录侧的就绪判据。

    只覆盖本模块拥有的判据。任务完成度、strict 校验与角色隔离由调用方补齐后
    合并——但归因规则一致：每个 blocker 带 owner（human / ai / external）。
    """
    blockers = []
    try:
        data = load_verification(change_id)
    except VerificationFormatError as exc:
        return {"ready": False, "blockers": [
            {"criterion": "verification-record", "detail": str(exc),
             "owner": "ai"}]}

    steps = data["steps"]
    if not steps:
        blockers.append({"criterion": "steps",
                         "detail": "verification.json 没有任何步骤",
                         "owner": "ai"})

    for step in steps:
        status = str(step.get("status") or "").lower()
        if status in TERMINAL_STATUSES:
            continue
        role = str(step.get("role") or "").lower()
        owner = {"human": "human", "external": "external"}.get(role, "ai")
        blockers.append({
            "criterion": "step-status",
            "detail": "步骤 %s（%s）状态为 %s：%s"
                      % (step.get("id"), role, status or "缺失",
                         step_summary(step)),
            "owner": owner,
        })

    program = parse_program(change_id)
    if program["exists"]:
        for rule_id in rule_coverage(program, steps)["uncovered"]:
            blockers.append({
                "criterion": "rule-coverage",
                "detail": "评估规则 %s 尚无已通过或已豁免的步骤覆盖" % rule_id,
                "owner": "ai",
            })

    quality = data.get("quality_docs") or {}
    if not str(quality.get("prescreen_run") or "").strip():
        blockers.append({"criterion": "quality-prescreen",
                         "detail": "质量文档预筛尚未运行", "owner": "ai"})
    for item in quality.get("triggered") or []:
        if isinstance(item, dict) and not str(item.get("reason") or "").strip():
            blockers.append({
                "criterion": "quality-prescreen",
                "detail": "被触发的质量文档条目 %s 缺少人工理由"
                          % item.get("doc"),
                "owner": "human",
            })

    conclusion = data.get("conclusion") or {}
    if str(conclusion.get("status") or "pending").lower() == "pending":
        blockers.append({"criterion": "conclusion",
                         "detail": "最终结论仍为 pending", "owner": "ai"})

    return {"ready": not blockers, "blockers": blockers}


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------

def _dump(path, data):
    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with open(path, "wb") as fh:
        fh.write(body.encode("utf-8"))


def find_step(data, step_id):
    for step in data["steps"]:
        if str(step.get("id")) == str(step_id):
            return step
    return None


def set_step(change_id, step_id, status, operator=None, date_value=None,
             note=None, evidence=None, agent=None, model=None,
             expected_status=None):
    """按 step id 寻址写入结论。

    用 id 而不是行号寻址：行号寻址需要携带原始整行做乐观锁，而 id 天然稳定。
    """
    status = str(status).lower()
    if status not in STATUSES:
        raise ValueError("status 必须是 %s 之一" % "/".join(STATUSES))

    path = verification_path(change_id)
    data = load_verification(change_id)
    step = find_step(data, step_id)
    if step is None:
        raise ValueError("找不到步骤 %s" % step_id)

    current = str(step.get("status") or "").lower()
    if expected_status is not None and current != str(expected_status).lower():
        raise StepConflict(
            "步骤 %s 的当前状态是 %s，与预期 %s 不一致；请刷新后重试"
            % (step_id, current, expected_status))

    role = str(step.get("role") or "").lower()
    if status == "waived" and not str(note or step.get("note") or "").strip():
        raise ValueError("标记 waived 必须同时给出豁免说明")

    step["status"] = status
    if operator is not None:
        step["operator"] = operator
    if note is not None:
        step["note"] = note
    if evidence is not None:
        step["evidence"] = list(evidence)
    if status == "pending":
        step["operator"] = None
        step["date"] = None
        step["evaluated_by"] = None
    else:
        step["date"] = date_value or step.get("date") or date.today().isoformat()
        if agent:
            step["evaluated_by"] = {"agent": agent, "model": model}
        elif role == "human" and not step.get("evaluated_by"):
            step["evaluated_by"] = {"agent": "human", "model": "human"}

    _dump(path, data)
    return step


def commit_step_record(change_id, step_id, status):
    """把验证记录单独提交。

    角色隔离断言要求评估结论不与实现改动同处一个提交。靠人记得分开提交是不
    够的——实测两次都是 `git add -A` 把记录扫进了实现提交。这里只 stage 这一
    个文件，从构造上保证分离。
    """
    import subprocess
    rel_path = rel(verification_path(change_id))
    try:
        add = subprocess.run(["git", "add", rel_path], cwd=ROOT,
                             capture_output=True, text=True, timeout=20)
        if add.returncode != 0:
            return False, (add.stderr or "").strip()
        staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--",
                                 rel_path], cwd=ROOT, timeout=20)
        if staged.returncode == 0:
            return False, "记录无变化，未提交"
        message = "Evaluator: %s %s -> %s" % (change_id, step_id, status)
        out = subprocess.run(["git", "commit", "-q", "-m", message, "--", rel_path],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return False, (out.stderr or out.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return True, message


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------

def render_markdown(change_id, full=False):
    """把 verification.json 渲染成 markdown 供人阅读。

    默认是**紧凑视图**：只给总览表、未完成/失败的步骤，以及全部人工步骤的判定
    契约——那是人真正要读来做决定的部分。已通过的自动步骤只在表里占一行。
    `full=True` 展开全部判定契约与迁移带入的原文。

    渲染结果 MUST NOT 被任何校验回读——事实来源只有 verification.json。
    """
    data = load_verification(change_id)
    env = data.get("environment") or {}
    counts = step_counts(data["steps"])

    out = ["# Verification — %s" % change_id, ""]
    out.append("> 本视图由 `harness verification %s --render` 从 "
               "`verification.json` 生成，仅供阅读；事实来源是 JSON。"
               % change_id)
    out.append("")
    out.append("- 基线提交：%s" % (data.get("baseline_commit") or "—"))
    out.append("- 日期：%s" % (env.get("date") or "—"))
    out.append("- 操作系统：%s" % (env.get("os") or "—"))
    out.append("- Unity：%s" % (env.get("unity") or "不适用"))
    out.append("- 步骤：%s"
               % "，".join("%s %d" % (name, counts[name]) for name in STATUSES))
    if data.get("note"):
        out.extend(["", data["note"]])

    table_steps = data["steps"] if full else [
        s for s in data["steps"]
        if str(s.get("status") or "").lower() in TERMINAL_STATUSES
        and str(s.get("role") or "").lower() != "human"]
    if table_steps:
        out.extend(["", "## 已完成的自动步骤" if not full else "## 步骤", "",
                    "| 步骤 | 角色 | 规则 | 状态 | 任务 | 证据 |",
                    "| --- | --- | --- | --- | --- | --- |"])
    for step in table_steps:
        evidence = step.get("evidence") or []
        out.append("| %s | %s | %s | %s | %s | %s |" % (
            step.get("id") or "—",
            step.get("role") or "—",
            step.get("rule") or "—",
            step.get("status") or "—",
            "、".join(str(t) for t in (step.get("tasks") or [])) or "—",
            "、".join("`%s`" % e for e in evidence) or "—",
        ))

    # 需要人读判定契约的只有两类：等他作答的人工步骤，和没通过的步骤。
    def needs_detail(step):
        if full:
            return True
        if str(step.get("role") or "").lower() == "human":
            return True
        return str(step.get("status") or "").lower() not in TERMINAL_STATUSES

    detailed = [s for s in data["steps"] if needs_detail(s)]
    hidden = len(data["steps"]) - len(detailed)
    out.extend(["", "## 判定契约", ""])
    if not full and hidden:
        out.append("> 已折叠 %d 个已通过的自动步骤；`--full` 展开全部。" % hidden)
        out.append("")
    for step in detailed:
        if full:
            out.append("### %s（%s）" % (step.get("id"), step.get("role")))
            out.append("")
            if step.get("how"):
                out.append("- 执行方式：`%s`" % step["how"])
            if step.get("observe"):
                out.append("- 观察对象：%s" % step["observe"])
            out.append("- 通过：%s" % (step.get("pass_when") or "—"))
            out.append("- 失败：%s" % (step.get("fail_when") or "—"))
            if step.get("needs_human_because"):
                out.append("- 需人理由：%s" % step["needs_human_because"])
            if step.get("note"):
                out.append("- 说明：%s" % step["note"])
            out.append("")
        else:
            # 紧凑模式：去掉每步的标题行与空行，字段并进带前缀的连续行。
            # 内容一个字不少，只是不再为每一步花掉三行版面。
            out.append("**%s**（%s，%s）"
                       % (step.get("id"), step.get("role"),
                          step.get("status") or "—"))
            if step.get("how"):
                out.append("- 执行：`%s`" % step["how"])
            if step.get("observe"):
                out.append("- 观察：%s" % step["observe"])
            out.append("- 通过：%s" % (step.get("pass_when") or "—"))
            out.append("- 失败：%s" % (step.get("fail_when") or "—"))
            if step.get("needs_human_because"):
                out.append("- 需人：%s" % step["needs_human_because"])
            if step.get("note"):
                out.append("- 说明：%s" % step["note"])
            out.append("")

    uncovered = data.get("uncovered") or []
    out.extend(["## 未覆盖内容", ""])
    out.extend(["- %s" % item for item in uncovered] or ["- 无。"])

    quality = data.get("quality_docs") or {}
    out.extend(["", "## 质量文档判断", ""])
    out.append("- 预筛运行：%s" % (quality.get("prescreen_run") or "未运行"))
    triggered = quality.get("triggered") or []
    if triggered:
        for item in triggered:
            out.append("- `%s`：%s" % (item.get("doc"), item.get("reason")))
    else:
        out.append("- 无触发条目（沉默即未触发）。")

    carried = data.get("migrated_sections") or []
    if carried and not full:
        out.extend(["", "## 迁移带入的原文", "",
                    "> %d 个小节原样带自旧格式；`--full` 展开。"
                    % len(carried)])
    elif carried:
        out.extend(["", "## 迁移带入的原文", "",
                    "> 以下小节在旧格式里没有结构化归宿，原样带过来，未作改写。"])
        for item in carried:
            out.extend(["", "### %s（原 %s）" % (item.get("heading"),
                                                item.get("source")), "",
                        item.get("text") or ""])

    conclusion = data.get("conclusion") or {}
    out.extend(["", "## 最终结论", "",
                "- `%s`" % (conclusion.get("status") or "pending")])
    if conclusion.get("note"):
        out.append("- %s" % conclusion["note"])
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

USAGE = """用法:
  harness_verification.py lint <change> [--root <path>]
  harness_verification.py counts <change> [--root <path>]
  harness_verification.py ready <change> [--root <path>]
  harness_verification.py render <change> [--full] [--root <path>]
  harness_verification.py set <change> <step> <status> [--by <operator>]
        [--date <YYYY-MM-DD>] [--note <text>] [--evidence <path>]...
        [--agent <name>] [--model <name>] [--expect <status>] [--commit]
        [--root <path>]
"""

COMMANDS = ("lint", "counts", "render", "ready", "set")


def main(argv):
    args = list(argv[1:])
    if not args or args[0] not in COMMANDS:
        sys.stderr.write(USAGE)
        return 2
    command = args.pop(0)

    root = None
    positional = []
    options = {"evidence": []}
    single_value = {"--by": "by", "--date": "date", "--note": "note",
                    "--agent": "agent", "--model": "model",
                    "--expect": "expect"}
    while args:
        arg = args.pop(0)
        if arg == "--root":
            root = args.pop(0) if args else None
            if root is None:
                sys.stderr.write(USAGE)
                return 2
        elif arg.startswith("--root="):
            root = arg.split("=", 1)[1]
        elif arg == "--full":
            options["full"] = True
        elif arg == "--commit":
            options["commit"] = True
        elif arg == "--evidence":
            if not args:
                sys.stderr.write(USAGE)
                return 2
            options["evidence"].append(args.pop(0))
        elif arg in single_value:
            if not args:
                sys.stderr.write(USAGE)
                return 2
            options[single_value[arg]] = args.pop(0)
        elif arg.startswith("-"):
            sys.stderr.write(USAGE)
            return 2
        else:
            positional.append(arg)

    expected = 3 if command == "set" else 1
    if len(positional) != expected:
        sys.stderr.write(USAGE)
        return 2

    if root:
        if not os.path.isdir(root):
            sys.stderr.write("错误: --root 不是目录: %s\n" % root)
            return 2
        configure_root(root)

    change_id = positional[0]

    if command == "lint":
        problems = lint(change_id)
        if problems:
            sys.stderr.write("错误: %s 的验证记录检查未通过\n" % change_id)
            for problem in problems:
                sys.stderr.write("  - %s\n" % problem)
            return 1
        print("==> 验证记录检查通过: %s" % change_id)
        return 0

    if command == "counts":
        try:
            data = load_verification(change_id)
        except VerificationFormatError as exc:
            sys.stderr.write("错误: %s\n" % exc)
            return 1
        print(json.dumps({
            "change": change_id,
            "status_counts": step_counts(data["steps"]),
            "role_counts": role_counts(data["steps"]),
            "pending_human": pending_human(data["steps"]),
        }, ensure_ascii=False, indent=2))
        return 0

    if command == "ready":
        result = verification_readiness(change_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 1

    if command == "render":
        try:
            sys.stdout.write(render_markdown(change_id,
                                             full=bool(options.get("full"))))
        except VerificationFormatError as exc:
            sys.stderr.write("错误: %s\n" % exc)
            return 1
        return 0

    step_id, status = positional[1], positional[2]
    try:
        step = set_step(
            change_id, step_id, status,
            operator=options.get("by"), date_value=options.get("date"),
            note=options.get("note"),
            evidence=options["evidence"] or None,
            agent=options.get("agent"), model=options.get("model"),
            expected_status=options.get("expect"))
    except StepConflict as exc:
        sys.stderr.write("冲突: %s\n" % exc)
        return 3
    except (VerificationFormatError, ValueError) as exc:
        sys.stderr.write("错误: %s\n" % exc)
        return 1
    print("==> %s 的步骤 %s 已置为 %s" % (change_id, step_id, step["status"]))
    if options.get("commit"):
        ok, detail = commit_step_record(change_id, step_id, step["status"])
        print("==> %s%s" % ("已单独提交验证记录: " if ok else "未提交: ", detail))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
