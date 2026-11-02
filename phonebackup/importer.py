"""Import an old backup (or any folder) into an existing backup.

Files are sorted into the same Year/MM.Month-photos|videos / raw structure, every file is
hashed at the source and after writing, identical files are stored only once (also against
everything already in the backup), and the source folder is only read - never changed.
"""

from pathlib import Path

from .backup import perform_backup
from .sources import IMPORT_EXCLUDES, FolderSource


def check_import(source_root, backup_parents):
    """Raise ValueError if the combination makes no sense."""
    src = Path(source_root).resolve()
    if not src.is_dir():
        raise ValueError(f"The folder to import does not exist:\n{src}")
    if not backup_parents:
        raise ValueError("Choose at least one copy of the backup to import into.")
    names = {Path(p).name for p in backup_parents}
    if len(names) != 1:
        raise ValueError("All chosen copies must belong to the same backup.")
    for p in backup_parents:
        p = Path(p).resolve()
        if src == p or p in src.parents:
            raise ValueError("The folder to import is inside the backup itself.")
        if src in p.parents:
            raise ValueError("The folder to import contains the backup itself - choose the old "
                             "backup folder only, not a folder above the backup.")


def perform_import(source_root, backup_parents, cfg, interactive=True, cancel=None):
    """Returns (status, report paths, file results, verdict) like perform_backup."""
    check_import(source_root, backup_parents)
    root = Path(source_root).resolve()
    parents = [Path(p) for p in backup_parents]
    src = FolderSource(root, kind="Folder import", device_name=root.name, description=str(root),
                       key_prefix=f"import:{root.as_posix()}/", verify_source=True,
                       exclude_dirs=IMPORT_EXCLUDES)
    return perform_backup(src, None, None, [""], [p.parent for p in parents], cfg,
                          interactive=interactive, cancel=cancel, parent_name=parents[0].name,
                          mode="import", source_label=root.name)
