# Changelog

## [0.9.3] - 2026-11-02

### Features
- *Settings → Download ADB…*: downloads Google's official platform-tools (adb) directly from
  Google into the app's data folder and sets the path (Windows, Linux, macOS); the download is
  checked (zip, safe paths, adb starts) before it replaces an older one.
- Settings show which adb is used; mouse-over explanation of ADB and its speed advantage over
  MTP (about 45–50 MB/s vs. typically 10–20 MB/s).

## [0.9.2] - 2026-11-02

### Fixes
- Linux: "Keep the computer awake" did not stop the automatic standby on COSMIC (and other
  desktops whose idle timer suspends via `systemctl suspend`, which logind allows despite the
  user's own block inhibitor). The desktop idle timer is now paused as well via the D-Bus
  ScreenSaver / PowerManagement inhibit; the screen stays on while a job runs.

### Features
- Import an old phone as a backup of its own ("Import old backup" tab → *New backup of an old
  phone*): enter the old phone's name and owner, add one or more folders (e.g. the copy of the
  internal storage and of the SD card) and tick which folders to import. Every folder with
  files is listed with its photo/video/other counts; app data (`Android/data`, `Android/obb`),
  caches, thumbnails, trash and hidden folders are left out, system/temporary files
  (`Thumbs.db`, `*.tmp`, …) are skipped and listed. Camera folders are pre-ticked and
  sorted into the year/month and raw folders like a phone backup - recognised by DCIM / Camera /
  100ANDRO… or, for self-sorted old backups (e.g. `jpgs/August 2023`, `RAW bis 8.5.23`), by
  camera file names (`PXL_…`, `IMG_2017…`, `20170520_120000`, `DSC…`, …); other folders keep
  their original folder name under
  `Year/other/pictures | movies | other-files/`. Messenger and screenshot folders are listed
  but not pre-ticked. Each folder can be switched between *Camera* and *Other*.
- Import into an existing backup also accepts several folders and the same folder selection;
  other files can optionally be imported there too.

## [0.9.1] - 2026-11-02

### Features
- Keeps the computer from going to standby or shutting down while a job runs (Linux and
  Windows), without changing the power settings; can be switched off in the settings.
- App icon (window, taskbar, Windows program file) and a Linux desktop/app-menu launcher
  (`install-linux-desktop.sh`).

## [0.9.0] - 2026-11-02

First public test version.

### Features
- Backup of photos and videos from Android phones to one or more external drives at the
  same time, sorted into `Year/MM.Month-photos`, `MM.Month-videos` and `raw/MM.Month-raw`.
  Folders are only created when files go into them.
- Capture date from photo/video metadata, then from the filename, then from the file date.
- SHA-256 check of every file: on the phone (ADB) and on every drive (written copy read back).
- Incremental: only new files are copied; nothing is ever deleted; same name with different
  content is saved as `name_1.jpg`; identical files are stored only once.
- Report after every backup as TXT, HTML and CSV in the backup folder.
- Fast ADB connection (about 50 MB/s over USB 3) with MTP fallback and a clear warning.
- Export to a second storage as full, differential or incremental runs, plus restore.
- Import of old backups or any folder into an existing backup ("Import old backup" tab):
  mixed folders are sorted into the same year/month structure, every source file is hashed
  separately and every copy is verified, identical files are stored only once (also against
  what is already backed up), thumbnail/recycle-bin folders are ignored, non-media files are
  skipped and listed, and the old folder is never changed. Running the same import again
  copies nothing.
- Older formats recognised: TIFF, BMP, AVI, MTS/M2TS, MPG, WMV, FLV, VOB and many RAW formats.
- Graphical interface (drives and folders chosen with pickers; attached but unmounted
  drives are mounted with one click on Linux) and a terminal version.

### Downloads
- **Linux** (`linux-x86_64.tar.gz`): unpack and start the program.
  Needs `adb` (`sudo apt install adb`).
- **Windows** (`windows-x64.zip`): unpack and start the program (`.exe`).
  Put Google's `platform-tools` folder next to the `.exe` for ADB. Windows may warn about
  an unknown publisher because the program is not signed: "More info" -> "Run anyway".

### Known limitations
- The Windows version and the MTP fallback have not been tested on real hardware yet.
