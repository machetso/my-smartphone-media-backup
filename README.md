# My Smartphone Media Backup

Verified, incremental backup of photos and videos from an Android phone to one or more
external drives, sorted by year and month, with a report after every run.
Python 3.8+, runs on Linux and Windows. The graphical interface needs PySide6; the terminal
version needs no extra packages.

## Download

Ready-to-run programs for Linux and Windows are on the
[Releases page](../../releases) - no Python installation needed.
Windows: download `My-Smartphone-Media-Backup-v….exe` and double-click it (or the `.zip` with
README and license); Linux: the `.tar.gz`.
See [CHANGELOG.md](CHANGELOG.md) for what is new.

**Updates:** at start the program looks whether a newer version is out (once a day; can be
switched off in Settings) and offers **Update now** or **Not now**. *Update now* downloads the new
version, checks that it is signed with the project's release key, swaps the program and restarts
it – settings, drives, phones and pairings stay. If the new version does not start, the old one is
put back automatically. (Started from the source code: update with `git pull` instead.)

**Making a release (maintainer):** push the tag → GitHub Actions builds the draft release →
`python3 tools/sign_release.py sign vX.Y.Z` on the maintainer's computer (adds the signed
`update-manifest.json`; the private key never goes to GitHub) → publish the release.

## Start from source

**Graphical interface** (needs PySide6):

```
./start-linux.sh                   # Linux (uses the project's .venv, PySide6 is already installed there)
start-windows.pyw                 # Windows: double-click (after: py -m pip install PySide6)
```

**Start screen:** **Your phones** – one entry per backup (e.g. *Sam's Pixel 10 Pro*,
*Kim's Galaxy A55*) with the date of its last backup and its own **Update backup** button,
enabled when exactly that phone and one of its drives are connected (same folders and drives,
only new photos and videos). Backups made before this list existed are found on the connected
drives. *Select all* / *Remove from list* hide phones (their backups stay on the drives). Below:
**New backup…** (another phone, or other folders / drives), **Backup settings…** and
**Manage backups…** (the tabs below).

**Backup settings** (subpage):

* **Phone connection** – the program **always uses the fastest connection it finds**; you do not
  choose one. The overview shows the speed of each way to connect, the one in use is marked, and
  the log says whether it is the fastest and what would be faster. If the phone turns up with USB
  debugging on the cable while it is connected over Wi-Fi, the program switches to the cable by
  itself. **Find the fastest connection** checks the cable, the Wi-Fi and Bluetooth and shows
  what is available.

  | Connection | Speed |
  |---|---|
  | USB cable + USB debugging (switched on by the phone app, or by hand) | 45–50 MB/s (USB 3), ~20–30 MB/s (USB 2) |
  | USB cable, normal file transfer (MTP – only on request) | 10–20 MB/s |
  | Wi-Fi: phone app or Wireless debugging | 10–40 MB/s, depends on the Wi-Fi |
  | Wi-Fi directly to this computer (no router) | 10–30 MB/s |

  *Switch on USB debugging (first time)…* is a step-by-step guide: it reads the model of the
  phone on the cable (works before USB debugging is on), has the steps for Pixel, Samsung,
  Xiaomi / Redmi / POCO, OnePlus / OPPO / realme, Motorola, Huawei / Honor, Sony and Nothing, and
  *Search the web for this phone* for any other. Android requires this once by hand – no program
  can switch USB debugging on before that.
  **Phone app switches it:** at the first USB-debugging connection the program offers to install
  the phone app *My Media Backup* and give it the right to switch USB debugging (Android's
  `WRITE_SECURE_SETTINGS`, granted over the cable – the app cannot get it by itself). From then
  on: open the app → **Allow backup over cable** → plug in. After every backup the computer
  switches USB debugging (or Wireless debugging) off again (*Switch … off after the backup*, on
  by default). Only USB debugging is switched off; the Developer options stay.

  **Rules for switching debugging off** (the phone app enforces them even if the computer is gone):
  1. Wi-Fi backups normally run through the phone app with debugging off; Wireless debugging
     only for phones without the app.
  2. One connection per backup: over the cable → Wireless debugging is switched off at the start;
     through the app over Wi-Fi → USB debugging is switched off at the start.
  3. The phone app never switches Wireless debugging on.
  4. 5 minutes after *Allow backup over cable* without a backup start → off (countdown on the phone).
  5. During a backup the computer says "still here" every 30 s; nothing for 2 minutes → off.
  6. Right after the backup the computer switches it off (and ends backup mode on the phone).

  **Recognising the phone securely:** at pairing the phone app creates a key in the phone's
  security chip; the computer stores its fingerprint. Model, serial number or names are never
  trusted – every connection checks that key (TLS with the pinned certificate) before the
  computer's secret is sent.
  * **Cable:** while the app runs, the computer reaches it through the cable (`adb forward`) and
    checks the key – the status then says *verified*. First time: the computer installs the app,
    opens it and asks to pair over the cable; you tap **Pair** on the phone (no code needed, the
    cable is the proof).
  * **Wi-Fi:** the app announces itself anonymously: a random name and a code that changes every
    10 minutes, which only a paired computer can recognise (HMAC of the pairing secret). Strangers
    in the same network cannot see which phone it is or follow it.
  * **Bluetooth (last resort, only to find the phone):** the same changing code plus the phone's
    Wi-Fi address (encrypted) in a Bluetooth LE signal. If the computer can reach that address it
    connects over Wi-Fi; otherwise it says so. **No files are ever sent over Bluetooth.**
    Needs the Python package `bleak` (in requirements.txt) and the phone's "Nearby devices"
    permission.
* **Folders on the phone** – **Camera** adds Android's standard camera folder `DCIM/Camera`;
  *Choose folders…* lists the phone's folders (screenshots `Pictures/Screenshots`, Samsung
  `DCIM/Screenshots`, WhatsApp `Android/media/com.whatsapp/WhatsApp/Media`, `Movies`, `Download`
  …) or lets you type one (*Select all* / *Select none*); *Remove*.
  **Keep the phone's folder structure** (option): files from folders other than the camera
  folder land in the same folders in the backup, e.g. `Pixel 10 Pro - Sam/Pictures/Screenshots/`;
  the camera folder is always sorted into year/month folders. Files already backed up stay
  where they are; identical files are still stored only once.
