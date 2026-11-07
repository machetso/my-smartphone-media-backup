"""Interface languages: formatting, plurals, every dictionary's placeholders and completeness."""

import json
import re
import sys
import unittest
from pathlib import Path

from phonebackup import i18n

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import i18n_keys  # noqa: E402

PH = re.compile(r"%(\d+\$)?[-+0#,]*\d*(?:\.\d+)?([sdfigeExX])")


def placeholders(text):
    """Placeholder types in the order the values are used: plain ones in reading order,
    positional ones (%2$s) by their number – a translation may reorder only with positions."""
    found = PH.findall(text.replace("%%", ""))
    if any(pos for pos, _ in found):
        return [c for _, c in sorted(((int(pos[:-1]) if pos else i + 1), c) for i, (pos, c) in enumerate(found))]
    return [c for _, c in found]


class I18nTest(unittest.TestCase):
    def tearDown(self):
        i18n.use("en")

    def test_format_and_plural(self):
        i18n.use("en")
        self.assertEqual(i18n.tr("%s of %d at %.1f MB/s", "a", 3, 2.25), "a of 3 at 2.2 MB/s")
        self.assertEqual(i18n.tr("%1$s / %2$s", "x", "y"), "x / y")
        self.assertEqual(i18n.trp("%d file", "%d files", 1, 1), "1 file")
        self.assertEqual(i18n.trp("%d file", "%d files", 4, 4), "4 files")
        self.assertEqual(i18n.plural_category("ro", 15), "few")

    def test_dictionary_placeholders_match(self):
        for f in sorted((ROOT / "i18n").glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            bad = []
            for key, value in d["texts"].items():
                for v in (value.values() if isinstance(value, dict) else [value]):
                    if not isinstance(v, str) or (not v.strip() and key.strip()):
                        bad.append((key, v))
                    elif placeholders(v) != placeholders(key):
                        bad.append((key, v))
            self.assertFalse(bad, f"{f.stem}: {len(bad)} wrong placeholders, e.g. {bad[:3]}")

    def test_every_text_is_translated(self):
        keys = i18n_keys.keys()
        missing = {code: [t for t in keys if t not in d["texts"]]
                   for code, d in i18n_keys.dictionaries().items()}
        self.assertFalse(any(missing.values()), {c: len(m) for c, m in missing.items() if m})


if __name__ == "__main__":
    unittest.main()


class ManualTranslationsTest(unittest.TestCase):
    """Every interface language has the manual (README.<code>.md) with the same headings and
    code blocks as the English README (user request 2026-11-07)."""

    @staticmethod
    def _shape(text):
        import re
        heads = re.findall(r"^(#+) ", text, re.M)
        fences = len(re.findall(r"^\s*```", text, re.M))
        return heads, fences

    def test_every_language_has_the_manual(self):
        from pathlib import Path
        from phonebackup import i18n
        root = Path(__file__).resolve().parent.parent
        english = self._shape((root / "README.md").read_text(encoding="utf-8"))
        for lang in i18n.languages():
            if lang.code == "en":
                continue
            with self.subTest(lang=lang.code):
                f = root / f"README.{lang.code}.md"
                self.assertTrue(f.is_file(), f"{f.name} missing")
                self.assertEqual(self._shape(f.read_text(encoding="utf-8")), english)
