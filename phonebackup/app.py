"""Interactive terminal program (menus)."""

import os
import shutil
import sys
from pathlib import Path

from . import APP_NAME, __version__, config, gfs, ui
from .backup import backup_parent_name, perform_backup
from .export import MODES, Catalog, has_catalog, perform_export, perform_restore
from .i18n import tr
from .importer import perform_import
from .keepawake import KeepAwake
from .layout import same_volume
from .locations import (describe_unmounted, detect_drives, detect_unmounted, find_backups,
                        mount_device, mount_for_paths)
from .report import shown
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
        return tr("%s  (available, %s free)", path, ui.human_size(shutil.disk_usage(path).free))
    return tr("%s  (NOT connected)", path)


def add_location(default_folder):
    drives = detect_drives()
    unmounted = detect_unmounted()
    opts = ([tr("%s  (%s free)", p, ui.human_size(free)) for p, free in drives] +
            [tr("%s  - not mounted, will be mounted", describe_unmounted(d)) for d in unmounted] +
            [tr("Type a path myself")])
    idx = ui.choose(tr("Which drive"), opts, default=1)
    drive = None
    if idx < len(drives):
        drive = drives[idx][0]
    elif idx < len(drives) + len(unmounted):
        d = unmounted[idx - len(drives)]
        drive, err = mount_device(d["device"])
        if not drive:
            ui.error(tr("Could not mount %s: %s", d["device"], err))
            return None
        ui.ok(tr("Mounted at %s", drive))
        if not os.access(drive, os.W_OK):
            ui.error(tr("The drive was mounted READ-ONLY (NTFS: run chkdsk /f in Windows or disable "
                        "Fast Startup) - it cannot be used for backups."))
            return None
    if drive:
        sub = ui.ask(tr("Folder name on this drive"), default_folder)
        path = str(Path(drive) / sub)
    else:
        path = ui.ask(tr("Full path of the folder"))
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        ui.error(tr("Cannot create %s: %s", path, e))
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
        print("  " + tr("a) add a new location"))
        avail = [str(i) for i, p in enumerate(locs, 1) if os.path.isdir(p)]
        default = ",".join(avail) if multiple else (avail[0] if avail else "a")
        prompt = tr("Choose (numbers, e.g. 1,2)") if multiple else tr("Choose (number)")
        ans = ui.ask(prompt, default or "a").strip().lower()
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
        ui.warn("  " + tr("No connected location chosen."))


# ---------------------------------------------------------------- backup

