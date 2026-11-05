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

REMOVED = "REMOVED"
FULL_MONTHS = 3
DIFF_MONTHS = 1
KEEP = {"full": 4, "differential": 3, "incremental": 6}
ROLE = {"full": "Grandfather", "differential": "Father", "incremental": "Son"}


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
    """(mode, reason) for the next export."""
    now = now or datetime.now()
    runs = active(runs)
    fulls = [r for r in runs if r.type == "full" and _done(r)]
    if not fulls:
        return "full", "there is no complete full export on this storage yet"
    full = fulls[-1]
    if now >= add_months(_when(full), full_months):
        return "full", (f"the last full export ({_when(full):%Y-%m-%d}) is more than "
                        f"{full_months} months old")
    diffs = [r for r in runs if r.type == "differential" and _done(r) and r.id > full.id]
    last = diffs[-1] if diffs else full
    if now >= add_months(_when(last), diff_months):
        what = "differential" if diffs else "full"
        return "differential", (f"the last {what} export ({_when(last):%Y-%m-%d}) is more than "
                                f"{diff_months} month{'s' if diff_months > 1 else ''} old")
    due = add_months(_when(last), diff_months)
    return "incremental", (f"the last {'differential' if diffs else 'full'} export is from "
                           f"{_when(last):%Y-%m-%d} – the next differential is due from {due:%Y-%m-%d}")


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
    return f"{ROLE.get(run.type, '?')} ({run.type})"
