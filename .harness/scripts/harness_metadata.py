"""Optional non-derived change facts stored inside program.md; never task state."""
import json
import os
import re

FIELDS = {"generated_by", "depends_on", "blockers"}
BLOCK = re.compile(r"^```harness-metadata\s*\n(.*?)^```[ \t]*$", re.M | re.S)

def load(root, change_id):
    if not isinstance(change_id, str) or not change_id or change_id in (".", "..", "archive") or "/" in change_id or "\\" in change_id:
        raise ValueError("invalid change id")
    path = os.path.join(root, "openspec", "changes", change_id, "program.md")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as stream:
        text = stream.read()
    blocks = BLOCK.findall(text)
    if len(blocks) > 1 or ("```harness-metadata" in text and not blocks):
        raise ValueError("program.md must contain at most one closed harness-metadata block")
    if not blocks:
        return {}
    data = json.loads(blocks[0])
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise ValueError("harness-metadata accepts only generated_by, depends_on, blockers")
    for field in ("depends_on", "blockers"):
        if field in data and (not isinstance(data[field], list) or any(not isinstance(v, str) or not v.strip() for v in data[field])):
            raise ValueError(field + " must be a list of nonempty strings")
    for dep in data.get("depends_on", []):
        if dep in (".", "..", "archive") or "/" in dep or "\\" in dep or dep == change_id:
            raise ValueError("invalid dependency: " + dep)
    if "generated_by" in data:
        identity = data["generated_by"]
        if not isinstance(identity, dict) or set(identity) != {"agent", "model"} or any(not isinstance(v, str) or not v.strip() for v in identity.values()):
            raise ValueError("generated_by requires nonempty agent and model")
    return data
