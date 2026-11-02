"""Interactive terminal program (menus)."""

import os
import shutil
import sys
from pathlib import Path

from . import APP_NAME, __version__, config, ui
from .backup import backup_parent_name, perform_backup
from .export import MODES, Catalog, has_catalog, perform_export, perform_restore
from .importer import perform_import
from .keepawake import KeepAwake
from .layout import same_volume
from .locations import (describe_unmounted, detect_drives, detect_unmounted, find_backups,
                        mount_device, mount_for_paths)
from .sources import connect_source

PHONE_FOLDER_ROOTS = ["DCIM", "Pictures", "Movies", "Download",
                      "Android/media/com.whatsapp/WhatsApp/Media"]


def _awake(cfg, what, func, *args):
    """Run a long job while the computer is kept from going to standby / shutting down."""
    with KeepAwake(what, enabled=bool(cfg.get("keep_awake", True))) as ka:
        if ka.enabled:
            (ui.info if ka.active else ui.warn)(ka.message())
        return func(*args)


def _describe(path):
    if os.path.isdir(path):
        return f"{path}  (available, {ui.human_size(shutil.disk_usage(path).free)} free)"
    return f"{path}  (NOT connected)"


def add_location(default_folder):
    drives = detect_drives()
    unmounted = detect_unmounted()
    opts = ([f"{p}  ({ui.human_size(free)} free)" for p, free in drives] +
            [f"{describe_unmounted(d)}  - not mounted, will be mounted" for d in unmounted] +
            ["Type a path myself"])
    idx = ui.choose("Which drive", opts, default=1)
    drive = None
    if idx < len(drives):
        drive = drives[idx][0]
    elif idx < len(drives) + len(unmounted):
        d = unmounted[idx - len(drives)]
        drive, err = mount_device(d["device"])
        if not drive:
            ui.error(f"Could not mount {d['device']}: {err}")
            return None
        ui.ok(f"Mounted at {drive}")
        if not os.access(drive, os.W_OK):
            ui.error("The drive was mounted READ-ONLY (NTFS: run chkdsk /f in Windows or disable "
                     "Fast Startup) - it cannot be used for backups.")
            return None
    if drive:
        sub = ui.ask("Folder name on this drive", default_folder)
        path = str(Path(drive) / sub)
    else:
        path = ui.ask("Full path of the folder")
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        ui.error(f"Cannot create {path}: {e}")
        return None
    return str(Path(path).resolve())


def choose_locations(cfg, key, what, multiple, default_folder):
    for m in mount_for_paths(cfg.get(key, [])):
        ui.info(m)
    while True:
        locs = cfg.get(key, [])
        ui.info(f"\n{what}:")
        for i, p in enumerate(locs, 1):
            print(f"  {i}) {_describe(p)}")
        print("  a) add a new location")
        avail = [str(i) for i, p in enumerate(locs, 1) if os.path.isdir(p)]
        default = ",".join(avail) if multiple else (avail[0] if avail else "a")
        hint = "numbers, e.g. 1,2" if multiple else "number"
        ans = ui.ask(f"Choose ({hint})", default or "a").strip().lower()
        if ans == "a":
            p = add_location(default_folder)
            if p and p not in locs:
                cfg[key] = locs + [p]
                config.save(cfg)
            continue
        nums = ui.parse_numbers(ans, len(locs))
        chosen = [locs[n - 1] for n in nums if os.path.isdir(locs[n - 1])]
        if not multiple:
            chosen = chosen[:1]
        if chosen:
            return chosen
        ui.warn("  No connected location chosen.")


# ---------------------------------------------------------------- backup

def choose_phone_folders(source, cfg):
    folders = list(cfg.get("source_folders") or ["DCIM/Camera"])
    ui.info(f"\nFolders on the phone to back up: {', '.join(folders)}")
    if not ui.ask_yes_no("Change the folders?", False):
        return folders
    ui.info("Searching folders on the phone ...")
    candidates = []
    for root in PHONE_FOLDER_ROOTS:
        candidates += source.list_subfolders(root)
    candidates = sorted(set(candidates) | set(folders))
    while True:
        for i, c in enumerate(candidates, 1):
            print(f"  {i:2d}) [{'x' if c in folders else ' '}] {c}")
        ans = ui.ask("Numbers to switch on/off, a path to add, or Enter when done",
                     allow_empty=True)
        if not ans:
            break
        nums = ui.parse_numbers(ans, len(candidates))
        if nums:
            for n in nums:
                c = candidates[n - 1]
                folders.remove(c) if c in folders else folders.append(c)
        else:
            p = ans.strip().strip("/")
            if p.startswith("sdcard/"):
                p = p[len("sdcard/"):]
            folders.append(p)
            candidates = sorted(set(candidates) | {p})
    if not folders:
        folders = ["DCIM/Camera"]
    if ui.ask_yes_no("Remember these folders for next time?", True):
        cfg["source_folders"] = folders
        config.save(cfg)
    return folders


