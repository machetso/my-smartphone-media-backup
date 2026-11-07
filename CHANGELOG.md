# Changelog

## [0.9.8.2] - 2026-11-07

### Fixed
- **Windows: a USB hard disk was taken for a phone.** With a USB drive connected (e.g. a WD drive
  named "Backup Disk") the program warned that a phone was on the cable with USB debugging off.
  Windows lists drives as "portable devices" too; the program now only counts real USB devices
  as phones, never drive volumes, whatever their name.
- Linux: a drive of a phone maker (e.g. a Samsung portable SSD) is no longer taken for a phone.

## [0.9.8.1] - 2026-11-07

### Simpler "New backup" page (user request 2026-11-07)
- **Phone connection:** a simple view by default – the connection status and, when it helps, a
  tip below it. The speed overview, the connection buttons and *Switch … off after the backup*
  are behind the new tick box **Advanced connection settings** (remembered). The program still
  picks the fastest connection by itself.
- **USB tips:** for a phone's first backup the program suggests the USB cable with USB debugging.
  When USB debugging is off it says how much faster it would be (up to 50 MB/s instead of
  10–20 MB/s), with *How to switch on USB debugging…* (the step-by-step guide for the phone's
  brand) and *Continue without (slower file transfer)*.
- **Backup destinations:** only the drives used before with this phone (and owner), already
  ticked; a new phone starts with an empty list. *Add drive…* also offers the backup folders used
  before with other phones.
- **Start screen:** the button below *Your phones* now says *Remove ticked phones from list
  (backups are kept)*, so it is clear what the tick boxes are for.
- Manual updated in all languages.

## [0.9.8] - 2026-11-07

### Start screen menu (user request 2026-11-07)
- New **☰ Menu** at the top right of the start screen, there from the very first start:
  **Language** (all languages, the current one ticked), **Manual**, **Program settings…** and
  **About**. Before, the language could only be changed under *Manage backups… → Settings*.
- **Manual** opens this README in the program window, in the chosen language: the manual is now
  translated into all languages of the program (German, Spanish, French, Hebrew, Romanian,
  Klingon) and built into the program, no internet needed.

## [0.9.7] - 2026-11-07

### Security (open points of the 2026-11-06 review)
- **Wi-Fi pairing can no longer be intercepted.** Before, somebody in the same Wi-Fi could read
  the one-time token from the plain-HTTP link and fetch the pairing key from the phone before the
  computer did. Now commit-then-reveal: the link only carries a hash of the key, the phone adds
  its own random number, and the computer reveals the key only over the encrypted connection to
  that phone. A listener never sees the key, and a man in the middle gets different codes on the
  two screens. **Needs phone app 0.6.0** (older app/program versions say "please update").
- **Fake phone app detected:** when the phone is on the cable, the program checks who signed the
  installed phone app. If it is not the same as the app inside the program (e.g. a fake swapped in
  during the download over Wi-Fi), it is not used and a warning explains what to do.
- **ADB download checked:** the platform-tools file is now taken from Google's official SDK list
  (current stable version) and its size and SHA-1 must match before anything is unpacked.
- **Hotspot password no longer visible in the process list** (it was an nmcli argument; it now goes
  in through stdin).
- **Google Drive: one writer at a time.** Two computers/windows exporting or cleaning up the same
  Google Drive at once could overwrite each other's catalog. A "writing now" marker on Google Drive
  now makes the second one wait with a clear message (a left-over marker after a crash expires
  after 15 minutes).

### One-click update (user request 2026-11-07)
- At start the program looks on GitHub whether a newer version is out (at most once a day) and
  offers **Update now** or **Not now**. Nothing about the computer, the phone or the backups is
  sent; no internet or Direct Wi-Fi is simply ignored. Can be switched off in **Settings**
  ("Check for a new version at start").
- **Update now** (Windows .exe and Linux program): downloads the new version, checks it against a
  list signed with the project's release key (Ed25519; the key is not on GitHub, so even a
  taken-over GitHub account cannot push an update), refuses older versions, swaps the program and
  restarts. If the new version does not open its window within two minutes, the old one is put
  back and started again. Started from the source code: the message links to the download page.
- Works from 0.9.7 on: the first automatic update will be 0.9.7 → the next version.

### Direct Wi-Fi and Google Drive
- **No more "Network is unreachable (101)" during Direct Wi-Fi:** while the computer runs its own
  hotspot it has no internet, so the program no longer asks Google for the Drive free space. The
  Google Drive row shows "no internet right now (not needed for backups)" and checks again by itself.
