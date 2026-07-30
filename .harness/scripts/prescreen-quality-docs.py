#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""质量文档判断的机器预筛。

**举证责任反转**：默认结论是「无需更新」，脚本必须**证明**某条触发了才要求人工
写理由。未触发的条目不产出任何说明文字——沉默即未触发。这取代了旧规则里逐条
撰写「无需更新，原因是……」的仪式（实测 6 条判断全是 `not-needed`）。

无法机械判定的条目（是否值得立 ADR、是否踩到了值得记录的坑）单独成组，保留
人工判断，MUST NOT 由脚本代为结论。

触发条件的权威仍是 `docs/quality/README.md`；本脚本是它的机器可判定投影。

  python3 .harness/scripts/prescreen-quality-docs.py <change> [--root <p>]
        [--write] [--json]

--write 把结果写回 verification.json 的 quality_docs。
退出码：0 完成；1 失败；2 用法错误。
"""

import json
import os
import re
import subprocess
import sys
from datetime import date

_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
if _SELF_DIR not in sys.path:
    sys.path.insert(0, _SELF_DIR)

import harness_checks as hc  # noqa: E402
import harness_verification as hv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(_SELF_DIR))

# 机械可判定的触发条件。每条都必须能从 diff 内容举证。
TEST_PATH_RE = re.compile(r"(^|/)(test|tests|Tests|Editor/Tests)/|"
                          r"(_|\.)?[Tt]est[s]?\.(cs|py)$")
IMPL_PATH_RE = re.compile(r"^(UnityProject/Assets/GameScripts/|src/|"
                          r"\.harness/scripts/)")
DEBT_MARKER_RE = re.compile(r"^\+.*\b(TODO|FIXME|HACK|XXX|临时|待办|workaround)\b",
                            re.IGNORECASE)

# 无法机械判定：只能由人决定。
MANUAL_DOCS = (
    ("docs/adr/", "是否值得为本次技术选择立一条 ADR"),
    ("docs/knowledge/pitfalls/", "本轮是否踩到了可复现、容易重复发生的坑"),
)


def configure_root(root):
    global ROOT
    ROOT = os.path.abspath(root)
    hc.configure_root(ROOT)
    hv.configure_root(ROOT)


def _git(args):
    try:
        out = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def diff_text(baseline):
    for args in ([["diff", baseline]] if baseline else []) + [["diff", "HEAD"]]:
        out = _git(args)
        if out:
            return out
    return ""


def prescreen(change_id):
    """返回 {prescreen_run, changed_paths, triggered, manual}。"""
    try:
        baseline = hv.load_verification(change_id).get("baseline_commit")
    except hv.VerificationFormatError:
        baseline = None

    paths = hc.changed_paths(change_id)
    diff = diff_text(baseline)

    impl = [p for p in paths if IMPL_PATH_RE.match(p)]
    tests = [p for p in paths if TEST_PATH_RE.search(p)]
    _floor, risk_reasons = hc.risk_floor(paths)
    debt_lines = [l for l in diff.split("\n") if DEBT_MARKER_RE.match(l)]

    triggered = []

    # scorecard：实现面积变化且测试覆盖同时变化，才说明长期质量状态动了。
    if impl and tests:
        triggered.append({
            "doc": "docs/quality/scorecard.md",
            "evidence": "实现路径 %d 处、测试路径 %d 处同时变化（例：%s / %s）"
                        % (len(impl), len(tests), impl[0], tests[0]),
            "reason": "",
        })
    elif impl and not tests:
        triggered.append({
            "doc": "docs/quality/scorecard.md",
            "evidence": "实现路径变化 %d 处但没有测试变化（例：%s）；"
                        "未验证面积可能扩大" % (len(impl), impl[0]),
            "reason": "",
        })

    # tech-debt：diff 里新增了债务标记。
    if debt_lines:
        triggered.append({
            "doc": "docs/quality/tech-debt.md",
            "evidence": "diff 新增 %d 处债务标记（例：%s）"
                        % (len(debt_lines), debt_lines[0].strip()[:80]),
            "reason": "",
        })

    # risks：触及高影响路径，与风险等级下限同一组判据。
    if risk_reasons:
        triggered.append({
            "doc": "docs/quality/risks.md",
            "evidence": "触及高影响路径：%s" % "；".join(risk_reasons[:3]),
            "reason": "",
        })

    # knowledge/changes：每个 close 的 change 都该留一条摘要。
    triggered.append({
        "doc": "docs/knowledge/changes/",
        "evidence": "每个已 close 的 change 都应留下一条短摘要（docs/quality/README.md）",
        "reason": "",
    })

    return {
        "prescreen_run": date.today().isoformat(),
        "changed_paths": len(paths),
        "triggered": triggered,
        "manual": [{"doc": doc, "question": q} for doc, q in MANUAL_DOCS],
    }


def write_back(change_id, result):
    """写回 verification.json，保留已经写好的人工理由。"""
    path = hv.verification_path(change_id)
    data = hv.load_verification(change_id)
    quality = data.setdefault("quality_docs", {})
    existing = {item.get("doc"): item.get("reason")
                for item in (quality.get("triggered") or [])
                if isinstance(item, dict)}

    quality["prescreen_run"] = result["prescreen_run"]
    quality["triggered"] = [
        {"doc": item["doc"], "evidence": item["evidence"],
         "reason": existing.get(item["doc"]) or item["reason"]}
        for item in result["triggered"]
    ]
    quality["manual"] = result["manual"]

    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with open(path, "wb") as fh:
        fh.write(body.encode("utf-8"))


USAGE = """用法:
  prescreen-quality-docs.py <change> [--root <path>] [--write] [--json]
"""


def main(argv):
    args = list(argv[1:])
    root = None
    change_id = None
    do_write = as_json = False
    while args:
        arg = args.pop(0)
        if arg == "--root":
            root = args.pop(0) if args else None
            if root is None:
                sys.stderr.write(USAGE)
                return 2
        elif arg.startswith("--root="):
            root = arg.split("=", 1)[1]
        elif arg == "--write":
            do_write = True
        elif arg == "--json":
            as_json = True
        elif arg.startswith("-"):
            sys.stderr.write(USAGE)
            return 2
        elif change_id is None:
            change_id = arg
        else:
            sys.stderr.write(USAGE)
            return 2

    if change_id is None:
        sys.stderr.write(USAGE)
        return 2
    if root:
        if not os.path.isdir(root):
            sys.stderr.write("错误: --root 不是目录: %s\n" % root)
            return 2
        configure_root(root)

    result = prescreen(change_id)
    if do_write:
        try:
            write_back(change_id, result)
        except hv.VerificationFormatError as exc:
            sys.stderr.write("错误: %s\n" % exc)
            return 1

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("==> 质量文档预筛: %s（%d 个改动路径）"
          % (change_id, result["changed_paths"]))
    print("\n触发（需人工写理由）：")
    for item in result["triggered"]:
        print("  %-28s %s" % (item["doc"], item["evidence"]))
    if not result["triggered"]:
        print("  （无）")
    print("\n需人工判断（脚本不代为结论）：")
    for item in result["manual"]:
        print("  %-28s %s" % (item["doc"], item["question"]))
    print("\n未列出的条目即未触发；沉默即未触发，不需要撰写「无需更新」说明。")
    if do_write:
        print("\n已写回 %s" % hv.rel(hv.verification_path(change_id)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
