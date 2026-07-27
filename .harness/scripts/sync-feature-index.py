#!/usr/bin/env python3
"""从 OpenSpec 派生 .harness/feature-index.json 的能力索引骨架。

能力索引不是任务管理器：它只保存 capability 与 OpenSpec spec 的映射、成熟度、
质量等级、活跃变更和最近验证提交。骨架（id / spec_ref / requirement_count /
active_changes）从 openspec 派生，人工只维护 `overrides` 中的 quality、title、
domain、maturity 和 last_verified_commit。

用法:
  .harness/scripts/sync-feature-index.py            重新生成索引
  .harness/scripts/sync-feature-index.py --check    只检查是否已是最新，不写文件
"""

import datetime
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
INDEX_PATH = os.path.join(ROOT_DIR, ".harness", "feature-index.json")
SPECS_DIR = os.path.join(ROOT_DIR, "openspec", "specs")
CHANGES_DIR = os.path.join(ROOT_DIR, "openspec", "changes")

NOTE = (
    "能力索引，不是任务管理器。骨架由 .harness/scripts/sync-feature-index.py 从 "
    "openspec/specs/ 派生，人工只维护 overrides。产品行为以 openspec/specs/ 为准，"
    "候选和 active 执行 change 以 openspec/changes/<id>/ 为准，唯一 active 执行槽以 "
    ".harness/current.json.active_change 为准，验证证据以对应 change 的 "
    "verification.md 和 .harness/evidence/ 为准。"
)

OVERRIDE_FIELDS = ("title", "domain", "maturity", "quality", "last_verified_commit")


def spec_ids_from_disk():
    if not os.path.isdir(SPECS_DIR):
        return []
    return sorted(
        name
        for name in os.listdir(SPECS_DIR)
        if os.path.isfile(os.path.join(SPECS_DIR, name, "spec.md"))
    )


REQUIREMENT_RE = re.compile(r"(?m)^###\s+Requirement:")


def requirement_count(spec_id):
    """统计一个 spec 的 requirement 数。

    直接解析 spec.md 而不是调用 `openspec list --specs --json`：索引必须能被
    确定性重算，否则 `--check` 会因为 openspec CLI 是否可用而假报不同步。
    两种口径已在 62 个 spec 上逐一比对一致。
    """
    path = os.path.join(SPECS_DIR, spec_id, "spec.md")
    try:
        with open(path, encoding="utf-8") as handle:
            return len(REQUIREMENT_RE.findall(handle.read()))
    except OSError:
        return None


def active_changes_by_spec():
    """从各非归档 change 的 delta spec 目录反推每个 capability 的在途变更。"""
    mapping = {}
    if not os.path.isdir(CHANGES_DIR):
        return mapping

    for change in sorted(os.listdir(CHANGES_DIR)):
        if change == "archive":
            continue
        delta_dir = os.path.join(CHANGES_DIR, change, "specs")
        if not os.path.isdir(delta_dir):
            continue
        for capability in sorted(os.listdir(delta_dir)):
            if os.path.isfile(os.path.join(delta_dir, capability, "spec.md")):
                mapping.setdefault(capability, []).append(change)

    return mapping


def load_existing():
    if not os.path.isfile(INDEX_PATH):
        return {}
    try:
        with open(INDEX_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def project_name():
    """项目名由人工维护，重新生成时原样保留。"""
    existing = load_existing()
    name = existing.get("project")
    return name if isinstance(name, str) and name else "替换成你的项目名"


def load_overrides():
    existing = load_existing()
    if not existing:
        return {}

    overrides = existing.get("overrides")
    if isinstance(overrides, dict):
        return overrides

    # schema v1 兼容：从旧 features 数组回收人工维护过的字段。
    recovered = {}
    for feature in existing.get("features", []):
        if not isinstance(feature, dict):
            continue
        spec_ref = feature.get("spec_ref") or ""
        spec_id = spec_ref.split("/")[-2] if spec_ref.count("/") >= 2 else None
        if not spec_id:
            continue
        kept = {
            field: feature[field]
            for field in OVERRIDE_FIELDS
            if feature.get(field) not in (None, "")
        }
        if kept:
            recovered[spec_id] = kept

    return recovered


def build_index():
    overrides = load_overrides()
    in_flight = active_changes_by_spec()

    features = []
    for spec_id in spec_ids_from_disk():
        override = overrides.get(spec_id, {})
        features.append(
            {
                "id": spec_id,
                "title": override.get("title", spec_id),
                "domain": override.get("domain", spec_id.split("-")[0]),
                "spec_ref": "openspec/specs/%s/spec.md" % spec_id,
                "requirement_count": requirement_count(spec_id),
                "maturity": override.get("maturity", "implemented"),
                "quality": override.get("quality"),
                "active_changes": in_flight.get(spec_id, []),
                "last_verified_commit": override.get("last_verified_commit"),
            }
        )

    # 保留指向尚未落地 spec 的人工 override，避免静默丢失人工维护过的数据。
    orphans = sorted(set(overrides) - {feature["id"] for feature in features})

    return {
        "schema_version": 2,
        "project": project_name(),
        "last_updated": datetime.date.today().isoformat(),
        "note": NOTE,
        "generated_by": ".harness/scripts/sync-feature-index.py",
        "orphan_overrides": orphans,
        "overrides": overrides,
        "features": features,
    }


def render(index):
    return json.dumps(index, ensure_ascii=False, indent=2) + "\n"


def main(argv):
    check_only = "--check" in argv[1:]
    unknown = [arg for arg in argv[1:] if arg != "--check"]
    if unknown:
        sys.stderr.write("未知参数: %s\n" % " ".join(unknown))
        return 2

    index = build_index()
    rendered = render(index)

    if check_only:
        try:
            with open(INDEX_PATH, encoding="utf-8") as handle:
                current = handle.read()
        except OSError as error:
            sys.stderr.write("无法读取 %s: %s\n" % (INDEX_PATH, error))
            return 1

        # last_updated 每天都会变，不作为过期判据。
        def comparable(text):
            try:
                data = json.loads(text)
            except ValueError:
                return None
            data.pop("last_updated", None)
            return json.dumps(data, ensure_ascii=False, sort_keys=True)

        if comparable(current) != comparable(rendered):
            sys.stderr.write(
                "错误: .harness/feature-index.json 与 openspec 已不同步；"
                "运行 .harness/scripts/sync-feature-index.py 重新生成。\n"
            )
            return 1

        print("==> feature-index 与 openspec 同步 (%d capabilities)" % len(index["features"]))
        return 0

    with open(INDEX_PATH, "w", encoding="utf-8") as handle:
        handle.write(rendered)

    print(
        "==> 已生成 %s：%d capabilities，%d 条人工 override"
        % (
            os.path.relpath(INDEX_PATH, ROOT_DIR),
            len(index["features"]),
            len(index["overrides"]),
        )
    )
    if index["orphan_overrides"]:
        print("==> 提示：以下 override 没有对应 spec：%s" % ", ".join(index["orphan_overrides"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
