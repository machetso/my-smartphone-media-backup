"""The incremental phone -> external drive(s) backup run."""

import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import ui
from .copier import Cancelled, sha256_file, stream_copy
from .index import INTERNAL_DIR, BackupIndex
from .layout import keep_structure_placement, relative_dir, safe_name, unique_path
from .media import CATEGORY_LABEL, category_for, detect_date
from .report import unique_basename, write_reports
from .sources import PhoneHasher

MIN_FREE = 50 * 1024 * 1024     # a drive with less free space than this counts as full
MAX_ATTEMPTS = 3


@dataclass(eq=False)
class Dest:
    label: str
    base: Path
    parent: Path
    index: BackupIndex
    alive: bool = True
    problem: str = ""
    written: int = 0
    written_bytes: int = 0
    errors: int = 0

    plan = "simple"

    @property
    def home(self):
        """The backup folder ('Phone - Owner'); for a GFS plan the run folder is `parent`."""
        return self.parent

    @property
    def report_dir(self):
        return self.parent

    @property
    def tmp(self):
        return self.home / INTERNAL_DIR / "tmp"

    def existing(self, final):
        """The file already at this place in the backup (None if free)."""
        return final if Path(final).exists() else None

    def on_written(self, rel, size, mtime, sha):
        pass


@dataclass
class FileResult:
    sf: object
    category: str
    taken: datetime = None
    date_source: str = ""
    sha: str = ""
    transfer_check: str = ""
    per_dest: dict = field(default_factory=dict)   # label -> (status, location)

    @property
    def ok(self):
        return bool(self.per_dest) and all(not s.startswith("ERROR") for s, _ in self.per_dest.values())

    @property
    def newly_written(self):
        return any(s.startswith("OK") for s, _ in self.per_dest.values())


def backup_parent_name(phone_name, owner):
    return safe_name(f"{phone_name} - {owner}")


