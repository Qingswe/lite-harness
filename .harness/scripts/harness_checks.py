#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harness verify / close 的门槛检查。

放在 Python 里而不是各平台脚本里，保证 Windows 与 Unix 判定完全一致。
验证记录的解析全部委派 `harness_verification.py`，本文件不自带第二份实现。
只依赖标准库。

  python3 .harness/scripts/harness_checks.py verification <change> [--root <p>]
  python3 .harness/scripts/harness_checks.py roles <change> [--root <path>]
  python3 .harness/scripts/harness_checks.py doc-refs [--root <path>]
  python3 .harness/scripts/harness_checks.py skills [--root <path>]
  python3 .harness/scripts/harness_checks.py probe-needed <change> [--root <p>]
  python3 .harness/scripts/harness_checks.py risk-floor <change> [--root <p>]

退出码：0 通过；1 检查失败；2 用法错误。
probe-needed 用退出码表达判定：0 = 需要 Unity 探针，1 = 不需要。
"""

import hashlib
import json
import os
import re
import subprocess
import sys

_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
if _SELF_DIR not in sys.path:
    sys.path.insert(0, _SELF_DIR)

import harness_state  # noqa: E402
import harness_verification as hv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(_SELF_DIR))

# 规则与流程文档：这些文件里的仓库内路径引用必须真实存在。
# 列表是超集：不存在的条目会被跳过，因此项目可以拥有额外文档而不必改本文件。
REFERENCE_DOCS = (
    "CLAUDE.md",
    "AGENTS.md",
    "index.md",
    "clean-state-checklist.md",
    "docs/quality/README.md",
    "docs/quality/scorecard.md",
    "docs/knowledge/agent-unity-subproject-priority.md",
    ".harness/program.md",
)

# 反引号里的仓库根相对路径。只校验含 "/" 的引用：裸文件名（`tasks.md` 等）
# 是 change 目录内的相对引用，脱离上下文无法判定。
PATH_RE = re.compile(r"`([A-Za-z0-9_.][A-Za-z0-9_./-]*/[A-Za-z0-9_./-]*)`")

# 含占位符或通配的引用不作为真实路径校验。
PLACEHOLDER_RE = re.compile(r"[<>*?{}]|\.\.\.|＜|＞")

# 存放 skill 定义的客户端配置目录（相对仓库根）。
SKILL_ROOTS = (
    ".agents", ".claude", ".codex", ".cursor", ".factory", ".gemini", ".zcode",
    "UnityProject/.agents", "UnityProject/.claude", "UnityProject/.codex",
    "UnityProject/.cursor", "UnityProject/.factory", "UnityProject/.gemini",
    "UnityProject/.zcode",
)

# 表示"不需要"的说法。必须出现在条目开头：用子串匹配会把"确认无
# NotSupportedException"这类正面要求误判为不需要。
# 「无」后面不能紧跟汉字，否则"无论如何都要跑"会被误判。
NEGATIVE_RE = re.compile(
    r"^(不需要|不要求|不适用|不涉及|不执行|不运行|无需|无强制|n/?a|none|[-—])"
    r"|^无(?![一-鿿])",
    re.IGNORECASE)

# 「不验证及理由」小节里若条目写的其实是"要执行"，保守当作需要探针。
POSITIVE_RE = re.compile(r"^(必须|需要|要求|执行|运行|跑)", re.IGNORECASE)

# 判断某条内容是否与 Unity 验证相关。
UNITY_HINT_RE = re.compile(
    r"EditMode|PlayMode|Unity|环境探针|init\.(sh|ps1)", re.IGNORECASE)

# 高影响路径：触及这些的变更风险等级不低于 high，自评不得下调。
HIGH_RISK_PATTERNS = (
    ("Prefab", re.compile(r"\.prefab$", re.IGNORECASE)),
    ("shader", re.compile(r"\.(shader|shadergraph|compute|hlsl|cginc)$",
                          re.IGNORECASE)),
    ("渲染管线", re.compile(r"(RenderPipeline|URP|HDRP|renderer[- ]?data)",
                            re.IGNORECASE)),
    ("序列化格式", re.compile(r"\.(asset|unity|mat|controller|playable)$",
                              re.IGNORECASE)),
    ("存档 schema", re.compile(r"(save|savedata|savegame|persist)",
                               re.IGNORECASE)),
)

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def configure_root(root):
    global ROOT
    ROOT = os.path.abspath(root)
    # 解析器与状态层必须跟着换根，否则几处会各看一个仓库。
    hv.configure_root(ROOT)
    harness_state.configure_root(ROOT)


def read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8")


def section_lines(text, heading):
    """取某个 Markdown 小节的正文行（到下一个同级或更高级标题为止）。"""
    lines = text.replace("\r\n", "\n").split("\n")
    start = None
    level = None
    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not m:
            continue
        if start is None and m.group(2).strip() == heading:
            start = idx + 1
            level = len(m.group(1))
        elif start is not None and len(m.group(1)) <= level:
            return lines[start:idx]
    return lines[start:] if start is not None else []


# --------------------------------------------------------------------------
# 验证记录：正向断言
# --------------------------------------------------------------------------

def check_verification(change_id):
    """断言验证记录给出了明确结论，而不是"没匹配到 pending 就放行"。

    解析全部委派 harness_verification：历史上人工检查有两份解析器，两份都只读
    第一张表格，第二张表的行对状态计数与关闭门槛同时不可见。委派保证唯一实现。
    """
    problems = list(hv.lint(change_id))
    if problems:
        return problems

    data = hv.load_verification(change_id)
    steps = data["steps"]
    if not steps:
        return ["verification.json 没有任何步骤；至少要有一条明确结论"]

    for step in steps:
        status = str(step.get("status") or "").lower()
        if status not in hv.TERMINAL_STATUSES:
            problems.append(
                "步骤 %s 状态为 %s，必须是 passed 或 waived：%s"
                % (step.get("id"), status or "缺失",
                   str(step.get("pass_when") or "")[:40]))
    return problems


# --------------------------------------------------------------------------
# 文档引用路径存在性
# --------------------------------------------------------------------------

def _is_field_accessor(raw):
    """`.harness/current.json.active_change` 这类字段访问器不是路径。"""
    parts = raw.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:cut])
        if os.path.isfile(os.path.join(ROOT, prefix)):
            return True
    return False


def _repo_anchored(raw):
    """只校验以仓库根下真实存在的顶层条目开头的引用。

    `specs/`、`Assets/Mirror/` 这类是相对于 change 目录或 Unity 工程的片段，
    脱离上下文无法判定，不参与校验。
    """
    head = raw.split("/", 1)[0]
    return os.path.exists(os.path.join(ROOT, head))


def check_doc_references():
    problems = []
    for doc in REFERENCE_DOCS:
        full = os.path.join(ROOT, doc)
        if not os.path.isfile(full):
            continue
        for raw in sorted(set(PATH_RE.findall(read_text(full)))):
            if PLACEHOLDER_RE.search(raw) or not _repo_anchored(raw):
                continue
            target = os.path.join(ROOT, raw.rstrip("/"))
            if os.path.exists(target) or _is_field_accessor(raw):
                continue
            problems.append("%s 引用了不存在的路径: %s" % (doc, raw))
    return problems


# --------------------------------------------------------------------------
# skill 定义跨目录一致性
# --------------------------------------------------------------------------

def _digest(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def collect_skill_files():
    """返回 {(skill 名, skill 内相对路径): {摘要: [所在目录]}}。"""
    found = {}
    for skill_root in SKILL_ROOTS:
        base = os.path.join(ROOT, skill_root, "skills")
        if not os.path.isdir(base):
            continue
        for skill_name in sorted(os.listdir(base)):
            skill_dir = os.path.join(base, skill_name)
            if not os.path.isdir(skill_dir):
                continue
            for cur, _dirs, files in os.walk(skill_dir):
                if "__pycache__" in cur:
                    continue
                for name in sorted(files):
                    full = os.path.join(cur, name)
                    inner = os.path.relpath(full, skill_dir).replace("\\", "/")
                    key = (skill_name, inner)
                    found.setdefault(key, {}).setdefault(
                        _digest(full), []).append(skill_root)
    return found


def check_skill_consistency():
    problems = []
    for (skill_name, inner), by_digest in sorted(collect_skill_files().items()):
        if len(by_digest) > 1:
            variants = "; ".join(
                "%s -> %s" % (digest[:8], ", ".join(sorted(dirs)))
                for digest, dirs in sorted(by_digest.items()))
            problems.append("skill %s 的 %s 在不同客户端目录中分叉：%s"
                            % (skill_name, inner, variants))
    return problems


# --------------------------------------------------------------------------
# 环境探针是否由质量契约要求
# --------------------------------------------------------------------------

def requires_unity_probe(change_id):
    """判断本变更是否需要 Unity 探针。

    两个来源：`verification.json` 里存在 Unity 相关步骤（需要），或 `program.md`
    的「不验证及理由」显式声明不跑（不需要）。两者都没有时保守执行探针——这逼
    作者把决定写下来，而不是靠沉默省掉验证。
    """
    program = hv.parse_program(change_id)
    if not program["exists"]:
        return True, "找不到 program.md，保守执行探针"

    try:
        steps = hv.load_verification(change_id)["steps"]
    except hv.VerificationFormatError:
        return True, "验证记录无法解析，保守执行探针"

    for step in steps:
        blob = " ".join(str(step.get(field) or "")
                        for field in ("how", "observe", "pass_when"))
        if UNITY_HINT_RE.search(blob):
            return True, "验证记录中存在 Unity 相关步骤（%s）" % step.get("id")

    for line in hv.section_lines(program["text"], "不验证及理由"):
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        item = stripped.lstrip("-").strip().replace("**", "")
        if not UNITY_HINT_RE.search(item.split("：")[0].split(":")[0]):
            continue
        _label, sep, value = item.partition("：")
        if not sep:
            _label, sep, value = item.partition(":")
        if POSITIVE_RE.match(value.strip().lstrip("`")):
            return True, "「不验证及理由」中的 Unity 条目写的是要执行，保守执行探针"
        return False, "program.md 声明不执行 EditMode/PlayMode/环境探针"

    return True, "program.md 未声明 Unity 验证范围，保守执行探针"


# --------------------------------------------------------------------------
# 风险等级下限
# --------------------------------------------------------------------------

def changed_paths(change_id):
    """本 change 触及的路径。

    优先用 verification.json 记录的 baseline_commit 与工作区比较——只看未提交
    改动会让已经提交的实现从下限计算里消失，那正是下限最需要生效的时候。
    """
    baseline = None
    try:
        baseline = hv.load_verification(change_id).get("baseline_commit")
    except hv.VerificationFormatError:
        pass

    candidates = []
    if baseline:
        candidates.append(["diff", "--name-only", baseline])
    candidates.append(["diff", "--name-only", "HEAD"])

    for args in candidates:
        out = _git(args)
        if out is None:
            continue
        paths = [l.strip() for l in out.splitlines() if l.strip()]
        if paths:
            return paths
    return []


# 下限衡量的是实现风险，文档与产物不参与计算。
NON_IMPLEMENTATION_RE = re.compile(
    r"^(openspec/|docs/|\.harness/evidence/|\.harness/checkpoints/|"
    r"README\.md$|CLAUDE\.md$|AGENTS\.md$|index\.md$)")


def risk_floor(paths):
    """按触及路径计算风险等级下限，返回 (等级, 触发原因列表)。"""
    reasons = []
    for path in paths:
        if NON_IMPLEMENTATION_RE.match(path):
            continue
        for label, pattern in HIGH_RISK_PATTERNS:
            if pattern.search(path):
                reasons.append("%s: %s" % (label, path))
                break
    return ("high" if reasons else "low"), reasons


def check_risk_floor(change_id, paths=None):
    program = hv.parse_program(change_id)
    if not program["exists"]:
        return ["找不到 %s" % hv.rel(hv.program_path(change_id))]

    declared = program["risk_level"]
    if declared is None:
        return ["program.md 未声明有效的风险等级"]

    floor, reasons = risk_floor(changed_paths(change_id)
                                if paths is None else paths)
    if RISK_ORDER[declared] < RISK_ORDER[floor]:
        detail = "；".join(reasons[:5])
        return ["program.md 声明风险等级为 %s，低于机械下限 %s。触发下限的路径："
                "%s。自评不得低于下限，人工可上调不可下调。"
                % (declared, floor, detail)]
    return []


# --------------------------------------------------------------------------
# 角色隔离
# --------------------------------------------------------------------------

def _git(args):
    try:
        out = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True,
                             text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _statuses_at(rev, relpath):
    """取某个修订下 verification.json 的 {step id: status}。

    只负责把 blob 取来；解析委派 harness_verification.parse_statuses，本文件
    不自带第二份实现。
    """
    return hv.parse_statuses(_git(["show", "%s:%s" % (rev, relpath)]))


def _is_implementation_path(path, change_id):
    """实现文件 = 既不是本 change 的产物，也不是证据。"""
    if path.startswith("openspec/changes/%s/" % change_id):
        return False
    if path.startswith(".harness/evidence/"):
        return False
    if path.startswith(".harness/checkpoints/"):
        return False
    return True


def check_role_isolation(change_id, generator_identity=None):
    """断言实现与评估没有由同一次提交、同一身份完成。

    这是自动归档下唯一挡住自批作业的机械检查，因此它只依赖仓库里可复查的事实：
    提交内容与记录下来的评估身份，不依赖执行体自述。
    """
    problems = []
    relpath = "openspec/changes/%s/verification.json" % change_id

    # 提交级断言需要 git；身份校验不需要。拿不到 git 时只跳过前者，
    # 不能连身份校验一起放弃——否则在任何非 git 上下文里这道闸门会静默消失。
    log = _git(["log", "--format=%H", "--", relpath]) or ""

    for commit in [l.strip() for l in log.splitlines() if l.strip()]:
        before = _statuses_at(commit + "^", relpath)
        after = _statuses_at(commit, relpath)
        # 人工作答/豁免的步骤不受提交级断言约束：这条断言防的是「实现者给自己
        # 的产出打分」，而人记录自己的决定不属于那件事。身份校验早就豁免了
        # agent == "human"，两处必须一致，否则同一件事在两道闸门下结论相反。
        identities = hv.parse_step_identities(_git(["show", "%s:%s" % (commit, relpath)]))
        promoted = [sid for sid, status in after.items()
                    if status in hv.TERMINAL_STATUSES
                    and before.get(sid) != status
                    and identities.get(sid) != "human"]
        if not promoted:
            continue
        names = _git(["show", "--name-only", "--format=", commit]) or ""
        touched = [n.strip() for n in names.splitlines() if n.strip()]
        impl = [n for n in touched if _is_implementation_path(n, change_id)]
        if impl:
            problems.append(
                "提交 %s 同时把步骤 %s 置为终态并修改了实现文件（%s）；"
                "实现与评估不得由同一次提交完成"
                % (commit[:8], "/".join(sorted(promoted)),
                   "、".join(sorted(impl)[:3])))

    try:
        steps = hv.load_verification(change_id)["steps"]
    except hv.VerificationFormatError as exc:
        return problems + [str(exc)]

    generator_identity = generator_identity or {}
    gen_agent = str(generator_identity.get("agent") or "").strip().lower()
    gen_model = str(generator_identity.get("model") or "").strip().lower()

    for step in steps:
        if str(step.get("status") or "").lower() not in hv.TERMINAL_STATUSES:
            continue
        identity = step.get("evaluated_by") or {}
        agent = str(identity.get("agent") or "").strip().lower()
        model = str(identity.get("model") or "").strip().lower()
        if not agent:
            problems.append("步骤 %s 已得出结论但没有记录评估身份"
                            % step.get("id"))
            continue
        if agent == "human":
            continue
        if gen_agent and agent == gen_agent:
            problems.append(
                "步骤 %s 的评估身份 %s 与本 change 的实现身份相同；"
                "实现者不得评估自身产出" % (step.get("id"), agent))
        elif gen_model and model and model == gen_model:
            problems.append(
                "步骤 %s 的评估模型 %s 与实现模型相同；模型是自己输出的最佳"
                "辩护律师，评估必须换模型" % (step.get("id"), model))
    return problems


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# 关闭门槛：lint 与 close 共用的唯一实现
# --------------------------------------------------------------------------

REQUIRED_CHANGE_FILES = (
    ("tasks.md", None),
    ("program.md", ".harness/templates/program.md"),
    ("verification.json", ".harness/templates/verification.json"),
)


def check_change_files(change_id):
    problems = []
    change_dir = os.path.join(ROOT, "openspec", "changes", change_id)
    if not os.path.isdir(change_dir):
        return ["找不到变更目录: openspec/changes/%s" % change_id]
    for name, template in REQUIRED_CHANGE_FILES:
        if not os.path.isfile(os.path.join(change_dir, name)):
            hint = "，请从 %s 复制" % template if template else ""
            problems.append("缺少 openspec/changes/%s/%s%s"
                            % (change_id, name, hint))
    for name in hv.LEGACY_FILES:
        if os.path.isfile(os.path.join(change_dir, name)):
            problems.append(
                "openspec/changes/%s/%s 是迁移前形态，必须迁移后删除；"
                "运行 .harness/scripts/migrate-change-artifacts.py"
                % (change_id, name))
    return problems


def check_tasks_complete(change_id):
    path = os.path.join(ROOT, "openspec", "changes", change_id, "tasks.md")
    if not os.path.isfile(path):
        return ["找不到 openspec/changes/%s/tasks.md" % change_id]
    harness_state.configure_root(ROOT)
    items = [t for t in harness_state.parse_tasks(path) if t["type"] == "task"]
    unchecked = [t for t in items if not t["checked"]]
    if not items:
        return ["tasks.md 没有任何任务条目"]
    if unchecked:
        return ["tasks.md 仍有 %d 项未完成，最靠前的是：%s"
                % (len(unchecked), unchecked[0]["text"][:60])]
    return []


def check_quality_docs(change_id):
    """质量文档判断改为预筛结果：默认无需更新，被触发的条目必须有人工理由。"""
    try:
        data = hv.load_verification(change_id)
    except hv.VerificationFormatError as exc:
        return [str(exc)]
    quality = data.get("quality_docs") or {}
    if not str(quality.get("prescreen_run") or "").strip():
        return ["verification.json 的 quality_docs.prescreen_run 为空；"
                "请先运行质量文档预筛。未触发的条目不需要撰写说明，"
                "但预筛本身必须真的跑过"]
    problems = []
    for item in quality.get("triggered") or []:
        if not isinstance(item, dict):
            problems.append("quality_docs.triggered 含非对象条目")
            continue
        if not str(item.get("reason") or "").strip():
            problems.append("质量文档条目 %s 被预筛判定为触发，但缺少人工理由"
                            % item.get("doc"))
    return problems


def close_gate(change_id):
    """close 与 lint 共用的门槛断言。两者 MUST 调用本函数，不得各写一份。"""
    problems = list(check_change_files(change_id))
    if problems:
        return problems
    problems.extend(check_tasks_complete(change_id))
    problems.extend(check_verification(change_id))
    problems.extend(check_risk_floor(change_id))
    problems.extend(check_role_isolation(change_id,
                                         generator_identity(change_id)))
    problems.extend(check_quality_docs(change_id))
    return problems


# --------------------------------------------------------------------------
# 就绪度与下一个动作
# --------------------------------------------------------------------------

def _strict_blockers(change_id):
    if not _which("openspec"):
        return [{"criterion": "openspec-strict",
                 "detail": "未找到 openspec 命令，无法验证 strict 校验",
                 "owner": "external"}]
    try:
        out = subprocess.run(["openspec", "validate", change_id, "--strict"],
                             cwd=ROOT, capture_output=True, text=True,
                             timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return [{"criterion": "openspec-strict",
                 "detail": "strict 校验无法执行: %s" % exc, "owner": "external"}]
    if out.returncode != 0:
        detail = (out.stdout or out.stderr or "").strip().splitlines()
        return [{"criterion": "openspec-strict",
                 "detail": "strict 校验失败：%s" % (detail[0] if detail else ""),
                 "owner": "ai"}]
    return []


def _which(name):
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(path, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def change_readiness(change, run_strict=True):
    """七项判据合并。change 是 harness_state.build_change 的结果。

    与 harness status 共用同一份状态投影：调用方传入的 change 就是投影产物，
    这里不重新扫描仓库，也不新建第二份推导逻辑。
    """
    change_id = change["id"]
    blockers = list(harness_state.compute_readiness(change)["blockers"])

    # 就绪度必须包含格式门槛，否则会出现「ready 说可以关、lint 说不行」的分裂：
    # 自动归档会先打 tag 再在 close 的门槛处中止，留下一个半途状态。
    for problem in hv.lint(change_id):
        blockers.append({"criterion": "lint", "detail": problem, "owner": "ai"})

    if run_strict:
        blockers.extend(_strict_blockers(change_id))

    for problem in check_role_isolation(change_id,
                                        generator_identity(change_id)):
        blockers.append({"criterion": "role-isolation", "detail": problem,
                         "owner": "ai"})
    for problem in check_risk_floor(change_id):
        blockers.append({"criterion": "risk-floor", "detail": problem,
                         "owner": "ai"})

    return {"change": change_id, "ready": not blockers, "blockers": blockers}


OWNER_LABEL = {"human": "人", "ai": "AI", "external": "外部"}


def build_ready_report(run_strict=True):
    harness_state.configure_root(ROOT)
    state = harness_state.build_state()
    # 覆盖全部可发现的 change，不只是 current.json 里的候选：一个磁盘上真实存在
    # 且已就绪的 change 若没被登记进候选，会对 ready 完全不可见，从而永远触发
    # 不到自动归档。成员关系的漂移由 detect_drift 报告，不该在这里吞掉。
    changes = list(state["changes"])

    ready, blocked = [], []
    for change in changes:
        result = change_readiness(change, run_strict=run_strict)
        if result["ready"]:
            ready.append({"change": change["id"],
                          "depends_on": change["recovery"].get("depends_on") or []})
        else:
            first = result["blockers"][0]
            blocked.append({
                "change": change["id"],
                "criterion": first["criterion"],
                "next_action": first["detail"],
                "owner": first["owner"],
                "blocker_count": len(result["blockers"]),
            })

    return {"ready": _order_by_dependency(ready), "blocked": blocked}


def _order_by_dependency(ready):
    """就绪项按依赖排序：被依赖的先关。存在环时保持原顺序并原样返回。"""
    ids = {item["change"] for item in ready}
    ordered, seen = [], set()

    def visit(item, trail):
        if item["change"] in seen or item["change"] in trail:
            return
        trail.add(item["change"])
        for dep in item.get("depends_on") or []:
            if dep in ids:
                nxt = next(i for i in ready if i["change"] == dep)
                visit(nxt, trail)
        if item["change"] not in seen:
            seen.add(item["change"])
            ordered.append(item)

    for item in ready:
        visit(item, set())
    return ordered


def build_next_action(run_strict=True):
    """循环的下一个动作：目标 change、目标 task 与应派出的角色。"""
    harness_state.configure_root(ROOT)
    state = harness_state.build_state()
    active = next((c for c in state["changes"] if c["is_active"]), None)

    if active is None:
        report = build_ready_report(run_strict=run_strict)
        if report["ready"]:
            return {"action": "close", "change": report["ready"][0]["change"],
                    "role": None,
                    "reason": "就绪度成立，自动归档；批量顺序见 harness ready"}
        return {"action": "select-active", "change": None, "role": "human",
                "reason": "没有 active change，需要人选定下一个要做什么"}

    if active.get("verification_error"):
        return {"action": "migrate", "change": active["id"], "role": "generator",
                "reason": active["verification_error"]}

    tasks = [t for t in (active["tasks"] or []) if t["type"] == "task"]
    pending_task = next((t for t in tasks if not t["checked"]), None)
    if pending_task:
        return {"action": "implement", "change": active["id"],
                "role": "generator", "task": pending_task["text"],
                "reason": "还有未完成任务"}

    pending_eval = next((s for s in active["steps"]
                         if s["role"] != "human"
                         and s["status"] not in hv.TERMINAL_STATUSES), None)
    if pending_eval:
        return {"action": "evaluate", "change": active["id"],
                "role": "evaluator", "step": pending_eval["id"],
                "rule": pending_eval["rule"],
                "reason": "任务已完成，验证步骤待评估"}

    pending_human = next((s for s in active["human_steps"]
                          if s["status"] not in hv.TERMINAL_STATUSES), None)
    if pending_human:
        return {"action": "await-human", "change": active["id"], "role": "human",
                "step": pending_human["id"],
                "reason": "等待人工步骤作答；这是产品品味、风险承担或选择做什么"}

    result = change_readiness(active, run_strict=run_strict)
    if result["ready"]:
        return {"action": "close", "change": active["id"], "role": None,
                "reason": "七项判据全部成立"}
    first = result["blockers"][0]
    return {"action": "resolve", "change": active["id"],
            "role": first["owner"], "reason": first["detail"]}


def format_ready(report):
    out = []
    ready = report["ready"]
    out.append("可归档（%d）：" % len(ready))
    for item in ready or []:
        deps = item.get("depends_on") or []
        note = "依赖 %s，同批可关" % "、".join(deps) if deps else "依赖已满足"
        out.append("  %-52s %s" % (item["change"], note))
    if not ready:
        out.append("  （无）")
    out.append("")
    out.append("被阻塞（%d）：" % len(report["blocked"]))
    for item in report["blocked"]:
        out.append("  %-52s [%s] %s" % (
            item["change"], OWNER_LABEL.get(item["owner"], item["owner"]),
            item["next_action"]))
    if not report["blocked"]:
        out.append("  （无）")
    return "\n".join(out)


USAGE = """用法:
  harness_checks.py gate <change> [--root <path>]
  harness_checks.py ready [--json] [--no-strict] [--root <path>]
  harness_checks.py next [--json] [--no-strict] [--root <path>]
  harness_checks.py verification <change> [--root <path>]
  harness_checks.py roles <change> [--root <path>]
  harness_checks.py doc-refs [--root <path>]
  harness_checks.py skills [--root <path>]
  harness_checks.py probe-needed <change> [--root <path>]
  harness_checks.py risk-floor <change> [--root <path>]