- **Google Drive actions explain why they cannot work with Direct Wi-Fi on** (export, clean-up,
  restore, sign-in): the computer is not in the normal Wi-Fi, so there is no internet. The message
  shows the two steps (back up over Direct Wi-Fi, then switch it off and export) and offers to
  switch Direct Wi-Fi off right away.

### Faster / more reliable
- The read-back check after copying now really reads from the drive (Linux: the just-written data
  is dropped from RAM first).
- Databases (backup index, export catalog, re-sorting) commit at most once per second instead of
  after every file – much less waiting on USB hard disks. Nothing is lost on close.

## [0.9.6] - 2026-11-06

### Languages (user request 2026-11-06)
- **7 languages – the same as VideoSpeedControl:** English, Deutsch, Español, Français, Română,
  עברית (Hebrew, right-to-left) and tlhIngan Hol (Klingon). **Settings → Language** ("System
  language" = the computer's language if available); the program offers to restart.
- **Everything is translated:** windows, buttons, messages, the log, the terminal version, the
  setup page shown on the phone, the sign-in page, and the **reports** (TXT/HTML/CSV).
  Folder and file names on the drives stay the same in every language (e.g. `01.January-photos`),
  so a backup made in one language continues in any other.
- **Phone app "My Media Backup" 0.5.0** in the same languages: follows the phone's language,
  or choose it in the app (Language). Updated over the cable after the install question.
- Long translated texts wrap instead of widening the window.

### Improvements
- Windows: each release also offers the program file (`My-Smartphone-Media-Backup-v….exe`) on its
  own, not only inside the .zip (added to 0.9.5 by hand).

## [0.9.5] - 2026-11-06

Security update after a full code review – **please update** (the phone app is updated to 0.4.0
over the cable; the program asks first). Existing backups, settings and pairings stay valid.

### Improvements
- **Connection status clearly visible** on the start screen and in the backup settings: a coloured
  banner with a big headline – e.g. "● Connected: Google Pixel 10 Pro · USB cable · verified",
  "▲ Action needed", "○ No phone connected" – and the details below as before.
- Settings are copied once a day (last 7 days) to `~/.config/phonebackup/backups`.

### Security (review 2026-11-06)
- **Pairing must now also be confirmed on the phone** (phone app 0.4.0). Before, any app on the
  phone or a tapped web link could pair itself with the phone app and read the photos and
  videos; the code was only checked on the computer. Pairing links are only accepted for
  computers in the local network.
- **Pairing over the cable shows a code on both screens**, made from a random value of the
  computer and the phone's key – another app on the phone cannot put itself in between. A
  waiting request is never replaced by another one.
- Phone app: only answers devices in the local network (not mobile data / the internet); limited
  number of connections and request size; only a paired computer keeps backup mode on; USB
  debugging that the app switched on is always switched off at the end of a backup; taps through
  another app's overlay are ignored; the cable link can no longer be opened from web pages.
- Restore (drive and Google Drive) refuses catalog entries that point outside the restore folder;
  cleanup only deletes real export folders; a catalog downloaded from Google Drive is checked and
  folder names from Google Drive cannot point outside the app's data folder.
- Wi-Fi debugging: only phones this computer connected on purpose are connected automatically.
- The setup page only listens on the address of the QR code, drops slow connections, refuses bad
  requests and keeps the first pairing request.
- Settings and the Google sign-in are saved readable only by you; the Google sign-in window cannot
  be blocked by another program.
- CSV reports: file names that would run as spreadsheet formulas are neutralised.
- A crafted photo can no longer hang the app (EXIF scan).
- Export never overwrites a file in a new export folder (names that differ only in case) and an
  error with one file no longer leaves the export unfinished without a report.
- Release build: write rights only for the release step; GitHub actions pinned to fixed versions.

### Tested
- Pixel 10 Pro: phone app update 0.3.x → 0.4.0 over the cable (install question), a forged pairing
  link and a key request through the phone's loopback were refused, cable backup without errors.
- 114 automatic tests, 16 of them for the security fixes; the tests now run in a sandbox and can
  no longer touch the real settings.

## [0.9.4] - 2026-11-05

The biggest update so far: a simple start screen, a phone app for backups without cables and
without permanent USB debugging, Grandfather-Father-Son backups, and Google Drive.

### New name
- The app is now called **My Smartphone Media Backup** (before: an earlier working title,
  briefly *Fast Smartphone Media Backup*); the phone app is called **My Media Backup**. Program
  files: `My-Smartphone-Media-Backup.exe` (Windows), `my-smartphone-media-backup` (Linux).
  Existing backups, settings and phone pairings keep working unchanged.

### Simpler to use
- **Start screen "Your phones"**: one entry per backed-up phone with its size and its own
  **Update backup** button (same phone, folders and drives – only new files). Older backups on the
  connected drives are found automatically. Select several or *Select all*, *Remove from list*.
- **New backup…** opens the backup settings; **gear button** = backup settings; everything else
  (import, export, restore, settings) is under **Manage backups…**.
- Backup settings in two columns: phone, folders (**Camera** button for `DCIM/Camera`, *Choose
  folders…* with *Select all / Select none*, *Remove*), backup drives. The folder list is kept per
  backup, folders that the connected phone does not have are left out. Option **keep the phone's
  folder structure** for folders other than the camera.
- **The fastest connection is chosen automatically** (cable with USB debugging › phone app over
  Wi-Fi › Wireless debugging › MTP): an overview shows the speed of each connection type and which
  one is in use; the app switches to the cable as soon as it is available; **Find the fastest
  connection** checks cable, Wi-Fi and Bluetooth; the log says what would make it faster.
- **Beginner's guide "Switch on USB debugging (first time)"**: recognises the phone model on the
  cable even without debugging, step-by-step texts for the common brands, web search for others.
- **Sizes everywhere**: size of each backup (files and GB) on the start screen, the Export tab and
  the Import tab.
- **Better progress**: percentage, files done and **to go**, current speed, time left and the
  file(s) being copied right now – also for exports and Google Drive uploads.
- **Summary at the end** of every job (backup, import, export, upload, restore): time, amount and
  **average speed**; every report shows the average speed. The report is the log file
  (**Open log file**); if a job stops with an error, its log is saved as a text file as well.
- **Works in a small window** (e.g. half the screen): the window can be made much smaller; the
  pages scroll while the start buttons (*Start backup / import / export / restore*) always stay
  visible; *New backup* puts its two columns below each other when they do not fit; the progress
  (percentage, files to go, amount, speed, time left, files now) is always shown in full on three
  lines and is never squeezed – the log gives way first.
- Settings: ADB in one line (*Ready – version …* or *Not installed* + **Download ADB…**), with an
  ⓘ explanation; if ADB is missing, the app offers the download once at start.
- Export tab: the backup is chosen by name like on the Import tab, with **Refresh** (mounts the
  drives) and **Read from copy** when the backup is on several drives.

### Phone app "My Media Backup" (Android, new – version 0.3.3)
- Backups **over Wi-Fi without USB debugging**: the app may only *read* photos and videos. The
  connection is encrypted (TLS) and tied to the phone's own key, which the computer remembers at
  pairing; a secret per paired computer; every file is checked with SHA-256 on the phone.
- Set up with **Set up phone app…**: QR code → download page served by the computer → both show a
  6-digit code → confirm. Or pair over the cable with one tap.
- **USB debugging only for the backup** (*Allow backup over cable*): the app switches USB
  debugging on, the computer switches it off again after every backup. Safety switch-off by the
  app: 5 minutes without a backup start, 2 minutes without a sign of life from the computer, end
  of the backup, after a reboot – also if the app is updated or closed by Android meanwhile.
  Wireless debugging is never switched on by the app; only one connection per backup.
- **Backup mode** on the phone ends after the backup or after 5 minutes unused (with countdown);
  the phone shows "<computer> is copying …".
- Anonymous recognition: on Wi-Fi the phone announces itself with a random name and a token that
  changes every 10 minutes (no model, no ID); Bluetooth LE is only used to *find* the phone, never
  for files.
- **Nothing is installed on a phone without asking**: before the phone app is installed, updated
  or given its right over the cable, a dialog shows which phone (model and serial number), which
  app and version, why, exactly what happens (install the bundled file – nothing downloaded –,
  grant the right, open the app), what the app can and cannot do and how to remove it. *Not now*
  is the default; the backup then works with USB debugging switched on by hand. Every install is
  also written to the log.

### Wi-Fi without the phone app
- **Pair over Wi-Fi…** with Android's *Wireless debugging* (QR code or 6-digit code); paired
  phones are connected automatically afterwards. Cable is preferred when both are there.
- **Direct Wi-Fi…**: the computer opens its own hotspot (Linux; on Windows the hotspot settings
  open) with a QR code for the phone – backups without a router.

### Safety
- **Never the wrong phone**: each backup folder remembers its phone (serial number, phone-app key,
  model; older backups from their reports). Checked at *Start* and again right before the first
  file – a different phone is refused. No Wi-Fi phone is used while a phone is on the cable.
- **Read-only guard**: every command sent to the phone must match a short fixed list of read-only
  commands with paths inside the phone's storage; the only exceptions (switching debugging off,
  installing the bundled phone app) are a fixed list too.

