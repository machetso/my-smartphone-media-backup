# Changelog

## [Unreleased]

### Features
- **Always the fastest connection, chosen automatically** (no manual choice): overview with the
  speeds and the connection in use, log line "fastest / not the fastest + what to do", automatic
  switch from Wi-Fi / MTP to the cable when USB debugging appears, button **Find the fastest
  connection** (cable, Wi-Fi, Bluetooth). Destination list scrolls sideways for long names.
- **Never back up the wrong phone** (`phoneid.py`): each backup folder remembers its phone (serial
  number, phone-app key id, model; older backups from their reports); checked when Start is
  clicked and again right before the first file - a different phone is refused. The name field is
  never replaced by another phone; no Wi-Fi phone while a phone is on the cable. The start
  confirmation shows the connection and how to make it faster if it is not the fastest.
- New name: **Fast Smartphone Media Backup** (phone app: *Fast Media Backup*).
- Simple start screen: **Your phones**, one entry per backup with its own **Update backup**
  (same phone, folders and drives, only new files; enabled when that phone and a drive are
  connected; older backups found on the drives; select all / remove from list), **New backup…**,
  **Backup settings…**, **Import, export, restore…**. Folder lists per backup.
- Backup settings as a subpage: phone connection with a speed overview of all connection types
  (USB debugging via the phone app preselected), **Camera** button (`DCIM/Camera`) next to
  *Choose folders…* and *Remove*.
- USB debugging only for the backup: the phone app (installed and granted
  `WRITE_SECURE_SETTINGS` over the cable once) switches USB debugging on (*Allow backup over
  cable*); the computer switches USB / Wireless debugging off after every backup. The only
  non-read-only commands are a fixed list in `phoneguard.CONTROL`.
- Debugging switch-off rules, enforced by the phone app (0.3.0): 5 min without a backup start →
  off; "still here" every 30 s, nothing for 2 min → off; one connection per backup (the other
  debugging is switched off at the start); backup mode ends → off; the app never switches
  Wireless debugging on.
- Secure recognition by the phone's Keystore key: over the cable via `adb forward` (status
  "verified"), pairing over the cable confirmed on the phone; anonymous Wi-Fi announcement
  (random name, HMAC token changing every 10 min, no model / id); Bluetooth LE only to find the
  phone (same token + encrypted address), never for files. New dependency: `bleak`.
- Backup settings in two columns (everything visible without scrolling); *Select all* /
  *Select none* in the folder chooser; option **keep the phone's folder structure** for folders
  other than the camera folder (`layout.keep_structure_placement`).
- Beginner's guide *Switch on USB debugging (first time)…*: detects the phone model on the USB
  cable without debugging, steps for the common brands, web search for any other phone.
- Backup over Wi-Fi with Android's Wireless debugging (ADB over Wi-Fi, no phone app): *Pair over
  Wi-Fi…* (QR code or 6-digit code), paired phones are then found and connected automatically
  (mDNS + last address); USB is preferred when both are available. Same SHA-256 check on the
  phone as over USB; report shows "ADB over Wi-Fi".
- *Direct Wi-Fi…*: the computer opens its own hotspot (Linux via NetworkManager, 5 GHz first;
  Windows opens the Mobile hotspot settings) with a QR code for the phone - backups without a
  router. The app offers to stop it on exit.
- New dependency: `segno` (QR codes, pure Python).
- Read-only guard (`phoneguard.py`): every command the app sends to the phone must match one of
  a few fixed read-only templates (getprop, test -d, find/stat, sha256sum, cat) with all paths
  inside /sdcard; anything else is refused before it reaches adb.

- Phone app "Media Backup" (android/, Kotlin): backups over Wi-Fi WITHOUT USB debugging. The app
  may only read photos and videos (MediaStore); TLS with the phone's Keystore certificate pinned
  by the computer + a secret per paired computer; SHA-256 on the phone; same paths as ADB, so
  existing backups continue. "Set up phone app…" shows a QR code → page served by the computer
  (download APK, "Connect app") → both show a 6-digit code → confirm. Backup mode on the phone
  switches off after the backup (or after 30 min unused). Android 17: asks for local-network access.
  Built with tools/build_companion.sh (1.6 MB, shipped in assets/companion/).

### Fixes
- Wi-Fi backups through the phone app much faster with many small files (measured 4.1 → 11.4 MB/s,
  the limit of the Wi-Fi link): the computer fetches up to 3 files ahead (max. 128 MB in memory,
  checked against the phone's SHA-256 as before); the phone app (0.3.1) no longer rebuilds its
  photo list every 20 s during a backup. An older phone app is updated automatically over the cable.
- Wi-Fi pairing hung on Linux: adb's own mDNS found nothing, now Avahi is asked as well.

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
