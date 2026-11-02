# My Smartphone Media Backup

Verified, incremental backup of photos and videos from an Android phone to one or more
external drives, sorted by year and month, with a report after every run.
Python 3.8+, runs on Linux and Windows. The graphical interface needs PySide6; the terminal
version needs no extra packages.

## Download

Ready-to-run programs for Linux and Windows are on the
[Releases page](../../releases) - no Python installation needed.
See [CHANGELOG.md](CHANGELOG.md) for what is new.

## Start from source

**Graphical interface** (needs PySide6):

```
./start-linux.sh                   # Linux (uses the project's .venv, PySide6 is already installed there)
start-windows.pyw                 # Windows: double-click (after: py -m pip install PySide6)
```

The window has four tabs:

* **Backup** – owner, phone name (filled in automatically), phone folders (*Choose folders…*),
  and the list of destination drives. Tick one or more. *Add drive…* lists the connected
  external drives, including drives that are attached but not mounted yet (Linux: they are
  mounted with one click, no password). *Add folder…* opens a folder picker. A ticked drive
  that is attached but not mounted is mounted automatically when the backup starts. A preview shows exactly where the
  files will go. The phone is detected automatically as soon as it is plugged in via ADB.
* **Import old backup** – adds an old backup or any folder (mixed photos, videos, RAW, nested
  folders, duplicates) to an existing backup: sorted into the same year/month folders, every file
  hashed at the source and verified after writing, identical files stored only once (also against
  what is already in the backup), the old folder is only read. Non-media files are skipped and
  listed in the report "Import <folder name> <date>".
* **Second storage (export)** – pick the backup, the target drive and full / differential /
  incremental. Earlier exports are listed.
* **Restore** – pick the export set, the state and the target folder.
* **Settings** – adb path, waiting time, fsync.

The progress bar, speed, remaining time and the log are at the bottom, with *Cancel* (stops
after the current file), *Open report* and *Open backup folder*.

**Terminal version** (no extra packages): `python3 smartphone_media_backup.py --cli`
or directly `smartphone_media_backup.py backup | export | restore | settings`.
If PySide6 is missing, `smartphone_media_backup.py` starts the terminal version automatically.

## Result on the drive

```
PhoneBackups/
└── Pixel 10 Pro - Sam/                  ← backup parent folder (one per phone + owner)
    ├── Backup Pixel 10 Pro Sam 2026-11-02.txt / .html / .csv   ← report
    ├── 2026/
    │   ├── 01.January-photos/  …  12.December-photos/
    │   ├── 01.January-videos/  …  12.December-videos/
    │   └── raw/01.January-raw/ …                  (only if RAW/DNG files exist)
    └── .phonebackup/index.sqlite                 ← what is already backed up (do not delete)
```

* Year and month folders are only created when a file goes into them - no empty folders.
* Month = capture date from the photo/video metadata → otherwise the filename
  (`PXL_20261102_…`) → otherwise the file date.
* Motion photos (`*.MP.jpg`), HEIC, PNG, … count as photos; DNG and other RAW files go to `raw/`.
* A second report on the same day gets the time added to its name.
* Nothing is ever deleted: not on the phone, not in the backup.
* Same name but different content → the new file is saved as `name_1.jpg`. Identical content
  is stored only once.

## Safety

* **Phone → computer:** with ADB, the phone calculates the SHA-256 itself and it is compared
  with the received data. With MTP this is not possible, and the report says so.
* **Computer → drive:** each copy is forced onto the disk, read back and its SHA-256 compared.
* Files are written as temporary files and only renamed after the check. An interrupted backup
  never leaves half files; the next run simply continues.
* Two (or more) drives are written **at the same time**. The phone is read only once.
* Free space is checked first. If a drive fails or fills up, the backup continues on the
  other drive and the report shows it in red.

## ADB setup (once). This makes the phone usable in ~2 seconds instead of waiting for MTP

**On the phone**

1. Settings → About phone → tap *Build number* 7× (developer mode on).
2. Settings → System → Developer options → switch on **USB debugging**.
3. Connect the phone, unlock it and confirm *Allow USB debugging* with
   **Always allow from this computer**.

**Linux (Pop!_OS / Ubuntu)**

```
sudo apt install adb
adb devices          # should show your phone as "device"
```

**Windows**

1. Download *SDK Platform-Tools for Windows* from
   https://developer.android.com/tools/releases/platform-tools
2. Unzip it so that the folder `platform-tools` is **next to `smartphone_media_backup.py`** (found automatically),
   or enter the path to `adb.exe` under *Settings*.
3. Google Pixel: if the phone isn't found, install the *Google USB Driver*.

If ADB doesn't work, the program shows a clear warning and switches to the **MTP fallback**:

* Linux: the phone is mounted automatically via gvfs/`gio`. Choose *File transfer* in the
  phone's USB notification.
* Windows: needs `py -m pip install pywin32` once. Explorer then copies the files.
  This is slow, and it was not tested on real hardware during development (see below).

## Second storage (export)

Menu item 2 copies a backup parent folder to another drive. Each run gets its own folder:

```
PhoneBackups-Export/Pixel 10 Pro - Sam/
├── 2026-11-02_14-30-00_full/
├── 2026-11-20_09-12-45_incremental/
├── 2026-12-01_18-03-10_differential/
└── .phonebackup-export/catalog.sqlite
```

| Type          | Copies                                             |
|---------------|----------------------------------------------------|
| full          | everything                                         |
| differential  | everything new since the last **full** export      |
| incremental   | everything new since the **last** export (any type) |

Every exported file is checked against the SHA-256 recorded at backup time. A file that was
damaged on the first drive (bit rot) is reported as a WARNING.
Menu item 3 (*Restore*) rebuilds one complete folder from full + later exports and verifies it.

## Settings

Saved in `~/.config/phonebackup/config.json` (Windows: `%APPDATA%\PhoneBackup\config.json`):
owner name, phone folders (default `DCIM/Camera`, more can be selected in the program),
drives, adb path.

## Tests

```
python3 -m unittest discover tests
```

## Tested

* Linux (Pop!_OS) with a Google Pixel 10 Pro (Android 17) via ADB over USB 3:
  1372 files / 20 GB backed up to two external HDDs at the same time and verified, about 24 MB/s.
* Not yet tested on real hardware: the MTP fallback (Linux gvfs, Windows Explorer) and Windows in general.

## License

MIT – see [LICENSE](LICENSE).
