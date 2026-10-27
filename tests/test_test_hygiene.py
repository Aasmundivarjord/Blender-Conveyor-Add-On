"""Suite rule §2.10 (PM, 2026-10-15, extended to headless tests): no test or
tool saves a .blend outside the scratch temp folder -- Åsmund's project
folders (scenes/ above all) are his. Every save_as_mainfile / save_mainfile
in tests/ and tools/ must build its path from TMPDIR.
Pure Python: python3 -m unittest tests.test_test_hygiene (from dev/)."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAVE = re.compile(r"\bsave(?:_as)?_mainfile\s*\(")


class TestHygieneTests(unittest.TestCase):
    def test_blend_saves_go_to_the_scratch_temp_folder(self):
        offenders = []
        for folder in ("tests", "tools"):
            for path in sorted((ROOT / folder).rglob("*.py")):
                if path.name == pathlib.Path(__file__).name:
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
                for n, line in enumerate(lines):
                    if not SAVE.search(line) or line.lstrip().startswith("#"):
                        continue
                    window = "\n".join(lines[max(0, n - 2):n + 1])  # the call and the guard just above it
                    if "TMPDIR" not in window:
                        offenders.append(f"{path.relative_to(ROOT)}:{n + 1}: {line.strip()[:90]}")
        self.assertEqual(offenders, [], "a .blend saved outside TMPDIR")


if __name__ == "__main__":
    unittest.main()