def _check_dest_alive(d):
    try:
        if not d.home.is_dir():
            d.alive, d.problem = False, "drive disconnected or folder no longer reachable"
        elif shutil.disk_usage(d.home).free < MIN_FREE:
            d.alive, d.problem = False, "drive is full"
    except OSError as e:
        d.alive, d.problem = False, f"drive error: {e}"


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _copy_one(source, sf, cat, targets, hasher, cfg, prog, cancel=None, placement=None):
    res = FileResult(sf=sf, category=cat)
    stream_sha, wres, last_err = None, None, ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        temps = [d.tmp / f"{uuid.uuid4().hex}.part" for d in targets]
        counted = [0]

        def on_bytes(n):
            counted[0] += n
            prog.update(add_bytes=n, current=sf.name)

        try:
            stream_sha, n, wres = stream_copy(source.open_stream(sf), temps,
                                              fsync=cfg.get("fsync", True), on_bytes=on_bytes,
                                              cancel=cancel)
        except Cancelled:
            for t in temps:
                _remove(t)
            raise
        except Exception as e:  # noqa: BLE001
            stream_sha, n, wres = None, -1, None
            last_err = f"reading from the source failed: {e}"
        if stream_sha is not None and n != sf.size:
            last_err = f"incomplete transfer ({n} of {sf.size} bytes)"
            stream_sha = None
        if stream_sha is not None and hasher is not None:
            phone_sha = hasher.get(sf.rel)
            if phone_sha is None:
                res.transfer_check = "n/a (source could not hash this file)"
            elif phone_sha != stream_sha:
                last_err = "MISMATCH between source hash and received data"
                stream_sha = None
            else:
                res.transfer_check = "OK (SHA-256 at source = received)"
        elif stream_sha is not None:
            res.transfer_check = (f"n/a ({source.kind}: no hash on the phone; "
                                  "copies compared with the received data)")
        if stream_sha is not None:
            break
        for t in temps:
            _remove(t)
        prog.bytes -= counted[0]
        if attempt < MAX_ATTEMPTS and source.is_connected():
            time.sleep(1)
            continue
        break

    if stream_sha is None:
        for d in targets:
            res.per_dest[d.label] = (f"ERROR: {last_err}", "")
            d.errors += 1
        res.transfer_check = f"ERROR: {last_err}"
        return res

    res.sha = stream_sha
    good = []
    for d, w in zip(targets, wres):
        if w.error:
            res.per_dest[d.label] = (f"ERROR: write failed ({w.error})", "")
        elif w.sha256 != stream_sha:
            res.per_dest[d.label] = ("ERROR: verification failed (hash of written copy differs)", "")
        else:
            good.append((d, w))
            continue
        d.errors += 1
        _remove(w.path)
        _check_dest_alive(d)
    if not good:
        return res

    taken, how = detect_date(good[0][1].path, sf.name, sf.mtime)
    res.taken, res.date_source = taken, how
    placement = placement or getattr(source, "placement", None)
    reldir = placement(sf, taken, cat) if placement else relative_dir(taken, cat)

    for d, w in good:
        try:
            existing = d.index.find_by_sha(stream_sha)
            if existing:
                _remove(w.path)
                d.index.add(sf.source_key, sf.size, sf.mtime, stream_sha, existing, cat, taken, how)
                res.per_dest[d.label] = ("DUPLICATE: identical file already in backup", existing)
                continue
            final = d.parent / reldir / safe_name(sf.name)
            status = "OK - copied and verified"
            there = d.existing(final)
            if there is not None:
                if there.stat().st_size == sf.size and sha256_file(there) == stream_sha:
                    _remove(w.path)
                    rel = final.relative_to(d.parent).as_posix()
                    d.index.add(sf.source_key, sf.size, sf.mtime, stream_sha, rel, cat, taken, how)
                    res.per_dest[d.label] = ("DUPLICATE: identical file already in backup", rel)
                    continue
                # GFS: a name is also taken when an earlier backup of the chain has it
                final = unique_path(final, taken=lambda p: d.existing(p) is not None)
                status = "OK - copied and verified (renamed: name already used by a different file)"
            final.parent.mkdir(parents=True, exist_ok=True)   # year/month folder only when needed
            os.replace(w.path, final)
            if sf.mtime:
                try:
                    os.utime(final, (sf.mtime, sf.mtime))
                except OSError:
                    pass
            rel = final.relative_to(d.parent).as_posix()
            d.index.add(sf.source_key, sf.size, sf.mtime, stream_sha, rel, cat, taken, how)
            d.on_written(rel, sf.size, sf.mtime, stream_sha)
            d.written += 1
            d.written_bytes += sf.size
            res.per_dest[d.label] = (status, rel)
        except OSError as e:
            _remove(w.path)
            d.errors += 1
            res.per_dest[d.label] = (f"ERROR: {e}", "")
            _check_dest_alive(d)
    return res