def choose_phone_folders(source, cfg):
    folders = list(cfg.get("source_folders") or ["DCIM/Camera"])
    ui.info("\n" + tr("Folders on the phone to back up: %s", ", ".join(folders)))
    if not ui.ask_yes_no(tr("Change the folders?"), False):
        return folders
    ui.info(tr("Searching folders on the phone ..."))
    candidates = []
    for root in PHONE_FOLDER_ROOTS:
        candidates += source.list_subfolders(root)
    candidates = sorted(set(candidates) | set(folders))
    while True:
        for i, c in enumerate(candidates, 1):
            print(f"  {i:2d}) [{'x' if c in folders else ' '}] {c}")
        ans = ui.ask(tr("Numbers to switch on/off, a path to add, or Enter when done"),
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
    if ui.ask_yes_no(tr("Remember these folders for next time?"), True):
        cfg["source_folders"] = folders
        config.save(cfg)
    return folders


def backup_menu(cfg):
    ui.title(tr("Backup: phone -> external drive(s)"))
    owner = ui.ask(tr("Name of the owner"), cfg.get("owner") or None)
    cfg["owner"] = owner
    config.save(cfg)
    dests = choose_locations(cfg, "destinations", tr("Backup destinations (choose 1 or more drives)"),
                             True, "PhoneBackups")
    ui.info("")
    source = connect_source(cfg)
    if source is None:
        ui.error(tr("No phone - backup cancelled."))
        return
    phone = ui.ask(tr("Name of the smartphone"), source.device_name or None)
    folders = choose_phone_folders(source, cfg)
    ui.info("\n" + tr("Summary:"))
    ui.info("  " + tr("Phone:   %s  (%s)", phone, source.kind))
    ui.info("  " + tr("Owner:   %s", owner))
    ui.info("  " + tr("Folders: %s", ", ".join(folders)))
    for d in dests:
        ui.info("  " + tr("To:      %s", Path(d) / backup_parent_name(phone, owner)))
    if not ui.ask_yes_no(tr("Start the backup?"), True):
        source.close()
        return
    status, paths, _, _ = _awake(cfg, "Backup", perform_backup, source, phone, owner, folders, dests, cfg)
    ui.info("\n" + tr("Status: %s", shown(status)))
    for p in paths:
        if p.suffix == ".txt":
            ui.info(tr("Report: %s", p))


# ---------------------------------------------------------------- export / restore

def import_menu(cfg):
    ui.title(tr("Import an old backup / any folder"))
    src = ui.ask(tr("Folder to import (it is only read, never changed)"))
    sets = {}
    for p in find_backups(cfg):
        sets.setdefault(Path(p).name, []).append(p)
    if not sets:
        ui.error(tr("No backup found on the connected drives - make a phone backup first."))
        return
    names = sorted(sets)
    name = names[ui.choose(tr("Import into which backup"), names)]
    ui.info(tr("Copies that will be updated:"))
    for p in sets[name]:
        ui.info(f"  {p}")
    if not ui.ask_yes_no(tr("Start the import?"), True):
        return
    try:
        status, paths, _, _ = _awake(cfg, "Import", perform_import, src, sets[name], cfg)
    except ValueError as e:
        ui.error(str(e))
        return
    ui.info("\n" + tr("Status: %s", shown(status)))
    for p in paths:
        if p.suffix == ".txt":
            ui.info(tr("Report: %s", p))


def export_menu(cfg):
    ui.title(tr("Export a backup to a second storage"))
    backups = find_backups(cfg)
    opts = backups + [tr("Type the path of a backup folder")]
    idx = ui.choose(tr("Which backup do you want to export"), opts)
    src = backups[idx] if idx < len(backups) else ui.ask(tr("Path of the backup folder (Phone - Owner)"))
    if not os.path.isdir(src):
        ui.error(tr("Folder not found."))
        return
    target = choose_locations(cfg, "export_targets", tr("Second storage"), False, "PhoneBackups-Export")[0]
    if same_volume(src, target):
        ui.warn(tr("WARNING: the second storage is on the SAME drive as the backup - "
                   "this does not protect against a drive failure."))
        if not ui.ask_yes_no(tr("Continue anyway?"), False):
            return
    tparent = Path(target) / Path(src).name
    full = None
    if has_catalog(tparent):
        cat = Catalog(tparent)
        runs = cat.runs()
        full = cat.last_full()
        cat.close()
        ui.info("\n" + tr("Previous exports:"))
        for r in runs[-8:]:
            ui.info(f"  {r.folder}  [{shown(r.status)}]")
    modes = [tr("full         - copy everything"),
             tr("differential - everything new since the last FULL export"),
             tr("incremental  - everything new since the LAST export (any type)")]
    if full is None:
        ui.info("\n" + tr("No full export exists yet on this storage - the first export must be 'full'."))
        mode = "full"
    else:
        mode = MODES[ui.choose(tr("Export type"), modes, default=3)]
    if not ui.ask_yes_no(tr("Start the %s export of %s to %s?", gfs.mode_name(mode), src, tparent), True):
        return
    try:
        status, paths, _ = _awake(cfg, "Export", perform_export, src, target, mode, cfg)
    except (ValueError, OSError) as e:
        ui.error(str(e))
        return
    ui.info("\n" + tr("Status: %s", shown(status)))
    ui.info(tr("Report: %s", [str(p) for p in paths if p.suffix == ".txt"][0]))


def restore_menu(cfg):
    ui.title(tr("Restore a complete copy from the second storage"))
    target = choose_locations(cfg, "export_targets", tr("Second storage"), False, "PhoneBackups-Export")[0]
    sets = [e.path for e in sorted(os.scandir(target), key=lambda e: e.name)
            if e.is_dir() and has_catalog(e.path)]
    if not sets:
        ui.error(tr("No exports found there."))
        return
    tparent = sets[ui.choose(tr("Which export set"), sets)]
    cat = Catalog(tparent)
    runs = cat.runs()
    cat.close()
    idx = ui.choose(tr("Restore the state of which export"),
                    [f"{r.folder}  [{shown(r.status)}]" for r in runs], default=len(runs))
    dest = ui.ask(tr("Restore into which (new or empty) folder"))
    if os.path.isdir(dest) and any(os.scandir(dest)):
        if not ui.ask_yes_no(tr("The folder is not empty - existing files with the same name will be "
                                "overwritten. Continue?"), False):
            return
    try:
        status, paths, _ = _awake(cfg, "Restore", perform_restore, tparent, runs[idx].id, dest, cfg)
    except (ValueError, OSError) as e:
        ui.error(str(e))
        return
    ui.info("\n" + tr("Status: %s", shown(status)))


# ---------------------------------------------------------------- settings / main

def settings_menu(cfg):
    while True:
        ui.title(tr("Settings"))
        ui.info("  " + tr("Settings file: %s", config.config_path()))
        idx = ui.choose(tr("Change"), [
            tr("Owner name ............ %s", cfg.get("owner") or "-"),
            tr("Folders on the phone .. %s", ", ".join(cfg.get("source_folders", []))),
            tr("Backup destinations ... %d saved (remove)", len(cfg.get("destinations", []))),
            tr("Export targets ........ %d saved (remove)", len(cfg.get("export_targets", []))),
            tr("ADB program ........... %s", cfg.get("adb_path") or tr("automatic")),
            tr("Wait for ADB phone .... %s s", cfg.get("adb_wait_seconds")),
            tr("Keep computer awake ... %s (during jobs)",
               tr("yes") if cfg.get("keep_awake", True) else tr("no")),
            tr("Back")], default=8)
        if idx == 0:
            cfg["owner"] = ui.ask(tr("Owner name"), cfg.get("owner") or None)
        elif idx == 1:
            txt = ui.ask(tr("Folders, separated by commas"), ", ".join(cfg.get("source_folders", [])))
            cfg["source_folders"] = [f.strip().strip("/") for f in txt.split(",") if f.strip()] or ["DCIM/Camera"]
        elif idx in (2, 3):
            key = "destinations" if idx == 2 else "export_targets"
            locs = cfg.get(key, [])
            if not locs:
                continue
            j = ui.choose(tr("Remove which (the files stay on the drive)"), locs + [tr("Cancel")],
                          default=len(locs) + 1)
            if j < len(locs):
                cfg[key] = locs[:j] + locs[j + 1:]
        elif idx == 4:
            cfg["adb_path"] = ui.ask(tr("Path to adb (empty = automatic)"), allow_empty=True)
        elif idx == 5:
            v = ui.ask(tr("Seconds"), str(cfg.get("adb_wait_seconds", 20)))
            if v.isdigit():
                cfg["adb_wait_seconds"] = int(v)
        elif idx == 6:
            cfg["keep_awake"] = ui.ask_yes_no(tr("Keep the computer from standby/shutdown while a job runs?"),
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
        print(tr("Usage: %s [backup|import|export|restore|settings]", "smartphone_media_backup.py"))
        return 0
    if argv and argv[0] in actions:
        actions[argv[0]](cfg)
        return 0
    while True:
        ui.title(f"{APP_NAME} {__version__}")
        idx = ui.choose(tr("Choose"), [tr("Backup phone -> external drive(s)"),
                                       tr("Import an old backup / any folder into a backup"),
                                       tr("Export a backup to a second storage (full / differential / incremental)"),
                                       tr("Restore from the second storage"),
                                       tr("Settings"),
                                       tr("Exit")], default=1)
        if idx == 5:
            return 0
        try:
            [backup_menu, import_menu, export_menu, restore_menu, settings_menu][idx](cfg)
        except KeyboardInterrupt:
            ui.warn("\n" + tr("Cancelled."))