* **Backup destinations** – the list of destination drives; long folder names can be scrolled
  sideways (full name as a tooltip).

**Never the wrong phone.** Every backup folder remembers its phone in `.phonebackup/phone.json`
(model, the phone's serial number, the phone app's key id; for older backups the program reads
them from the reports). When you click *Start backup* the connected phone is identified live and
compared: a different serial number or key → **refused, nothing copied**. If only the model can be
compared, or the model does not match the backup's name, you have to confirm it. Right before the
first file the phone is identified a second time (a swapped phone stops the backup). A phone that
connects never replaces the smartphone name you set, and while a phone is on the USB cable no
other phone is taken over Wi-Fi. The confirmation shows the connection and, if it is not the
fastest, how to make it faster (cable + USB debugging; USB 3 cable instead of USB 2). Tick one or more. *Add drive…* lists the connected
  external drives, including drives that are attached but not mounted yet (Linux: they are
  mounted with one click, no password). *Add folder…* opens a folder picker. A ticked drive
  that is attached but not mounted is mounted automatically when the backup starts. A preview shows exactly where the
  files will go. The phone is detected automatically as soon as it is plugged in via ADB.
**Manage backups…** has four tabs:

* **Import old backup** – two ways:
  * *Add to an existing backup* – adds old backups or any folders (mixed photos, videos, RAW,
    nested folders, duplicates) to one of your backups, sorted into the same year/month folders.
  * *New backup of an old phone* – the old phone gets a backup of its own (“Galaxy S7 - Sam”):
    enter phone name and owner and tick the destination drive(s).

  Add one or more folders (e.g. the copy of the old phone and of its SD card) and click
  *Choose folders to import…*: every folder with files is listed with its photos / videos /
  other files; app data, caches, thumbnails, trash and hidden folders are left out. Tick the
  folders and choose for each one *Camera* (→ year/month folders) or *Other* (→ keeps its
  original folder under `Year/other/pictures | movies | other-files/`). For an old phone the
  camera folders and normal picture/movie/download folders are pre-ticked, messenger and
  screenshot folders are not. Every file is hashed at the source and verified after writing,
  identical files are stored only once (also against what is already in the backup), the old
  folders are only read. Skipped files are listed in the report “Import <name> <date>”.
