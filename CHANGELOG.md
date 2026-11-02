# Changelog

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
