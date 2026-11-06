"""Grandfather-Father-Son scheme for the second storage (user decisions 2026-11-05).

Which export type is due (exports are started by hand, so it goes by the time since the last ones):
  Grandfather = FULL          when the last complete full export is 3 months old (or there is none)
  Father      = DIFFERENTIAL  when the last complete full/differential export is 1 month old
  Son         = INCREMENTAL   otherwise (every export in between)

Cleanup: GFS keeps the newest 4 grandfathers, 3 fathers and 6 sons. Older exports are only
SUGGESTED for removal and deleted after the user confirms - and never one that a kept export still
needs for its restore:
  full          -> itself
  differential  -> its full + itself
  incremental   -> its full + the newest complete differential before it (if any) + every export
                   after that up to itself
"""

from datetime import datetime

from .i18n import N_, tr, trp

REMOVED = "REMOVED"
FULL_MONTHS = 3
DIFF_MONTHS = 1
KEEP = {"full": 4, "differential": 3, "incremental": 6}
# English names – show them with tr(ROLE[mode]); the mode itself (full/…) is stored, never translated
ROLE = {"full": N_("Grandfather"), "differential": N_("Father"), "incremental": N_("Son")}
MODE_NAME = {"full": N_("full"), "differential": N_("differential"), "incremental": N_("incremental")}


def mode_name(mode):
    """'full' / 'differential' / 'incremental' as shown (the English word stays in folder names)."""
    return tr(MODE_NAME[mode]) if mode in MODE_NAME else mode


def add_months(dt, n):
    m = dt.month - 1 + n
    y = dt.year + m // 12
    m = m % 12 + 1
    # last day of the target month if the day does not exist (31 Jan + 1 month -> 28/29 Feb)
    for day in (dt.day, 30, 29, 28):
        try:
            return dt.replace(year=y, month=m, day=min(dt.day, day))
        except ValueError:
            continue
    return dt.replace(year=y, month=m, day=28)


def _when(run):
    return datetime.fromisoformat(run.started)


def active(runs):
    return [r for r in runs if r.status != REMOVED]


def _done(r):
    return r.status == "COMPLETED"


def choose(runs, now=None, full_months=FULL_MONTHS, diff_months=DIFF_MONTHS):
    """(mode, reason) for the next export – the reason is shown text (chosen language)."""
    now = now or datetime.now()
    runs = active(runs)
    fulls = [r for r in runs if r.type == "full" and _done(r)]
    if not fulls:
        return "full", tr("there is no complete full export on this storage yet")
    full = fulls[-1]
    if now >= add_months(_when(full), full_months):
        return "full", trp("the last full export (%s) is more than %d month old",
                           "the last full export (%s) is more than %d months old", full_months,
                           f"{_when(full):%Y-%m-%d}", full_months)
    diffs = [r for r in runs if r.type == "differential" and _done(r) and r.id > full.id]
    last = diffs[-1] if diffs else full
    if now >= add_months(_when(last), diff_months):
        when = f"{_when(last):%Y-%m-%d}"
        if diffs:
            return "differential", trp("the last differential export (%s) is more than %d month old",
                                       "the last differential export (%s) is more than %d months old",
                                       diff_months, when, diff_months)
        return "differential", trp("the last full export (%s) is more than %d month old",
                                   "the last full export (%s) is more than %d months old",
                                   diff_months, when, diff_months)
    due = add_months(_when(last), diff_months)
    if diffs:
        why = tr("the last differential export is from %s – the next differential is due from %s",
                 f"{_when(last):%Y-%m-%d}", f"{due:%Y-%m-%d}")
    else:
        why = tr("the last full export is from %s – the next differential is due from %s",
                 f"{_when(last):%Y-%m-%d}", f"{due:%Y-%m-%d}")
    return "incremental", why


def chain(runs, upto_id):
    """The exports needed to restore the state of export `upto_id` (oldest first)."""
    runs = [r for r in active(runs) if r.id <= upto_id]
    target = next((r for r in runs if r.id == upto_id), None)
    if target is None:
        return []
    if target.type == "full" and _done(target):
        return [target]
    fulls = [r for r in runs if r.type == "full" and _done(r) and r.id < upto_id]
    if not fulls:
        return []
    full = fulls[-1]
    if target.type == "differential":
        return [full, target]
    diffs = [r for r in runs if r.type == "differential" and _done(r) and full.id < r.id < upto_id]
    start = diffs[-1] if diffs else full
    return [full] + ([start] if diffs else []) + [r for r in runs if start.id < r.id <= upto_id]


def keep_set(runs, keep=None):
    """Runs GFS keeps (newest N per type) - always including the newest export."""
    keep = keep or KEEP
    runs = active(runs)
    kept = set()
    for t, n in keep.items():
        done = [r for r in runs if r.type == t and _done(r)]
        kept.update(r.id for r in done[-n:] if n > 0)
    if runs:
        kept.add(runs[-1].id)
    return kept


def to_retire(runs, keep=None):
    """Exports GFS would remove: not kept and not needed by any kept export's restore."""
    runs_a = active(runs)
    needed = set()
    for rid in keep_set(runs_a, keep):
        needed.update(r.id for r in chain(runs_a, rid))
        needed.add(rid)
    return [r for r in runs_a if r.id not in needed and r.status != "RUNNING"]


def label(run):
    """Shown text, e.g. 'Grandfather (full)' in the chosen language."""
    return tr("%s (%s)", tr(ROLE[run.type]) if run.type in ROLE else "?", mode_name(run.type))