* **Second storage (export)** – pick the backup, a second drive or **Google Drive** and the export
  type (*Automatic – Grandfather-Father-Son* by default). Earlier exports are listed; old ones can
  be cleaned up (only after you confirm). See *Second storage* below.
* **Restore** – pick the export set (on a drive or on Google Drive), the state and the target
  folder.
* **Settings** – adb path (normally empty = found automatically), waiting time, fsync, keep the
  computer awake. Hover over a setting for an explanation.

**Why ADB?** ADB (Android Debug Bridge, Google's USB tool for Android) is the fast and safe way:
about 45–50 MB/s over a USB 3 cable (measured with a Pixel 10 Pro), while MTP - the normal
"file transfer" mode - typically reaches 10–20 MB/s. With ADB every file is also checked with
SHA-256 on the phone itself. If ADB does not work the app falls back to MTP and says so.

**Keep the computer awake:** while a backup, import, export or restore runs, the computer is
kept from going to standby (on by default, switch off under *Settings*). The power settings
themselves are not changed – the block ends automatically with the job, even after a crash.
Linux: standby, idle suspend, closing the lid and a normal shutdown are blocked (logind
inhibitor), and the desktop's own idle timer is paused (D-Bus `org.freedesktop.ScreenSaver`
inhibit, like a video player does - needed on COSMIC and other desktops that suspend by
themselves after inactivity). While a job runs the screen therefore stays on.
Windows: sleep on inactivity is prevented and Windows asks before shutting down;
closing the lid and the power button still follow the Windows power settings.

**Desktop icon (Linux):** `./install-linux-desktop.sh` puts a start icon on the desktop and in
the app menu (run it again after moving the folder, `--remove` takes it away again).
The icons are built from `assets/PhoneBKP_Logo.webp` with `.venv/bin/python tools/make_icons.py`.

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
    │   ├── raw/01.January-raw/ …                  (only if RAW/DNG files exist)
    │   └── other/pictures|movies|other-files/<original folder>/   (only old phone imports)
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

**Easiest (Windows and Linux):** *Settings → Download ADB…* fetches Google's official
platform-tools directly from Google into the app's own folder (Windows:
`%LOCALAPPDATA%\phonebackup\platform-tools`, Linux: `~/.local/share/phonebackup/platform-tools`)
and sets the path - no installation, no admin rights. adb is not shipped with the app because
Google's licence does not allow passing it on.

**Windows (by hand)**

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

## Phone app (Wi-Fi, no USB debugging)

**Set up phone app…** shows a QR code. Scan it with the phone camera: the page (served by this
computer) offers **1. Download the app** (open the file, tap *Install*) and **2. Connect app**.
Phone and computer show the same 6-digit code - confirm it **on the phone and on the computer**
(the phone hands out its key only after your tap there). Done once. Pairing over the USB cable
works the same way: both screens show a code, tap *Pair* on the phone only if they match.

Over the cable the program can also install the app itself – it always **asks first** and
explains which phone, which version, why and exactly what happens; nothing is installed without
your click.

For a backup: open *My Media Backup* on the phone → **Start backup mode**. The computer finds it and
connects; after the backup the phone switches backup mode off itself (also after 5 minutes
unused). The app can only read photos and videos; the connection is encrypted (TLS, certificate
pinned while pairing). The computer **pulls** the files: it asks for every file, the phone only
answers the paired computer and never sends anything by itself. Same files and paths as over ADB, so existing backups simply continue.

## Backup over Wi-Fi (no cable)

Uses Android's built-in **Wireless debugging** (Android 11+, no app on the phone). Everything
works as over USB, including the SHA-256 check on the phone; it is only slower (depends on the
Wi-Fi, typically 10–40 MB/s).