def perform_backup(source, phone_name, owner, folders, dest_bases, cfg, interactive=True, cancel=None,
                   parent_name=None, mode="backup", source_label="", keep_structure=False):
    """Run one backup (or, with mode="import", an import of a folder into an existing backup).

    Returns (status, report paths, file results, verdict text).
    """
    started = datetime.now()
    t0 = time.monotonic()
    # keep_structure: folders other than the camera folder keep their path (user request 2026-11-04)
    placement = keep_structure_placement(folders) if keep_structure else None
    where = "in the source folder" if mode == "import" else "on the phone"
    parent_name = parent_name or backup_parent_name(phone_name, owner)
    from . import plans                       # backup plan per drive: simple or Grandfather-Father-Son
    dests = []
    for i, base in enumerate(dest_bases, 1):
        want = plans.plan_of(cfg, base)
        have = plans.folder_plan(Path(base) / parent_name)
        if have and have != want and mode != "import":
            ui.warn(f"  Destination {i}: {plans.check_switch(base, parent_name, want)} – this backup "
                    f"uses the plan “{plans.NAMES[have]}” of the existing folder.")
        if (have or want) == plans.GFS:
            d = plans.open_gfs(f"Destination {i}", base, parent_name, started)
        else:
            parent = Path(base) / parent_name
            parent.mkdir(parents=True, exist_ok=True)
            d = Dest(f"Destination {i}", Path(base), parent, BackupIndex(parent))
        shutil.rmtree(d.tmp, ignore_errors=True)          # leftovers of an interrupted run
        d.tmp.mkdir(parents=True, exist_ok=True)
        dests.append(d)
    if hasattr(source, "staging"):
        source.staging = dests[0].home / INTERNAL_DIR / "staging"

    ui.info(f"Reading the file list {'of the source folder' if mode == 'import' else 'from the phone'} ...")
    files, missing = source.list_files(folders)
    for m in missing:
        ui.warn(f"  Folder not found {where}: {m or source.root}")
    supported, unsupported = [], []
    classify = getattr(source, "category_of", None) or (lambda f: category_for(f.name))
    for sf in files:
        cat = classify(sf)
        (supported if cat else unsupported).append((sf, cat))

    todo, already = [], 0
    for sf, cat in supported:
        need = [d for d in dests if not d.index.has(sf.source_key, sf.size)]
        if need:
            todo.append((sf, cat, need))
        else:
            already += 1
    total_bytes = sum(sf.size for sf, _, _ in todo)

    ui.info(f"  {len(supported)} photos/videos {where}, {already} already backed up, "
            f"{len(todo)} new ({ui.human_size(total_bytes)}).")
    if unsupported:
        ui.info(f"  {len(unsupported)} other files are skipped "
                f"({getattr(source, 'skip_text', 'not photo/video')}).")

    for d in dests:
        needed = sum(sf.size for sf, _, need in todo if d in need) + plans.carry_bytes(d)
        free = shutil.disk_usage(d.home).free
        if needed > free - MIN_FREE:
            ui.warn(f"  {d.label} ({d.base}) has only {ui.human_size(free)} free, "
                    f"needs {ui.human_size(needed)}.")
            if interactive and not ui.ask_yes_no("  Use this drive anyway (copies until it is full)?", False):
                d.alive, d.problem = False, "skipped: not enough free space"

    status = "COMPLETED"
    results = []
    hasher = None
    prog = ui.Progress(len(todo), total_bytes)
    if not any(d.alive for d in dests):
        status = "ABORTED (no usable destination)"
        todo = []
    try:
        if todo and source.supports_phone_hash:
            hasher = PhoneHasher(source, [sf.rel for sf, _, _ in todo])
            hasher.start()
        if todo and hasattr(source, "prefetch"):     # Wi-Fi phone app: fetch ahead
            source.prefetch([sf for sf, _, _ in todo])
        for i, (sf, cat, need) in enumerate(todo, 1):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            targets = [d for d in need if d.alive]
            if not targets:
                r = FileResult(sf=sf, category=cat)
                for d in need:
                    r.per_dest[d.label] = (f"ERROR: destination unavailable ({d.problem})", "")
                results.append(r)
                continue
            r = _copy_one(source, sf, cat, targets, hasher, cfg, prog, cancel, placement)
            for d in need:
                if d not in targets:
                    r.per_dest[d.label] = (f"ERROR: destination unavailable ({d.problem})", "")
            results.append(r)
            prog.update(files_done=i, current=sf.name)
            if not any(d.alive for d in dests):
                status = "ABORTED (no destination drive left)"
                break
            if not r.ok and r.transfer_check.startswith("ERROR") and not source.is_connected():
                status = ("ABORTED (source folder no longer reachable)" if mode == "import"
                          else "ABORTED (phone disconnected)")
                break
    except (KeyboardInterrupt, Cancelled):
        status = "CANCELLED by user"
    finally:
        prog.finish()
        if hasher:
            hasher.stop()
        source.close()
        for d in dests:
            shutil.rmtree(d.tmp, ignore_errors=True)
            if hasattr(source, "staging"):
                shutil.rmtree(d.home / INTERNAL_DIR / "staging", ignore_errors=True)
    for d in dests:                           # GFS: full/differential also get the earlier files
        if d.plan == plans.GFS:
            status = plans.finish_gfs(d, status, cfg, cancel)

    finished = datetime.now()
    duration = time.monotonic() - t0
    paths, verdict = _write_backup_reports(source, phone_name, owner, folders, missing, dests, results,
                                           unsupported, len(supported), already, status, started,
                                           finished, duration, mode, source_label, parent_name)
    for d in dests:
        d.index.close()
        plans.close(d)
    return status, paths, results, verdict


