"""
Drift check for a vendored copy. The vendoring tool writes VENDORED.json (version + sha256 of every
file) next to the copied modules; an add-on's test suite calls `modified_files()` and fails when
anything in its `_wh/` was edited by hand. In the source repo there is no VENDORED.json and the
check returns nothing.
"""

import hashlib
import json
import os

MANIFEST = "VENDORED.json"


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def manifest(folder=None):
    folder = folder or os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(folder, MANIFEST)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def modified_files(folder=None):
    """Names of vendored files that differ from VENDORED.json, plus files missing or added
    (.py only); [] for an untouched copy or for the source repo."""
    folder = folder or os.path.dirname(os.path.abspath(__file__))
    data = manifest(folder)
    if data is None:
        return []
    recorded = data.get("files", {})
    present = {n for n in os.listdir(folder) if n.endswith(".py")}
    out = []
    for name in sorted(set(recorded) | present):
        path = os.path.join(folder, name)
        if name not in recorded or name not in present or file_hash(path) != recorded[name]:
            out.append(name)
    return out


def vendored_version(folder=None):
    data = manifest(folder)
    return data.get("version") if data else None
