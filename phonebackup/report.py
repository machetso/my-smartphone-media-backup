"""Write the copy report as .txt, .html and .csv (same content, three formats).

Languages (2026-11-06): what is SHOWN is in the chosen language, what the program COMPARES or
STORES stays English.

* Report file names (unique_basename), folder names, the catalog and every status value that code
  checks ("COMPLETED", "CANCELLED by user", "OK - …", "ERROR: …", verdict.startswith("EVERYTHING")
  / "ATTENTION" …) stay English – the same backup gets the same names in every language and old
  catalogs keep working.
* A status / verdict built by the program is a `Shown`: a str whose value is the English text
  (so ==, startswith, the catalog, JSON and the tests see English) and whose `.local` is the same
  text in the chosen language. Build one with both.tr(...) / both.trp(...) (same arguments as
  i18n.tr / trp, so tools/i18n_keys.py finds the texts).
* shown(value) gives the text for the screen / the reports: `.local` of a Shown; for a plain
  English status (e.g. from the catalog or another module) the translation of a known status or
  of its known prefix ("ERROR: …" keeps the detail); anything else (file names, numbers, already
  translated text) unchanged. write_reports applies it to every value and cell; section headings,
  row labels, column headers and the title are translated by the caller (tr(...)).
* The CSV keeps its columns and numbers (only text cells and the header row are translated);
  csv_cell() formula escaping is applied after translating.
"""

import csv
import html
import re
from pathlib import Path

from . import i18n
from .i18n import N_, tr, trp
from .layout import safe_name
from .safety import csv_cell


class Shown(str):
    """English text (for comparisons, the catalog, tests) that also knows its shown form."""

    def __new__(cls, en, local=None):
        o = super().__new__(cls, en)
        o.local = str(en) if local is None else str(local)
        return o

    def __add__(self, other):
        return Shown(str(self) + str(other), self.local + str(shown(other)))

    def __radd__(self, other):
        return Shown(str(other) + str(self), str(shown(other)) + self.local)


def _english(template, args):
    if not args:
        return template
    try:
        return template % tuple(str(a) if isinstance(a, Shown) else a for a in args)
    except (TypeError, ValueError):
        return template + " " + " ".join(str(a) for a in args)


class both:
    """Shown texts: both.tr / both.trp take the same arguments as i18n.tr / trp (the key finder
    picks them up by their names); Shown arguments are inserted in the matching language."""

    @staticmethod
    def tr(en, *args):
        return Shown(_english(en, args), tr(en, *(shown(a) for a in args)))

    @staticmethod
    def trp(one, other, n, *args):
        en = one if abs(int(n)) == 1 else other
        return Shown(_english(en, args), trp(one, other, n, *(shown(a) for a in args)))

    @staticmethod
    def join(sep, items):
        items = list(items)
        return Shown(sep.join(str(i) for i in items), sep.join(str(shown(i)) for i in items))