"""

COMMANDS = ("gate", "ready", "next", "verification", "roles", "doc-refs",
            "skills", "probe-needed", "risk-floor")

CHANGE_COMMANDS = ("gate", "verification", "roles", "probe-needed",
                   "risk-floor")


def generator_identity(change_id):
    """从 .harness/current.json 取本 change 的实现身份。

    走状态层的 load_current，不自己再读一遍：current.json 的解析与迁移语义
    只在 harness_state 一处。
    """
    harness_state.configure_root(ROOT)
    data = harness_state.load_current()
    if not isinstance(data, dict) or data.get("_parse_error"):
        return {}
    context = (data.get("change_context") or {}).get(change_id) or {}
    identity = context.get("generated_by") or data.get("generated_by") or {}
    return identity if isinstance(identity, dict) else {}


def main(argv):
    args = list(argv[1:])
    if not args or args[0] not in COMMANDS:
        sys.stderr.write(USAGE)
        return 2
    command = args.pop(0)

    root = None
    positional = []
    as_json = False
    run_strict = True
    while args:
        arg = args.pop(0)
        if arg == "--root":
            root = args.pop(0) if args else None
            if root is None:
                sys.stderr.write(USAGE)
                return 2
        elif arg.startswith("--root="):
            root = arg.split("=", 1)[1]
        elif arg == "--json":
            as_json = True
        elif arg == "--no-strict":
            run_strict = False
        elif arg.startswith("-"):
            sys.stderr.write(USAGE)
            return 2
        else:
            positional.append(arg)

    needs_change = command in CHANGE_COMMANDS
    if needs_change and len(positional) != 1:
        sys.stderr.write(USAGE)
        return 2
    if not needs_change and positional:
        sys.stderr.write(USAGE)
        return 2

    if root:
        if not os.path.isdir(root):
            sys.stderr.write("错误: --root 不是目录: %s\n" % root)
            return 2
        configure_root(root)

    if command == "probe-needed":
        needed, reason = requires_unity_probe(positional[0])
        print("==> 环境探针: %s（%s）" % ("执行" if needed else "跳过", reason))
        return 0 if needed else 1

    if command == "ready":
        report = build_ready_report(run_strict=run_strict)
        print(json.dumps(report, ensure_ascii=False, indent=2) if as_json
              else format_ready(report))
        return 0

    if command == "next":
        action = build_next_action(run_strict=run_strict)
        if as_json:
            print(json.dumps(action, ensure_ascii=False, indent=2))
        else:
            print("动作: %s" % action["action"])
            if action.get("change"):
                print("change: %s" % action["change"])
            if action.get("role"):
                print("角色: %s" % OWNER_LABEL.get(action["role"], action["role"]))
            for key in ("task", "step", "rule"):
                if action.get(key):
                    print("%s: %s" % (key, action[key]))
            print("原因: %s" % action["reason"])
        return 0

    if command == "gate":
        problems = close_gate(positional[0])
        label = "关闭门槛"
    elif command == "verification":
        problems = check_verification(positional[0])
        label = "验证记录结论"
    elif command == "roles":
        problems = check_role_isolation(
            positional[0], generator_identity(positional[0]))
        label = "角色隔离"
    elif command == "risk-floor":
        problems = check_risk_floor(positional[0])
        label = "风险等级下限"
    elif command == "doc-refs":
        problems = check_doc_references()
        label = "文档引用路径"
    else:
        problems = check_skill_consistency()
        label = "skill 定义一致性"

    if problems:
        sys.stderr.write("错误: %s 检查未通过\n" % label)
        for problem in problems:
            sys.stderr.write("  - %s\n" % problem)
        return 1

    print("==> %s 检查通过" % label)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