1. Phone: *Settings → System → Developer options → Wireless debugging* → on (allow it for the
   network).
2. App: **Pair over Wi-Fi…** → on the phone tap *Pair device with QR code* and scan the code
   (or use *Pair device with pairing code* and type the 6 digits). Needed only once.
3. From then on the phone is found automatically whenever Wireless debugging is on and phone and
   computer are in the same Wi-Fi. If both USB and Wi-Fi are available, USB is used.

**No router? Direct Wi-Fi:** **Direct Wi-Fi…** lets the computer open its own Wi-Fi network
(Linux: NetworkManager hotspot, 5 GHz if possible; Windows: opens the *Mobile hotspot*
settings). The phone joins it (QR code for the camera), and the backup runs directly between
phone and computer. Most Wi-Fi adapters drop the normal Wi-Fi meanwhile; it returns when the
direct Wi-Fi is stopped (the app asks when you close it).

Real Wi-Fi Direct (P2P) would need a companion app on the phone; it is planned as a later step.

## Backup plan per drive

In the drive list of *New backup* each backup drive has a **Backup plan**:

* **Simple** – one folder that grows, only new photos and videos are added (as shown above).
* **Grandfather-Father-Son** – dated backups like on a second storage (see below): a **full**
  backup every 3 months, a **differential** one every month, **incremental** ones in between.
  A full/differential backup also contains the earlier files it needs (copied on the drive and
  verified), so photos deleted from the phone stay in every full backup.

Both can be mixed, e.g. *Simple* on one HDD and *Grandfather-Father-Son* on the other. A phone
folder keeps the plan it was started with.

## Second storage (export)

*Manage backups → Second storage* copies a backup to another drive or to Google Drive. Each export
gets its own folder:

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

**Automatic – Grandfather-Father-Son** (default) picks the type: full every 3 months
(grandfather), differential every month (father), incremental in between (son); the app shows
which one comes next and why. It keeps the newest 4 full, 3 differential and 6 incremental
exports plus everything they need for a restore; older ones are suggested for removal and deleted
**only after you confirm** (*Clean up old exports…*).

Every exported file is checked against the SHA-256 recorded at backup time. A file that was
damaged on the first drive (bit rot) is reported as a WARNING.
*Restore* rebuilds one complete folder from the shortest chain (full + newest differential +
incrementals after it) and verifies every file.

### Google Drive

*Add to cloud storage → Google Drive* signs in through the browser. The app may only see the
files it uploaded itself (Google's `drive.file` right); the sign-in stays on this computer.
Two export types:

* **Copy** – a mirror of the backup in *My Drive/My Smartphone Media Backup/Phone - Owner*:
  only new files are uploaded, nothing is deleted or overwritten.
* **Grandfather-Father-Son** in *Phone - Owner (Grandfather-Father-Son)*: every photo is stored
  only **once** – full and differential exports link to files already on Google Drive
  (shortcuts, no extra space; also to the Copy). Cleanup moves files that newer exports still
  use into them before deleting anything. Restore downloads the files and verifies them. Please
  do not delete single photos there by hand – every export that links to them would lose them.

Every upload is checked against Google's own SHA-256; free space is checked before the upload.
Privacy policy: <https://machetso.github.io/my-smartphone-media-backup/privacy.html>

Builds from source need the app's Google key: `python3 tools/set_google_key.py client_secret_….json`
(writes the git-ignored `phonebackup/_gkey.py`); release builds get it from GitHub secrets.

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
* Samsung Galaxy S20 FE over USB (ADB) and over Wi-Fi with the phone app 0.3.3:
  12.4 MB/s over Wi-Fi, no errors; phone app update over the cable with the install question.
* Google Drive: Copy and Grandfather-Father-Son with a 20 GB backup (1381 files, about
  4 MB/s upload), shortcuts, cleanup and restore verified.
* Not yet tested on real hardware: the MTP fallback (Linux gvfs, Windows Explorer) and Windows in general.

## License

MIT – see [LICENSE](LICENSE).
