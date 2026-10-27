"""The public package carries no company material (2.25, extensions.blender.org): no company or
product names, no source attributions, no budget or prices, no process notes (PM, approvals,
rounds, waves) or internal documents, no pointers into the unshipped docs/, tools/ or tests/ --
in any shipped file, comments and docstrings included (the tooltip scan only sees user-visible
strings), the vendored _wh too. The general conveyor knowledge and the suite's contract ids
(R8, R22 ...) stay. The names themselves are kept as SHA-256 hashes, so this file -- in a
repository others may read -- never spells them; every word, and the start of every word, is
hashed and compared. No shipped image carries metadata (a render stamp named the source file's
path) and no .blend a path. Pure Python: python3 -m unittest tests.test_public_text (from dev/)."""
import ast
import fnmatch
import hashlib
import io
import json
import pathlib
import re
import tokenize
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BANNED = re.compile(r"activated roller|best practice|\bbudget|\bprices?\b|€|\bNOK\b"
                    r"|\bapproved\b|\brounds? \d|\bwaves? \d|coordinating|census|_coordination|research_notes|proposal|SUITE_PLAN", re.I)
PM = re.compile(r"\bPM\b(?!\s*\d)")  # the project manager; not a variable `pm` or a model number (Interroll PM 9730)
NAMES = re.compile(r"Åsmund|Asmund", re.I)  # only as the maintainer and copyright holder, in the manifest
DOCS = re.compile(r"\b(docs|tools|tests)/|\b\w+\.md\b")  # not shipped: no pointers into them (the manifest excludes them)
NOT_OURS = {"LICENSE"}  # the GPL's own text talks about price
NAME_HASHES = {  # sha256 of the lower-case company and product names that must never ship
    "606a17da8d260b13da16864c644553c451413cab3261c784c0443165c76bb7e2",
    "d5fa750a1ed806ea694fc85d3fe05a1783483168807fd3780addb238a9a61ebe",
}
NAME_LENGTHS = (9, 7)  # their lengths: a word is hashed whole and cut to each (a name inside a longer word)
PNG_TEXT = {b"tEXt", b"iTXt", b"zTXt", b"tIME"}


def names_in(line: str) -> bool:
    for word in re.findall(r"[a-z0-9]+", line.lower()):
        for cut in {word} | {word[:n] for n in NAME_LENGTHS if len(word) > n}:
            if hashlib.sha256(cut.encode()).hexdigest() in NAME_HASHES:
                return True
    return False


def shipped():
    """The files the build packs: everything but the manifest's paths_exclude_pattern."""
    with open(ROOT / "blender_manifest.toml", "rb") as fh:
        patterns = tomllib.load(fh)["build"]["paths_exclude_pattern"]
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(excluded(rel, p) for p in patterns) or rel in NOT_OURS:
            continue
        yield rel, path


def excluded(rel, pattern):
    if pattern.endswith("/"):  # a folder: anchored ("/docs/") or anywhere ("__pycache__/")
        name = pattern.strip("/")
        parts = rel.split("/")[:-1]
        return parts[:1] == [name] if pattern.startswith("/") else name in parts
    if pattern.startswith("/"):
        return "/" not in rel and fnmatch.fnmatch(rel, pattern[1:])
    return fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pattern)


class PublicTextTests(unittest.TestCase):
    def test_the_package_is_found(self):
        names = {rel for rel, _p in shipped()}
        self.assertIn("__init__.py", names)
        self.assertIn("ui/panels.py", names)
        self.assertFalse(any(n.startswith(("tests/", "tools/", "docs/")) for n in names))

    def test_no_company_material_in_shipped_text(self):
        hits = []
        for rel, path in shipped():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue  # images, .blend libraries
            for no, line in enumerate(text.splitlines(), 1):
                ours = rel != "blender_manifest.toml"
                if BANNED.search(line) or names_in(line) or PM.search(line) or (ours and (NAMES.search(line) or DOCS.search(line))):
                    hits.append(f"{rel}:{no}: {line.strip()[:100]}")
        self.assertEqual(hits, [])

    def test_the_names_are_caught_without_being_written_here(self):
        self.assertEqual(len(NAME_HASHES), len(NAME_LENGTHS))
        self.assertFalse(names_in("A conveyor line with a right-angle transfer and a spiral"))

    def test_no_metadata_in_shipped_images_or_libraries(self):
        """A render stamp in a PNG named the .blend it came from (a local path); a .blend can carry
        the path it was saved at."""
        import struct

        hits = []
        for rel, path in shipped():
            data = path.read_bytes()
            if rel.endswith(".png"):
                i = 8
                while i < len(data):
                    n, = struct.unpack(">I", data[i:i + 4])
                    if data[i + 4:i + 8] in PNG_TEXT:
                        hits.append(f"{rel}: {data[i + 4:i + 8].decode()} chunk")
                    i += 12 + n
            elif rel.endswith(".blend"):
                if data[:4] == b"\x28\xb5\x2f\xfd":  # zstd-compressed
                    try:
                        from compression import zstd
                    except ImportError:
                        continue  # (Python < 3.14 cannot look inside)
                    data = zstd.decompress(data)
                if re.search(rb"/Users/|/home/|[A-Z]:\\Users|OneDrive", data):
                    hits.append(f"{rel}: a local path")
        self.assertEqual(hits, [])

    def test_arb_only_as_an_id(self):
        """The angled-roller belt is called that in every text a user can meet (labels, messages,
        tooltips, docstrings, catalogue values) and in the comments; 'ARB' stays only as a bare id
        ('ARB') and inside identifiers (MODULE_KIND_ARB)."""
        word = re.compile(r"\bARB\b")
        hits = []

        def walk(v, where):
            if isinstance(v, dict):
                for k, x in v.items():  # keys are ids
                    walk(x, f"{where}.{k}")
            elif isinstance(v, list):
                for i, x in enumerate(v):
                    walk(x, f"{where}[{i}]")
            elif isinstance(v, str) and word.search(v) and v.strip() != "ARB":
                hits.append(f"{where}: {v[:80]}")

        prose = re.compile(r"(?<![\'\"])\bARB\b")  # in a comment: a word, not a quoted id
        for rel, path in shipped():
            if rel.endswith(".py"):
                text = path.read_text(encoding="utf-8")
                for n in ast.walk(ast.parse(text)):
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and word.search(n.value) and n.value.strip() != "ARB":
                        hits.append(f"{rel}:{n.lineno}: {n.value.strip()[:80]}")
                for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                    if tok.type == tokenize.COMMENT and prose.search(tok.string):
                        hits.append(f"{rel}:{tok.start[0]}: {tok.string[:80]}")
            elif rel.endswith(".json"):
                walk(json.loads(path.read_text(encoding="utf-8")), rel)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
