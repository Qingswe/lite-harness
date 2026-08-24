#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""角色档案：验证步骤的填表模板。

**这个模块提供的不是身份凭证。**

`.harness/program.md` 第 2 节要求实现与评估由不同角色、不同模型承担，
`verification.json` 的 `evaluated_by` 记录的就是「谁做的判定」。如果档案能决定
写进 `evaluated_by` 的值，那条要求就退化成措辞——任何人在浏览器里点几下就能伪造
一次 AI 评估记录。

所以档案里只有 `operator`（人名）和备注模板两样东西，二者都不是身份。AI evaluator
的身份只能由真实 Evaluator 经 CLI 写入（`harness_verification.set_step(agent=...)`），
而看板那条路径根本不传 `agent`。`PROFILE_FIELDS` 是这条边界的结构性保证：多出任何
一个字段都会让 `validate()` 报错。
"""

import copy
import json
import os

ROLES = ("human", "evaluator", "external")
# 档案允许出现的字段。刻意不含 evaluated_by / agent / model —— 见模块说明。
PROFILE_FIELDS = ("id", "label", "role", "operator", "note_template")
SCHEMA_VERSION = 1

_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_SELF_DIR))
ROLES_JSON = ""


def configure_root(root):
    global ROOT, ROLES_JSON
    ROOT = os.path.abspath(root)
    ROLES_JSON = os.path.join(ROOT, ".harness", "roles.json")


configure_root(ROOT)


def default_state():
    """默认档案。

    给刚采用模板的仓库一个能直接用的起点；采用方用 `.harness/roles.json`
    覆盖成自己的名单（operator 换成真实人名）。
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "active_profile": "human-owner",
        "profiles": [
            {"id": "human-owner", "label": "仓库所有者（人工）", "role": "human",
             "operator": "owner", "note_template": ""},
            {"id": "evaluator-agent", "label": "Evaluator Agent",
             "role": "evaluator", "operator": "harness-evaluator",
             "note_template": "证据：.harness/evidence/<change>/"},
            {"id": "external", "label": "外部工具", "role": "external",
             "operator": "", "note_template": ""},
        ],
    }


class RoleError(ValueError):
    """档案不合法。调用方应把它当作 400 而不是 500。"""


def validate(state):
    """校验档案，返回规范化后的副本。任何问题都抛 RoleError。

    校验必须发生在**写入之前**：写完再校验意味着非法档案已经落盘，而下一次
    load() 会拿它当事实。
    """
    if not isinstance(state, dict):
        raise RoleError("角色档案必须是对象")
    profiles = state.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise RoleError("profiles 必须是非空列表")

    seen = set()
    cleaned = []
    for raw in profiles:
        if not isinstance(raw, dict):
            raise RoleError("每个档案必须是对象")
        extra = set(raw) - set(PROFILE_FIELDS)
        if extra:
            # 多出来的字段可能是有人想塞 evaluated_by / agent / model 进来。
            raise RoleError("档案含未知字段: %s" % "、".join(sorted(extra)))
        pid = str(raw.get("id") or "").strip()
        if not pid:
            raise RoleError("档案缺少 id")
        if pid in seen:
            raise RoleError("档案 id 重复: %s" % pid)
        seen.add(pid)
        role = str(raw.get("role") or "").strip().lower()
        if role not in ROLES:
            raise RoleError("档案 %s 的 role 非法: %s（只能是 %s）"
                            % (pid, role or "空", "/".join(ROLES)))
        cleaned.append({
            "id": pid,
            "label": str(raw.get("label") or pid),
            "role": role,
            "operator": str(raw.get("operator") or ""),
            "note_template": str(raw.get("note_template") or ""),
        })

    active = str(state.get("active_profile") or "").strip()
    if active not in seen:
        raise RoleError("active_profile 指向不存在的档案: %s" % (active or "空"))

    return {
        "schema_version": int(state.get("schema_version") or SCHEMA_VERSION),
        "active_profile": active,
        "profiles": cleaned,
    }