# plain English statuses that are stored (catalog) or come from modules that keep them English
_KNOWN = {
    N_("COMPLETED"), N_("COMPLETED WITH ERRORS"), N_("RUNNING"), N_("REMOVED"),
    N_("CANCELLED by user"), N_("OK"),
    N_("ABORTED (no usable destination)"), N_("ABORTED (no destination drive left)"),
    N_("ABORTED (source folder no longer reachable)"), N_("ABORTED (phone disconnected)"),
    N_("drive disconnected or folder no longer reachable"), N_("drive is full"),
    N_("skipped: not enough free space"),
    N_("OK - copied and verified"),
    N_("OK - copied and verified (renamed: name already used by a different file)"),
    N_("DUPLICATE: identical file already in backup"),
    N_("not needed (already backed up on this drive)"),
    N_("OK - uploaded and verified"),
    N_("OK - uploaded (Google gave no SHA-256, checked while reading)"),
    N_("OK - reused from an earlier unfinished upload (moved, SHA-256 checked)"),
    N_("OK - linked to the file in the Copy on Google Drive (SHA-256 checked)"),
    N_("ERROR: Google Drive stored different data (SHA-256 mismatch)"),
    N_("ERROR: the stored file on Google Drive differs (SHA-256 mismatch) - not linked"),
    N_("ERROR: no longer on Google Drive and not in the backup – cannot be added"),
    N_("WARNING: a different file with this name is already on Google Drive - not overwritten"),
    N_("WARNING: uploaded, but the backup file differs from the SHA-256 recorded when it was "
       "backed up - the source drive may be damaged"),
    N_("STOPPED - Google Drive is full"), N_("STOPPED - Google sign-in is no longer valid"),
}
# known beginnings of a plain English status: the rest (a detail, an error text) is kept
_PREFIXES = (
    ("ERROR: ", N_("ERROR: %s")), ("WARNING: ", N_("WARNING: %s")),
    ("STOPPED - ", N_("STOPPED - %s")), ("PROBLEM: ", N_("PROBLEM: %s")),
    ("ATTENTION - ", N_("ATTENTION - %s")), ("drive error: ", N_("drive error: %s")),
    ("OK - linked to the stored file (SHA-256 checked, from ",
     N_("OK - linked to the stored file (SHA-256 checked, from %s")),
)
_ABORTED = re.compile(r"^ABORTED \((.*)\)$", re.S)


def shown(value):
    """The text to show for a value (see the module docstring); non-texts are returned as they are."""
    if isinstance(value, Shown):
        return value.local
    if not isinstance(value, str) or not value:
        return value
    if value in _KNOWN:
        return tr(value)
    for prefix, template in _PREFIXES:
        if value.startswith(prefix):
            return tr(template, shown(value[len(prefix):]))
    m = _ABORTED.match(value)
    if m:
        return tr("ABORTED (%s)", shown(m.group(1)))
    return value


def english(value):
    """Back from a SHOWN status (e.g. read from a report written in German) to the English status
    the program compares – the reverse of shown() for the known statuses, in every language."""
    if not isinstance(value, str) or not value or value in _KNOWN:
        return value
    from . import i18n
    for lang in i18n.languages():
        for en in _KNOWN:
            t = lang.texts.get(en)
            if isinstance(t, str) and t == value:
                return en
    return value


def unique_basename(directory, base, when):
    """'Backup Pixel 10 Pro Sam 2026-11-02' - adds the time only if that name is taken."""
    directory = Path(directory)
    candidates = [f"{base} {when:%Y-%m-%d}", f"{base} {when:%Y-%m-%d %H-%M}",
                  f"{base} {when:%Y-%m-%d %H-%M-%S}"]
    for c in candidates:
        c = safe_name(c)
        if not any((directory / (c + ext)).exists() for ext in (".txt", ".html", ".csv")):
            return c
    i = 2
    while True:
        c = safe_name(f"{candidates[-1]} ({i})")
        if not (directory / (c + ".txt")).exists():
            return c
        i += 1