### Backup plans: Simple or Grandfather-Father-Son
- **Per backup drive** you choose the plan in the drive list: *Simple* (one folder that grows, as
  before) or *Grandfather-Father-Son* – mixable, e.g. simple on one HDD and GFS on the other.
- **Grandfather-Father-Son**: dated **full** backups every 3 months (grandfather),
  **differential** every month (father), **incremental** in between (son). A full/differential
  also contains the earlier files it needs (copied on the drive, verified), so photos deleted from
  the phone stay in every full. No empty incremental when nothing is new. The app shows which type
  comes next and why.
- **Cleanup**: GFS keeps the newest 4 full, 3 differential and 6 incremental backups plus
  everything they need for a restore. Older ones are suggested for removal and deleted **only after
  you confirm** (also via **Clean up old exports…**).
- An existing backup folder keeps its plan (nothing is converted); for both plans on one drive use
  two folders.

### Second storage (export)
- New export type **Automatic – Grandfather-Father-Son** (default) besides Full / Differential /
  Incremental by hand; restores use the shortest chain (full + newest differential + incrementals
  after it).
- **Google Drive** (button **Add to cloud storage**, more services later), signing in through the
  browser. The app may only see the files it uploaded itself (`drive.file`); the sign-in is stored
  only on this computer. Two ways, chosen in *Export type*:
  - **Copy** – a mirror of the backup in *My Drive/My Smartphone Media Backup/Phone - Owner*: only
    new files are uploaded (3 at the same time), nothing is deleted or overwritten.
  - **Grandfather-Father-Son** in *Phone - Owner (Grandfather-Father-Son)*: **every photo is
    stored only once** – full and differential exports link to files already on Google Drive
    (shortcuts: no extra space, done in seconds), also to the Copy, so switching from Copy to GFS
    uploads nothing again. Cleanup moves files that newer exports still use into them before
    deleting anything. **Restore from Google Drive** on the Restore tab.
  - Every upload is checked against Google's own SHA-256; free space is checked before; the report
    stays on the computer and is also uploaded to Google Drive.