def load():
    """读档案。文件不存在时返回默认档案，但**不写盘**。

    读操作不产生副作用：一次 GET /api/roles 不该在仓库里造出一个文件。落盘只
    发生在明确的写操作里。
    """
    if not os.path.isfile(ROLES_JSON):
        return default_state()
    try:
        with open(ROLES_JSON, encoding="utf-8") as fh:
            return validate(json.load(fh))
    except (OSError, ValueError) as exc:
        raise RoleError("读取 %s 失败: %s" % (ROLES_JSON, exc))


def save(state):
    """校验后写盘。校验不过则原文件一字节不动。"""
    cleaned = validate(state)
    os.makedirs(os.path.dirname(ROLES_JSON), exist_ok=True)
    with open(ROLES_JSON, "w", encoding="utf-8") as fh:
        json.dump(cleaned, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return cleaned


def active_profile(state=None):
    state = state or load()
    for profile in state["profiles"]:
        if profile["id"] == state["active_profile"]:
            return profile
    # validate() 保证了这一行到不了；到了就说明有人绕过 save() 直接改了文件。
    raise RoleError("active_profile 指向不存在的档案")


def resolve(step_role, state=None):
    """给出该角色步骤应当填入的 operator。

    优先用与步骤 role 相符的档案：把一个 evaluator 步骤的 operator 填成人的名字
    会让记录说谎。找不到相符的就退回激活档案。
    """
    state = state or load()
    role = str(step_role or "").strip().lower()
    for profile in state["profiles"]:
        if profile["role"] == role and profile["operator"]:
            return profile["operator"]
    return active_profile(state)["operator"]


def use(profile_id, state=None):
    """切换激活档案。"""
    state = copy.deepcopy(state or load())
    state["active_profile"] = profile_id
    return save(state)


def set_profile(profile_id, operator=None, label=None, note_template=None,
                role=None, state=None):
    """改一个已有档案，或按给定字段新建一个。"""
    state = copy.deepcopy(state or load())
    for profile in state["profiles"]:
        if profile["id"] == profile_id:
            if operator is not None:
                profile["operator"] = operator
            if label is not None:
                profile["label"] = label
            if note_template is not None:
                profile["note_template"] = note_template
            if role is not None:
                profile["role"] = role
            return save(state)
    state["profiles"].append({
        "id": profile_id,
        "label": label or profile_id,
        "role": role or "human",
        "operator": operator or "",
        "note_template": note_template or "",
    })
    return save(state)


def main(argv):
    import argparse
    # --json 同时挂在主解析器和每个子命令上：只挂主解析器时它必须写在子命令
    # 之前（`roles --json list`），而人会自然地写 `roles list --json`，然后得到
    # 一句「unrecognized arguments」。
    # default=SUPPRESS 是必需的：子解析器与主解析器共用同一个 dest，若子解析器
    # 带着 default=False 参与解析，它会把主解析器已经设成 True 的值覆盖回去，
    # 于是 `roles --json list` 静默地不输出 JSON。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="输出 JSON",
                        default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(description="角色档案", parents=[common])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", parents=[common])
    use_p = sub.add_parser("use", parents=[common])
    use_p.add_argument("profile")
    set_p = sub.add_parser("set", parents=[common])
    set_p.add_argument("profile")
    set_p.add_argument("--operator")
    set_p.add_argument("--label")
    set_p.add_argument("--role", choices=ROLES)
    set_p.add_argument("--note-template", dest="note_template")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "list":
            state = load()
        elif args.cmd == "use":
            state = use(args.profile)
        else:
            state = set_profile(args.profile, operator=args.operator,
                                label=args.label, role=args.role,
                                note_template=args.note_template)
    except RoleError as exc:
        sys.stderr.write("角色档案错误: %s\n" % exc)
        return 2

    if getattr(args, "json", False):
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    print("激活档案: %s" % state["active_profile"])
    for profile in state["profiles"]:
        mark = "*" if profile["id"] == state["active_profile"] else " "
        print(" %s %-16s %-10s operator=%s"
              % (mark, profile["id"], profile["role"],
                 profile["operator"] or "（空）"))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