def backup_menu(cfg):
    ui.title("Backup: phone -> external drive(s)")
    owner = ui.ask("Name of the owner", cfg.get("owner") or None)
    cfg["owner"] = owner
    config.save(cfg)
    dests = choose_locations(cfg, "destinations", "Backup destinations (choose 1 or more drives)",
                             True, "PhoneBackups")
    ui.info("")
    source = connect_source(cfg)
    if source is None:
        ui.error("No phone - backup cancelled.")
        return
    phone = ui.ask("Name of the smartphone", source.device_name or None)
    folders = choose_phone_folders(source, cfg)
    ui.info("\nSummary:")
    ui.info(f"  Phone:   {phone}  ({source.kind})")
    ui.info(f"  Owner:   {owner}")
    ui.info(f"  Folders: {', '.join(folders)}")
    for d in dests:
        ui.info(f"  To:      {Path(d) / backup_parent_name(phone, owner)}")
    if not ui.ask_yes_no("Start the backup?", True):
        source.close()
        return
    status, paths, _, _ = _awake(cfg, "Backup", perform_backup, source, phone, owner, folders, dests, cfg)
    ui.info(f"\nStatus: {status}")
    for p in paths:
        if p.suffix == ".txt":
            ui.info(f"Report: {p}")


# ---------------------------------------------------------------- export / restore

def import_menu(cfg):
    ui.title("Import an old backup / any folder")
    src = ui.ask("Folder to import (it is only read, never changed)")
    sets = {}
    for p in find_backups(cfg):
        sets.setdefault(Path(p).name, []).append(p)
    if not sets:
        ui.error("No backup found on the connected drives - make a phone backup first.")
        return
    names = sorted(sets)
    name = names[ui.choose("Import into which backup", names)]
    ui.info("Copies that will be updated:")
    for p in sets[name]:
        ui.info(f"  {p}")
    if not ui.ask_yes_no("Start the import?", True):
        return
    try:
        status, paths, _, _ = _awake(cfg, "Import", perform_import, src, sets[name], cfg)
    except ValueError as e:
        ui.error(str(e))
        return
    ui.info(f"\nStatus: {status}")
    for p in paths:
        if p.suffix == ".txt":
            ui.info(f"Report: {p}")


def export_menu(cfg):
    ui.title("Export a backup to a second storage")
    backups = find_backups(cfg)
    opts = backups + ["Type the path of a backup folder"]
    idx = ui.choose("Which backup do you want to export", opts)
    src = backups[idx] if idx < len(backups) else ui.ask("Path of the backup folder (Phone - Owner)")
    if not os.path.isdir(src):
        ui.error("Folder not found.")
        return
    target = choose_locations(cfg, "export_targets", "Second storage", False, "PhoneBackups-Export")[0]
    if same_volume(src, target):
        ui.warn("WARNING: the second storage is on the SAME drive as the backup - "
                "this does not protect against a drive failure.")
        if not ui.ask_yes_no("Continue anyway?", False):
            return
    tparent = Path(target) / Path(src).name
    full = None
    if has_catalog(tparent):
        cat = Catalog(tparent)
        runs = cat.runs()
        full = cat.last_full()
        cat.close()
        ui.info("\nPrevious exports:")
        for r in runs[-8:]:
            ui.info(f"  {r.folder}  [{r.status}]")
    modes = ["full         - copy everything",
             "differential - everything new since the last FULL export",
             "incremental  - everything new since the LAST export (any type)"]
    if full is None:
        ui.info("\nNo full export exists yet on this storage - the first export must be 'full'.")
        mode = "full"
    else:
        mode = MODES[ui.choose("Export type", modes, default=3)]
    if not ui.ask_yes_no(f"Start the {mode} export of {src} to {tparent}?", True):
        return
    try:
        status, paths, _ = _awake(cfg, "Export", perform_export, src, target, mode, cfg)
    except (ValueError, OSError) as e:
        ui.error(str(e))
        return
    ui.info(f"\nStatus: {status}")
    ui.info(f"Report: {[str(p) for p in paths if p.suffix == '.txt'][0]}")