- The computer is kept awake during uploads, exports, restores and cleanups too.
- Privacy policy: <https://machetso.github.io/my-smartphone-media-backup/privacy.html>

### Faster
- Cable (ADB) backups with many small files much faster: up to 64 files per request instead of
  one request per file.
- Wi-Fi backups through the phone app: the computer fetches up to 3 files ahead (measured with
  many small files: 4.1 → 11.4 MB/s, the limit of the Wi-Fi link).

### Fixes
- Wi-Fi pairing found nothing on Linux: Avahi is asked as well.
- A phone on the cable with USB debugging switched off (e.g. after the last backup) was reported as
  "No phone connected yet". Now the app says which phone is on the cable and what to tap.
- Google Drive: a second app window (or computer) reading the export list could break a running
  Grandfather-Father-Son export at its end ("attempt to write a readonly database"). Every run now
  uses its own copy of the catalog; files of an export that stopped before it was recorded are
  reused by the next export (moved after the SHA-256 check) instead of being uploaded again.
- The folder list was shared by all phones (a Pixel's folders were offered for a Samsung): now per
  backup, and folders the connected phone does not have are removed before the start.
- The phone app's switch-off countdown was lost when the app was updated while USB debugging was
  on.

### Tested
- Samsung Galaxy S20 FE over Wi-Fi with the phone app 0.3.3: 12.4 MB/s, no errors; phone app
  update over the cable with the new install question.
- Google Drive: 20 GB backup (1381 files) uploaded and verified; Grandfather-Father-Son with
  shortcuts, cleanup and restore verified on the real Google Drive.

### Notes
- New dependencies: `segno` (QR codes), `bleak` (Bluetooth LE). No Google library is needed.
- The phone app is shipped inside the program (`assets/companion/MediaBackup.apk`) and installed
  over the cable on request.

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