def _write_backup_reports(source, phone_name, owner, folders, missing, dests, results,
                          unsupported, n_supported, already, status, started, finished, duration,
                          mode="backup", source_label="", parent_name=""):
    importing = mode == "import"
    secured = [r for r in results if r.ok and r.newly_written]
    duplicates = [r for r in results if r.ok and not r.newly_written]
    failed = [r for r in results if not r.ok]
    by_cat = {c: [0, 0] for c in CATEGORY_LABEL}
    for r in secured:
        by_cat[r.category][0] += 1
        by_cat[r.category][1] += r.sf.size
    total_n = sum(v[0] for v in by_cat.values())
    total_b = sum(v[1] for v in by_cat.values())

    all_ok = status == "COMPLETED" and not failed and all(d.alive for d in dests)
    if all_ok:
        verdict = (f"EVERYTHING COPIED CORRECTLY - {total_n} new files ({ui.human_size(total_b)}) "
                   f"secured and verified with SHA-256 on {len(dests)} destination(s).")
        if duplicates:
            verdict += f" {len(duplicates)} identical duplicate(s) were recognised and not stored twice."
    else:
        problems = []
        if status != "COMPLETED":
            problems.append(status)
        if failed:
            problems.append(f"{len(failed)} file(s) with errors (see list)")
        for d in dests:
            if not d.alive:
                problems.append(f"{d.label}: {d.problem}")
        verdict = "ATTENTION - " + "; ".join(problems)

    speed = total_b / duration if duration > 0 else 0
    if importing:
        general = [("Imported folder", getattr(source, "folders_text", "") or str(source.root))]
        if phone_name:
            general += [("Smartphone", phone_name), ("Owner", owner)]
        general += [("Imported into backup", parent_name),
                    ("Import date", f"{started:%Y-%m-%d}")]
    else:
        general = [("Smartphone", phone_name),
                   ("Owner", owner),
                   ("Backup date", f"{started:%Y-%m-%d}")]
    general += [
        ("Status", status),
        ("Started", f"{started:%Y-%m-%d %H:%M:%S}"),
        ("Finished", f"{finished:%Y-%m-%d %H:%M:%S}"),
        ("Duration", ui.human_duration(duration)),
    ]
    if not importing:
        general.append(("Connection", f"{source.kind} - {source.description}"))
    if getattr(source, "fallback_reason", None):
        general.append(("ADB fallback", f"ADB did not work ({source.fallback_reason}); "
                                        f"{source.kind} was used instead"))
    if not importing:
        general.append(("Folders on phone", ", ".join(folders)))
    if missing:
        general.append(("Folders NOT found", ", ".join(missing)))

    data = [
        ("Total secured this run", f"{total_n} files, {ui.human_size(total_b)} ({total_b:,} bytes)"),
        ("Photos", f"{by_cat['photo'][0]} files, {ui.human_size(by_cat['photo'][1])}"),
        ("Videos", f"{by_cat['video'][0]} files, {ui.human_size(by_cat['video'][1])}"),
        ("RAW", f"{by_cat['raw'][0]} files, {ui.human_size(by_cat['raw'][1])}"),
    ] + [
        (CATEGORY_LABEL[c] + " (other/)", f"{by_cat[c][0]} files, {ui.human_size(by_cat[c][1])}")
        for c in ("other-photo", "other-video", "other-file") if by_cat[c][0]
    ] + [
        ("Average speed", f"{ui.human_size(speed)}/s"),
        ("Photos/videos found " + ("in the source" if importing else "on phone"), str(n_supported)),
        ("Already backed up before (skipped)", str(already)),
        ("Identical duplicates (not stored twice)", str(len(duplicates))),
        ("Files with errors", str(len(failed))),
        (f"Other files skipped ({getattr(source, 'skip_text', 'not photo/video')})", str(len(unsupported))),
    ]
    dest_items = []
    for d in dests:
        state = "OK" if d.alive else f"PROBLEM: {d.problem}"
        tot = d.index.totals()
        content = ", ".join(f"{CATEGORY_LABEL.get(c, c)}: {n} files / {ui.human_size(b)}"
                            for c, (n, b) in sorted(tot.items()))
        dest_items += [(f"{d.label}", str(d.parent)),
                       (f"{d.label} backup plan", d.describe() if hasattr(d, "describe") else
                        "Simple – one folder, only new files are added"),
                       (f"{d.label} state", state),
                       (f"{d.label} this run", f"{d.written} files written, {ui.human_size(d.written_bytes)}, "
                                               f"{d.errors} errors"),
                       (f"{d.label} whole backup", content or "empty")]
        if getattr(d, "carried", 0):
            dest_items.append((f"{d.label} earlier files in this {d.mode} backup",
                               f"{d.carried} files, {ui.human_size(d.carried_bytes)} (copied on the drive)"))
    method = [("Source -> computer" if importing else "Phone -> computer",
               ("SHA-256 of every source file calculated separately and compared with the copied data"
                if importing else "SHA-256 calculated on the phone and compared with the received data")
               if source.supports_phone_hash else
               f"{source.kind}: SHA-256 of the received data (no hash possible on the phone "
               "with this connection)"),
              ("Computer -> drive", "every copy is flushed to disk, read back and its SHA-256 compared"),
              ("Interrupted copies", "files are written as temporary files and only renamed after a "
                                     "successful check - there are no half-copied files")]
    sections = [("General", general), ("Data secured", data), ("Destinations", dest_items),
                ("Verification method", method)]

    columns = ["Nr", "File", "Type", "Size", "Bytes", "Date taken", "Date from",
               "Path in source" if importing else "Phone path",
               "Transfer check", "SHA-256"]
    for d in dests:
        columns += [f"{d.label} status", f"{d.label} location"]
    rows = []
    for i, r in enumerate(results, 1):
        row = [i, r.sf.name, CATEGORY_LABEL[r.category], ui.human_size(r.sf.size), r.sf.size,
               f"{r.taken:%Y-%m-%d %H:%M:%S}" if r.taken else "", r.date_source, r.sf.rel,
               r.transfer_check, r.sha]
        for d in dests:
            st, loc = r.per_dest.get(d.label, ("not needed (already backed up on this drive)", ""))
            row += [st, loc]
        rows.append(row)
    n = len(rows)
    for sf, _ in unsupported:
        n += 1
        rows.append([n, sf.name, "other", ui.human_size(sf.size), sf.size, "", "", sf.rel,
                     "", ""] + [f"skipped ({getattr(source, 'skip_text', 'not a photo/video file')})",
                                ""] * len(dests))

    if importing:
        title = f"Import {source_label} into {parent_name} - {started:%Y-%m-%d %H:%M}"
        report_base = f"Import {source_label}"
    else:
        title = f"Backup {phone_name} - {owner} - {started:%Y-%m-%d %H:%M}"
        report_base = f"Backup {phone_name} {owner}"
    paths = []
    basename = None
    for d in dests:
        rdir = d.report_dir
        try:
            if basename is None or (rdir / (basename + ".txt")).exists():
                basename = unique_basename(rdir, report_base, started)
            paths += write_reports(rdir, basename, title, all_ok, verdict, sections, columns, rows)
        except OSError as e:
            ui.error(f"Could not write report to {rdir}: {e}")
    if all_ok:
        ui.ok(verdict)
    else:
        ui.error(verdict)
    return paths, verdict