def restore_menu(cfg):
    ui.title("Restore a complete copy from the second storage")
    target = choose_locations(cfg, "export_targets", "Second storage", False, "PhoneBackups-Export")[0]
    sets = [e.path for e in sorted(os.scandir(target), key=lambda e: e.name)
            if e.is_dir() and has_catalog(e.path)]
    if not sets:
        ui.error("No exports found there.")
        return
    tparent = sets[ui.choose("Which export set", sets)]
    cat = Catalog(tparent)
    runs = cat.runs()
    cat.close()
    idx = ui.choose("Restore the state of which export",
                    [f"{r.folder}  [{r.status}]" for r in runs], default=len(runs))
    dest = ui.ask("Restore into which (new or empty) folder")
    if os.path.isdir(dest) and any(os.scandir(dest)):
        if not ui.ask_yes_no("The folder is not empty - existing files with the same name will be "
                             "overwritten. Continue?", False):
            return
    try:
        status, paths, _ = _awake(cfg, "Restore", perform_restore, tparent, runs[idx].id, dest, cfg)
    except (ValueError, OSError) as e:
        ui.error(str(e))
        return
    ui.info(f"\nStatus: {status}")


# ---------------------------------------------------------------- settings / main

def settings_menu(cfg):
    while True:
        ui.title("Settings")
        ui.info(f"  Settings file: {config.config_path()}")
        idx = ui.choose("Change", [
            f"Owner name ............ {cfg.get('owner') or '-'}",
            f"Folders on the phone .. {', '.join(cfg.get('source_folders', []))}",
            f"Backup destinations ... {len(cfg.get('destinations', []))} saved (remove)",
            f"Export targets ........ {len(cfg.get('export_targets', []))} saved (remove)",
            f"ADB program ........... {cfg.get('adb_path') or 'automatic'}",
            f"Wait for ADB phone .... {cfg.get('adb_wait_seconds')} s",
            f"Keep computer awake ... {'yes' if cfg.get('keep_awake', True) else 'no'} (during jobs)",
            "Back"], default=8)
        if idx == 0:
            cfg["owner"] = ui.ask("Owner name", cfg.get("owner") or None)
        elif idx == 1:
            txt = ui.ask("Folders, separated by commas", ", ".join(cfg.get("source_folders", [])))
            cfg["source_folders"] = [f.strip().strip("/") for f in txt.split(",") if f.strip()] or ["DCIM/Camera"]
        elif idx in (2, 3):
            key = "destinations" if idx == 2 else "export_targets"
            locs = cfg.get(key, [])
            if not locs:
                continue
            j = ui.choose("Remove which (the files stay on the drive)", locs + ["Cancel"], default=len(locs) + 1)
            if j < len(locs):
                cfg[key] = locs[:j] + locs[j + 1:]
        elif idx == 4:
            cfg["adb_path"] = ui.ask("Path to adb (empty = automatic)", allow_empty=True)
        elif idx == 5:
            v = ui.ask("Seconds", str(cfg.get("adb_wait_seconds", 20)))
            if v.isdigit():
                cfg["adb_wait_seconds"] = int(v)
        elif idx == 6:
            cfg["keep_awake"] = ui.ask_yes_no("Keep the computer from standby/shutdown while a job runs?",
                                              bool(cfg.get("keep_awake", True)))
        else:
            return
        config.save(cfg)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cfg = config.load()
    actions = {"backup": backup_menu, "import": import_menu, "export": export_menu, "restore": restore_menu,
               "settings": settings_menu}
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: smartphone_media_backup.py [backup|import|export|restore|settings]")
        return 0
    if argv and argv[0] in actions:
        actions[argv[0]](cfg)
        return 0
    while True:
        ui.title(f"{APP_NAME} {__version__}")
        idx = ui.choose("Choose", ["Backup phone -> external drive(s)",
                                   "Import an old backup / any folder into a backup",
                                   "Export a backup to a second storage (full / differential / incremental)",
                                   "Restore from the second storage",
                                   "Settings",
                                   "Exit"], default=1)
        if idx == 5:
            return 0
        try:
            [backup_menu, import_menu, export_menu, restore_menu, settings_menu][idx](cfg)
        except KeyboardInterrupt:
            ui.warn("\nCancelled.")
