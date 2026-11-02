"""Write the copy report as .txt, .html and .csv (same content, three formats)."""

import csv
import html
from pathlib import Path

from .layout import safe_name


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
    """sections: [(heading, [(key, value), ...]), ...]; rows: list of lists matching columns."""
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
        w.writerows(rows)
    paths.append(p)
    return paths


def _txt(title, verdict, sections, columns, rows):
    out = [title, "=" * len(title), "", f">>> {verdict}", ""]
    for heading, items in sections:
        out += [heading, "-" * len(heading)]
        width = max((len(k) for k, _ in items), default=0)
        for k, v in items:
            lines = str(v).splitlines() or [""]
            out.append(f"  {k.ljust(width)} : {lines[0]}")
            for extra in lines[1:]:
                out.append(f"  {' ' * width}   {extra}")
        out.append("")
    heading = f"File list ({len(rows)} entries)"
    out += [heading, "-" * len(heading)]
    if not rows:
        out.append("  (no files in this run)")
    width = max(len(c) for c in columns[2:]) if len(columns) > 2 else 0
    for r in rows:
        out.append(f"[{r[0]}] {r[1]}")
        for c, v in zip(columns[2:], r[2:]):
            if v not in ("", None):
                out.append(f"     {c.ljust(width)} : {v}")
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
    s = html.escape(str(v if v is not None else ""))
    s = s.replace("\n", "<br>")
    cls = ' class="err"' if str(v).startswith(("ERROR", "MISMATCH", "WARNING")) else ""
    return f"<td{cls}>{s}</td>"


def _html(title, verdict_ok, verdict, sections, columns, rows):
    h = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body><main>",
         f"<h1>{html.escape(title)}</h1>",
         f"<div class='verdict {'ok' if verdict_ok else 'bad'}'>{html.escape(verdict)}</div>"]
    for heading, items in sections:
        h.append(f"<h2>{html.escape(heading)}</h2><table class='kv'>")
        for k, v in items:
            h.append(f"<tr><td>{html.escape(k)}</td>{_cell(v)}</tr>")
        h.append("</table>")
    h.append(f"<h2>File list ({len(rows)} entries)</h2><div class='wrap'><table class='files'><tr>")
    h += [f"<th>{html.escape(c)}</th>" for c in columns]
    h.append("</tr>")
    for r in rows:
        h.append("<tr>" + "".join(_cell(v) for v in r) + "</tr>")
    h.append("</table></div></main></body></html>")
    return "\n".join(h)