def write_reports(directory, basename, title, verdict_ok, verdict, sections, columns, rows):
    """sections: [(heading, [(key, value), ...]), ...]; rows: list of lists matching columns.
    Headings, keys, columns and title come translated; the verdict, values and cells go through
    shown() (English statuses -> the chosen language). `basename` is used as given (English)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    p = directory / (basename + ".txt")
    p.write_text(_txt(title, verdict, sections, columns, rows), encoding="utf-8")
    paths.append(p)
    p = directory / (basename + ".html")
    p.write_text(_html(title, verdict_ok, verdict, sections, columns, rows), encoding="utf-8")
    paths.append(p)
    p = directory / (basename + ".csv")
    # utf-8-sig + ';' opens correctly in Excel/LibreOffice with German or English settings
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(columns)
        w.writerows([csv_cell(shown(v)) for v in row] for row in rows)
    paths.append(p)
    return paths


def _file_list_heading(n):
    return trp("File list (%d entry)", "File list (%d entries)", n, n)


def _txt(title, verdict, sections, columns, rows):
    out = [title, "=" * len(title), "", f">>> {shown(verdict)}", ""]
    for heading, items in sections:
        out += [heading, "-" * len(heading)]
        width = max((len(k) for k, _ in items), default=0)
        for k, v in items:
            lines = str(shown(v)).splitlines() or [""]
            out.append(f"  {k.ljust(width)} : {lines[0]}")
            for extra in lines[1:]:
                out.append(f"  {' ' * width}   {extra}")
        out.append("")
    heading = _file_list_heading(len(rows))
    out += [heading, "-" * len(heading)]
    if not rows:
        out.append("  " + tr("(no files in this run)"))
    width = max(len(c) for c in columns[2:]) if len(columns) > 2 else 0
    for r in rows:
        out.append(f"[{r[0]}] {shown(r[1])}")
        for c, v in zip(columns[2:], r[2:]):
            if v not in ("", None):
                out.append(f"     {c.ljust(width)} : {shown(v)}")
    out.append("")
    return "\n".join(out)


_CSS = """
:root{--bg:#ffffff;--fg:#1d1f23;--muted:#5f6670;--line:#e3e6ea;--head:#f4f6f8;
--ok:#1f7a3d;--okbg:#e7f5ec;--bad:#b42318;--badbg:#fdecea}
@media (prefers-color-scheme:dark){:root{--bg:#16181b;--fg:#e6e8eb;--muted:#9aa1ab;
--line:#2c3036;--head:#1f2226;--ok:#6fd394;--okbg:#14301f;--bad:#ff8a80;--badbg:#3a1714}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 12px}h2{font-size:16px;margin:28px 0 8px}
.verdict{padding:12px 16px;border-radius:8px;font-weight:600;margin-bottom:8px}
.ok{background:var(--okbg);color:var(--ok)}.bad{background:var(--badbg);color:var(--bad)}
table{border-collapse:collapse;width:100%}td,th{padding:6px 10px;border-bottom:1px solid var(--line);
text-align:left;vertical-align:top}th{background:var(--head);position:sticky;top:0}
.kv td:first-child{color:var(--muted);width:280px;white-space:nowrap}
.files{font-size:12.5px}.files td{word-break:break-all}.wrap{overflow-x:auto}
.err{color:var(--bad);font-weight:600}
"""


def _cell(v):
    # red is decided on the English value, before it is translated
    cls = ' class="err"' if str(v).startswith(("ERROR", "MISMATCH", "WARNING")) else ""
    v = shown(v)
    s = html.escape(str(v if v is not None else ""))
    s = s.replace("\n", "<br>")
    return f"<td{cls}>{s}</td>"


def _html(title, verdict_ok, verdict, sections, columns, rows):
    lang = i18n.current()
    h = [f"<!doctype html><html lang='{html.escape(lang.locale or lang.code)}'"
         f"{' dir=rtl' if lang.rtl else ''}><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body><main>",
         f"<h1>{html.escape(title)}</h1>",
         f"<div class='verdict {'ok' if verdict_ok else 'bad'}'>{html.escape(shown(verdict))}</div>"]
    for heading, items in sections:
        h.append(f"<h2>{html.escape(heading)}</h2><table class='kv'>")
        for k, v in items:
            h.append(f"<tr><td>{html.escape(k)}</td>{_cell(v)}</tr>")
        h.append("</table>")
    h.append(f"<h2>{html.escape(_file_list_heading(len(rows)))}</h2>"
             "<div class='wrap'><table class='files'><tr>")
    h += [f"<th>{html.escape(c)}</th>" for c in columns]
    h.append("</tr>")
    for r in rows:
        h.append("<tr>" + "".join(_cell(v) for v in r) + "</tr>")
    h.append("</table></div></main></body></html>")
    return "\n".join(h)
