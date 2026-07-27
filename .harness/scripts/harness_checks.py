#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harness verify / close 的门槛检查。

放在 Python 里而不是各平台脚本里，保证 Windows 与 Unix 判定完全一致。
只依赖标准库。

  python3 .harness/scripts/harness_checks.py human-checks <change> [--root <p>]
  python3 .harness/scripts/harness_checks.py doc-refs [--root <path>]
  python3 .harness/scripts/harness_checks.py skills [--root <path>]
  python3 .harness/scripts/harness_checks.py probe-needed <change> [--root <p>]

退出码：0 通过；1 检查失败；2 用法错误。
probe-needed 用退出码表达判定：0 = 需要 Unity 探针，1 = 不需要。
"""

import hashlib
import os
import re
import sys

_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_SELF_DIR))

# 规则与流程文档：这些文件里的仓库内路径引用必须真实存在。
REFERENCE_DOCS = (
    "CLAUDE.md",
    "AGENTS.md",
    "index.md",
    "clean-state-checklist.md",
    "docs/quality/README.md",
    "docs/quality/scorecard.md",
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

# quality-contract.md「必须验证」里表示"不需要"的说法。必须出现在条目开头：
# 用子串匹配会把"确认无 NotSupportedException"这类正面要求误判为不需要。
# 「无」后面不能紧跟汉字，否则"无论如何都要跑"会被误判。
NEGATIVE_RE = re.compile(
    r"^(不需要|不要求|不适用|不涉及|无需|无强制|n/?a|none|[-—])|^无(?![一-鿿])",
    re.IGNORECASE)


def configure_root(root):
    global ROOT
    ROOT = os.path.abspath(root)


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
# human-checks：正向断言
# --------------------------------------------------------------------------

def check_human_checks(change_id):
    """断言人工检查表格给出了明确结论，而不是"没匹配到 pending 就放行"。"""
    path = os.path.join(ROOT, "openspec", "changes", change_id, "human-checks.md")
    if not os.path.isfile(path):
        return ["找不到 %s" % path]

    text = read_text(path)
    lines = text.replace("\r\n", "\n").split("\n")

    header_idx = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("|") and "状态" in line and "检查项" in line:
            header_idx = idx
            break
    if header_idx is None:
        return ["human-checks.md 缺少规范的五列检查项表格（表头需含「状态」和「检查项」）；"
                "不接受清单式或自由格式的人工检查"]

    rows = []
    for idx in range(header_idx + 2, len(lines)):
        line = lines[idx]
        if not line.strip().startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5:
            rows.append((idx + 1, cells))

    problems = []
    if not rows:
        problems.append("human-checks.md 的检查项表格没有任何数据行；"
                        "至少要有一行明确结论（passed 或 waived）")
        return problems

    waived = 0
    for line_no, cells in rows:
        status = cells[0].lower()
        if status == "waived":
            waived += 1
        elif status != "passed":
            problems.append("第 %d 行状态为 %r，必须是 passed 或 waived：%s"
                            % (line_no, cells[0], cells[1][:40]))

    if waived:
        body = [l.strip() for l in section_lines(text, "豁免记录")]
        entries = [l for l in body
                   if l.startswith("-") and l.lstrip("-").strip() not in ("", "无", "无。")]
        if not entries:
            problems.append("存在 %d 行 waived，但「豁免记录」小节没有对应说明条目" % waived)

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
    """读 quality-contract.md 的「必须验证」，判断本变更是否需要 Unity 探针。"""
    path = os.path.join(ROOT, "openspec", "changes", change_id,
                        "quality-contract.md")
    if not os.path.isfile(path):
        return True, "找不到 quality-contract.md，保守执行探针"

    body = section_lines(read_text(path), "必须验证")
    unity_lines = []
    for line in body:
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        item = stripped.lstrip("-").strip()
        if not item.startswith(("EditMode", "PlayMode")):
            continue
        _label, _sep, value = item.partition("：")
        if not _sep:
            _label, _sep, value = item.partition(":")
        unity_lines.append(value.strip())

    if not unity_lines:
        return True, "质量契约未声明 EditMode/PlayMode 要求，保守执行探针"

    for value in unity_lines:
        if not value:
            return True, "质量契约的 EditMode/PlayMode 条目为空，保守执行探针"
        if not NEGATIVE_RE.match(value.strip().lstrip("`")):
            return True, "质量契约要求 Unity 验证"

    return False, "质量契约声明不需要 EditMode/PlayMode"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

USAGE = """用法:
  harness_checks.py human-checks <change> [--root <path>]
  harness_checks.py doc-refs [--root <path>]
  harness_checks.py skills [--root <path>]
  harness_checks.py probe-needed <change> [--root <path>]
"""

COMMANDS = ("human-checks", "doc-refs", "skills", "probe-needed")


def main(argv):
    args = list(argv[1:])
    if not args or args[0] not in COMMANDS:
        sys.stderr.write(USAGE)
        return 2
    command = args.pop(0)

    root = None
    positional = []
    while args:
        arg = args.pop(0)
        if arg == "--root":
            root = args.pop(0) if args else None
            if root is None:
                sys.stderr.write(USAGE)
                return 2
        elif arg.startswith("--root="):
            root = arg.split("=", 1)[1]
        elif arg.startswith("-"):
            sys.stderr.write(USAGE)
            return 2
        else:
            positional.append(arg)

    needs_change = command in ("human-checks", "probe-needed")
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

    if command == "human-checks":
        problems = check_human_checks(positional[0])
        label = "人工检查结论"
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
