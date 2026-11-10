# My Smartphone Media Backup

HablI' Android mIlloghmey HaStamey je pa' De' jengva' wa' pagh law'Daq polghach nIDlu'bogh, chu'
neH. DIS jar je lanlu'. Hoch Qu' rIn QIn ghaj.
Python 3.8+, Linux Windows je Dung Qap. HaSta interface PySide6 poQ; terminal
Segh ghun latlh poQbe'.

## Suq

Linux Windows je vaD ghunmey ghuHpu'bogh
[Releases page](../../releases) Daq tu'lu' - Python jombe'lu'.
Windows: `My-Smartphone-Media-Backup-v….exe` yISuq 'ej cha'logh yIHot (pagh `.zip` README
chaw' je ghajbogh); Linux: `.tar.gz`.
chu'mey: [CHANGELOG.md](CHANGELOG.md) yIlegh.

**chu'moH:** taghDI' ghun Segh chu' law' tu'lu''a' nej (jaj Hoch wa'logh; ghuHmeyDaq
Qempa'laH) 'ej **DaH yIchu'moH** pagh **DaH be'** nob. *DaH yIchu'moH* Segh chu' Suq,
ghunmoHwI' ngoq Dung ponglu''a' nID, ghun choH 'ej taghqa'
– ghuHmey, De' jengva'mey, HablI'mey rapmoHghachmey je ratlh. Segh chu' taghbe'chugh, Segh ngo'
ghaH ta' cheghmoHlu'. (Hal ngoq vo' taghlu'pu'chugh: `git pull` yIlo'.)

**ghun chu' nobmeH (ghunmoHwI'):** tag yIngeH → GitHub Actions ghun chu' nab chenmoH →
ghunmoHwI' De'wI'Daq `python3 tools/sign_release.py sign vX.Y.Z` (ponglu'bogh
`update-manifest.json` chel; ngoq pegh GitHubDaq ngeHlu'be' reH) → ghun chu' yInob.

## Hal ngoq vo' yItagh

**HaSta interface** (PySide6 poQ):

```
./start-linux.sh                   # Linux (uses the project's .venv, PySide6 is already installed there)
start-windows.pyw                 # Windows: double-click (after: py -m pip install PySide6)
```

**tagh 'agh:** **HablI'mey** – polghach Hoch wa' tetlh Doch (rur *Sam's Pixel 10 Pro*,
*Kim's Galaxy A55*) polghach Qav jaj 'ej **polghach yIchu'qa'** Hot Daj ghaj;
HablI' vam 'ej De' jengva' Daj wa' rarlu'DI' neH Qap ('aplo'mey De' jengva'mey je rap,
mIlloghmey HaStamey chu' neH). tetlh vam ghajbe'DI' polghachmey chenmoHlu'pu'bogh rarlu'bogh
De' jengva'meyDaq tu'lu'. *Hoch yIwIv* / *tetlhvo' yIteq* HablI'mey So' (polghachmeychaj De' jengva'meyDaq ratlh). bIng:
**polghach chu'…** (latlh HablI', pagh latlh 'aplo'mey / De' jengva'mey), **polghach ghuHmey…** 'ej
**polghachmey yIlo'…** (bIngDaq tabmey).

**☰ DIr** (tagh HaSta' nIHDaq Dung, wa'DIch taghDaq): **Hol**, **ghojmeH paq** (ghItlhvam, Hol wIvlu'pu'bogh), **ghunmeH mIw…** **De'** je.

**polghach ghuHmey** (ghItlh bIng):

* **HablI' rarghach** – ghun **rarghach nomqu' tu'bogh lo' reH**; rarghach DawIvbe'.
  Hoch rarmeH mIw Do 'agh, lo'lu'bogh tu'lu', 'ej ghItlh tetlh nomqu''a' 'ej nuq nom law' 'e' ja'.
  Wi-Fi Dung rarlu'taHvIS HablI' tlheghDaq USB debugging chu'lu'bogh tu'lu'chugh, ghun tlhegh
  lo' ghaH ta'. **rarghach nomqu' yInej** tlhegh, Wi-Fi, Bluetooth je nID 'ej nuq tu'lu' 'agh.

  **nab ngeD:** rarghach Dotlh neH, 'ej QaHchugh bIngDaq qeS. HablI' polghach ghajbe'bogh: USB
  tlhegh USB debugging je qeS (wa'DIch polghach Hoch mIllogh HaSta je ghItlh). tlheghDaq HablI'
  USB debugging Hutlhbogh, pagh Wi-Fi / De' noH Dung rarlu'bogh: USB debugging nom law' 'e' qeS
  ja' – *USB QaghHa'moHwI' chu'meH mIw…* mIw tetlh poSmoH (bIng yIlegh), *Hutlh yItaH (De' noH
  QIt)* HablI' De' noH motlh lo'. **rar SeHlaw Dun** yIwIv: Do 'agh, Hoch rarghach leQmey, *…
  polghach pItlhDI' yIchu'Ha'* je.

  | rarghach | Do |
  |---|---|
  | USB tlhegh + USB debugging (HablI' ghun chu', pagh ghop chu'lu') | 45–50 MB/s (USB 3), ~20–30 MB/s (USB 2) |
  | USB tlhegh, ghItlh vIH motlh (MTP – tlhoblu'DI' neH) | 10–20 MB/s |
  | Wi-Fi: HablI' ghun pagh Wireless debugging | 10–40 MB/s, Wi-Fi Dotlh lo' |
  | Wi-Fi De'wI'vamDaq (router ghajbe') | 10–30 MB/s |

  *USB debugging yIchu' (wa'DIch)…* Hoch Hergh ghItlh: tlheghDaq HablI' Segh laD
  (USB debugging chu'be'taHvIS Qap), Pixel, Samsung,
  Xiaomi / Redmi / POCO, OnePlus / OPPO / realme, Motorola, Huawei / Honor, Sony, Nothing je Hergh ghaj, 'ej
  latlh HablI'vaD *HablI' vam vaD web yInej*. Android wa'logh ghop poQ – pa' ghun pagh
  USB debugging chu'laH.
  **HablI' ghun chu':** USB debugging rarghach wa'DIchDaq ghun
  HablI' ghun *My Media Backup* jom 'ej USB debugging choHmeH chaw' nob 'e' tlhob (Android
  `WRITE_SECURE_SETTINGS`, tlhegh Dung nob – ghun Hutlh 'oH SuqlaHbe'). vaj
  reH: ghun yIpoSmoH → **Allow backup over cable** → yIrar. Hoch polghach rIn De'wI'
  USB debugging (pagh Wireless debugging) Qempa'qa' (*polghach rIn 'e' HablI'Daq … yIQempa'*,
  motlh chu'). USB debugging neH Qempa'lu'; Developer options ratlh.

  **debugging Qempa'meH chutmey** (De'wI' tu'lu'be'chugh je HablI' ghun chutmey pab):
  1. Wi-Fi polghachmey motlh HablI' ghun lo' debugging Qempa'lu'taHvIS; Wireless debugging
     HablI'mey ghun ghajbe'bogh vaD neH.
  2. polghach Hoch wa' rarghach: tlhegh Dung → tagh DI' Wireless debugging Qempa'lu';
     ghun Wi-Fi Dung → tagh DI' USB debugging Qempa'lu'.
  3. HablI' ghun Wireless debugging chu'be' reH.
  4. *Allow backup over cable* 5 rep ret polghach tagh'be'chugh → Qempa' (HablI'Daq poH togh).
  5. polghach poHvIS 30 lup Hoch De'wI' "naDev jIHtaH" ja'; 2 rep pagh → Qempa'.
  6. polghach rInDI' De'wI' Qempa' SIbI' (HablI'Daq polmeH Dotlh rInmoH je).

  **HablI' QaD ngu'ghach:** rapmoHDI' HablI' ghun HablI' QaD chipDaq ngoq chenmoH;
  De'wI' ngoq ghIH pol. Segh, mI', pongmey je voqlu'be' reH
  – Hoch rarghach ngoq nID (TLS, certificate ngaQ) De'wI' pegh
  ngeHlu'pa'.
  * **tlhegh:** ghun Qu'taHvIS, De'wI' tlhegh Dung ghoS (`adb forward`) 'ej
    ngoq nID – vaj Dotlh *nIDlu'* 'agh. wa'DIch: De'wI' ghun jom,
    poSmoH 'ej tlhegh Dung rapmoH 'e' tlhob; HablI'Daq **yIrapmoH** DaHot (ngoq poQbe',
    tlhegh 'oH tob).
  * **Wi-Fi:** ghun pong Sovbe'lu'bogh Dung ja': pong Sumbe' 'ej ngoq Hoch
    10 rep choHbogh, De'wI' rapmoHlu'bogh neH ngu'laH (rapmoH pegh HMAC). nuvpu' Sovbe'lu'bogh
    Dup rapDaq nuq HablI' 'oH 'e' leghlaHbe', tlha'laHbe' je.
  * **Bluetooth (Qav mIw, HablI' nejmeH neH):** ngoq choHbogh rap 'ej HablI'
    Wi-Fi Daq (So'lu'bogh) Bluetooth LE QIn Dung. De'wI' Daq vam ghoSlaHchugh
    Wi-Fi Dung rar; ghoSlaHbe'chugh, ja'. **Bluetooth Dung ghItlh ngeHlu'be' reH.**
    Python ghun `bleak` (requirements.txtDaq) 'ej HablI' "Nearby devices"
    chaw' poQ.
* **HablI'Daq 'aplo'mey** – **Camera** Android camera 'aplo' motlh `DCIM/Camera` chel;
  *'aplo'mey yIwIv…* HablI' 'aplo'mey tetlh 'agh (screenshots `Pictures/Screenshots`, Samsung
  `DCIM/Screenshots`, WhatsApp `Android/media/com.whatsapp/WhatsApp/Media`, `Movies`, `Download`
  …) pagh wa' DaghItlhlaH (*Hoch yIwIv* / *pagh yIwIv*); *yIteq*.
  **HablI' 'aplo' tlhegh pol** (DuH): camera 'aplo' latlh 'aplo'mey vo' ghItlhmey
  polghachDaq 'aplo'mey rapDaq ratlh, rur `Pixel 10 Pro - Sam/Pictures/Screenshots/`;
  camera 'aplo' DIS/jar 'aplo'meyDaq lanlu' reH. ghItlhmey polta'pu'bogh
  Daqchajvo' vIHbe'; ghItlh rap wa'logh neH pollu'.
* **polghach Daqmey** – Daq De' jengva'mey tetlh; 'aplo' pongmey tIq
  poS nIH je vIHlaH (pong naQ tooltip 'oH).
  wa' pagh law' yIwIv. *De' jengva' yIchel…* rarlu'bogh pa' De' jengva'mey tetlh 'agh, De'
  jengva'mey rarlu'bogh 'ach chu'lu'be'bogh je (Linux: wa' Hot Dung chu'lu', mu'ngoq poQbe').
  *'aplo' yIchel…* 'aplo' wIvwI' poSmoH. De' jengva' wIvlu'bogh rarlu'bogh 'ach chu'lu'be'bogh
  polghach taghDI' ghaH ta' chu'lu'. nuqDaq ghItlhmey jaH 'e' lughbe'qu' 'agh. ADB Dung HablI'
  rarlu'DI' SIbI' ghaH ta' tu'lu'. HablI'vam (ghaH ghajwI' je) lo'pu'bogh De' jengva'mey neH 'agh
  tetlh, wIvlu'pu'; HablI' polghach ghajbe'bogh tetlh chIm tagh. *De' jengva' yIchel…* latlh
  HablI'mey lo'pu'bogh polghach 'aplo'mey je nob.

**HablI' Qagh pagh reH.** Hoch polghach 'aplo' HablI' Daj qaw `.phonebackup/phone.json`Daq
(Segh, HablI' mI', HablI' ghun ngoq ID; polghachmey ngo'vaD ghun QInmey vo'
laD). *polghach yItagh* DaHotDI' HablI' rarlu'bogh DaH ngu'lu' 'ej
rap nIDlu': mI' pagh ngoq latlh → **lajQo'lu', ghItlhqa'lu'be'**. Segh neH rap nIDlaHchugh,
pagh Segh polghach pong rapbe'chugh, DaHarqang. ghItlh wa'DIch
ret HablI' cha'logh ngu'lu' (HablI' choHlu'chugh polghach mev). HablI'
rarbogh HablI' pong DaghuHmoHbogh choHbe' reH, 'ej HablI' USB tlheghDaq taHvIS latlh
HablI' Wi-Fi Dung tlhaplu'be'. Harqang 'agh rarghach 'ej, nomqu'be'chugh,
nom law'moHmeH mIw (tlhegh + USB debugging; USB 2 tlhegh Daq USB 3 tlhegh).

**polghachmey yIlo'…** loS tabmey ghaj:

* **polghach ngo' yIlIH** – cha' mIw:
  * *polghach ghajbogh yIchel* – polghachmey ngo' pagh 'aplo'mey Hoch (mIlloghmey, HaStamey, RAW,
    'aplo'mey qoDbogh, ghItlh rap) polghachlIj wa'Daq chel, DIS/jar 'aplo'mey rapDaq lanlu'.
  * *HablI' ngo' polghach chu'* – HablI' ngo' polghach Daj Suq (“Galaxy S7 - Sam”):
    HablI' pong ghajwI' pong je yIghItlh 'ej Daq De' jengva'(mey) yIwIv.

  'aplo' wa' pagh law' yIchel (rur HablI' ngo' chIl 'ej SD card Daj chIl) 'ej
  *lIHmeH 'aplo'mey yIwIv…* yIHot: ghItlh ghajbogh Hoch 'aplo' tetlhDaq 'agh, mIlloghmey / HaStamey /
  latlh ghItlhmey je; ghun De', cache, mIllogh mach, veQ, 'aplo'mey So'lu'bogh je Qoylu'. 'aplo'mey
  yIwIv 'ej Hoch vaD *Camera* (→ DIS/jar 'aplo'mey) pagh *latlh* (→ 'aplo' ngo' Daj
  `Year/other/pictures | movies | other-files/` bIngDaq pol) yIwIv. HablI' ngo'vaD
  camera 'aplo'mey 'ej mIllogh/qon/Suq 'aplo'mey motlh wIvlu'pu', QIn QumwI' 'aplo'mey
  screenshot 'aplo'mey je wIvlu'be'. Hoch ghItlh Hal Daq hash chenmoHlu' 'ej ghItlhDI' nIDlu',
  ghItlh rap wa'logh neH pollu' (polghachDaq ghItlh ghajbogh rap nIDlu' je), 'aplo'mey
  ngo' laDlu' neH. ghItlhmey Qoylu'bogh QIn “Import <name> <date>”Daq tetlhlu'.
* **latlh Daq (lel)** – polghach, cha'DIch De' jengva' pagh **Google Drive**, lel
  Segh je yIwIv (motlh *Automatic – vav'a'-vav-puqloD*). lel ngo' tetlhlu'; ngo'mey
  teqlaH (DaHarqangDI' neH). bIngDaq *latlh Daq* yIlegh.
* **cheghmoH** – lel ghom (De' jengva'Daq pagh Google DriveDaq), Dotlh, Daq 'aplo' je
  yIwIv.
* **ghuHmey** – adb He (motlh chIm = ghaH ta' tu'lu'), loSmeH poH, fsync,
  De'wI' yIQotlh. QIjmeH ghuH Dung yIvIH.

**qatlh ADB?** ADB (Android Debug Bridge, Android vaD Google USB jan) mIw nom 'ej QaD 'oH:
USB 3 tlhegh Dung 45–50 MB/s (Pixel 10 Pro Dung juvlu'), MTP - ghItlh vIH
motlh - motlh 10–20 MB/s neH. ADB Dung Hoch ghItlh
HablI'Daq SHA-256 nIDlu' je. ADB Qapbe'chugh ghun MTP lo' 'ej ja'.

**De'wI' yIQotlh:** polghach, lIH, lel pagh cheghmoH Qu'taHvIS, De'wI'
standby 'elbe' (motlh chu'; *ghuHmey*Daq Qempa'laH). HoS ghuHmey
choHlu'be' – Qu' rInDI' Qotlhghach rIn ghaH ta', ghun Qaw'lu'DI' je.
Linux: standby, idle suspend, yoD SoQmoH, Qempa' motlh je Qotlhlu' (logind
inhibitor), 'ej desktop idle poH tlhap mevlu' (D-Bus `org.freedesktop.ScreenSaver`
inhibit, HaSta ghun rur - COSMIC desktop latlh je vaD poQlu', Qu' pagh poH nI' ret
Qongbogh). vaj Qu'taHvIS 'agh chu'taH.
Windows: Qu' pagh poH Qong Qotlhlu' 'ej Qempa'pa' Windows tlhob;
yoD SoQmoH, HoS Hot je Windows HoS ghuHmey tlha'.

**desktop mIllogh (Linux):** `./install-linux-desktop.sh` desktopDaq ghun naQ Daq je
tagh mIllogh lan ('aplo' DavIHDI' yIta'qa', `--remove` teqqa').
mIlloghmey `assets/PhoneBKP_Logo.webp` vo' `.venv/bin/python tools/make_icons.py` Dung chenmoHlu'.

bIngDaq ta' ghIH, Do, poH ratlhbogh, ghItlh tetlh je, *yImev* (ghItlh DaH rInDI'
mev), *QIn yIpoSmoH*, *polghach 'aplo' yIpoSmoH* je.

**terminal Segh** (ghun latlh poQbe'): `python3 smartphone_media_backup.py --cli`
pagh SIbI' `smartphone_media_backup.py backup | export | restore | settings`.
PySide6 tu'lu'be'chugh, `smartphone_media_backup.py` terminal Segh tagh ghaH ta'.

## De' jengva'Daq ghotvam

```
PhoneBackups/
└── Pixel 10 Pro - Sam/                  ← backup parent folder (one per phone + owner)
    ├── Backup Pixel 10 Pro Sam 2026-11-02.txt / .html / .csv   ← report
    ├── 2026/
    │   ├── 26.01/  …  26.12/                    (photos + videos of each month)
    │   ├── raw/26.01/ …  raw/26.12/             (only if RAW/DNG files exist)
    │   └── other/pictures|movies|other-files/<original folder>/   (only old phone imports)
    └── .phonebackup/index.sqlite                 ← what is already backed up (do not delete)
```

* jar qawHaq pong = DIS + jar: `26.02` 'oH jar cha' DIS 2026. qawHaq ngo' (`02.February-photos` /
  `02.February-videos`) moj – wa'DIch qawHaq ngo' 'ang ghun, qawHaq **pong ngo' ratlhbogh**
  DangaQHa'moH (not choH). Hoch Daq, Google Drive Daq je; ghItlh lalDan vIHmoH neH, Qaw'be'.
* ghItlh 'elDI' neH DIS jar je 'aplo'mey chenmoHlu' - 'aplo' chIm pagh.
* jar = mIllogh/HaSta metadata mIllogh jaj → pagh ghItlh pong
  (`PXL_20261102_…`) → pagh ghItlh jaj.
* Motion photos (`*.MP.jpg`), HEIC, PNG, … mIlloghmey 'oH; DNG RAW ghItlhmey latlh je `raw/`Daq jaH.
* jaj rapDaq cha'DIch QIn pongDaq rep chellu'.
* pagh teqlu' reH: HablI'Daq pagh, polghachDaq pagh.
* pong rap 'ach ngaS latlh → ghItlh chu' `name_1.jpg` pollu'. ngaS rap
  wa'logh neH pollu'.

## QaD

* **HablI' → De'wI':** ADB Dung HablI' SHA-256 Hutlh 'ar 'ej De' Hevlu'bogh rap
  nIDlu'. MTP Dung Qaplaw'be', 'ej QIn ja'.
* **De'wI' → De' jengva':** Hoch ghItlhqa' jengva'Daq ghItlhlu', laDqa'lu' 'ej SHA-256 nIDlu'.
* ghItlhmey poH ghItlh ghItlhlu' 'ej nIDDI' neH pongchoHlu'. polghach ghorlu'bogh
  ghItlh bID lonbe' reH; Qu' veb tlha' neH.
* cha' (pagh law') De' jengva'mey **rapDaq poH** ghItlhlu'. HablI' wa'logh neH laDlu'.
* wa'DIch Daq chIm nIDlu'. De' jengva' Qapbe'chugh pagh tlhapqu'chugh, latlh De' jengva'Daq
  polghach tlha' 'ej QIn Doq 'agh.

## ADB ghuHmoH (wa'logh). vaj HablI' ~2 lup lo'laH, MTP loSbe'lu'

**HablI'Daq**

1. Settings → About phone → *Build number* 7× yIHot (developer mode chu').
2. Settings → System → Developer options → **USB debugging** yIchu'.
3. HablI' yIrar, yIpoSmoH 'ej *Allow USB debugging* yIHarqang
   **Always allow from this computer** Dung.

**Linux (Pop!_OS / Ubuntu)**

```
sudo apt install adb
adb devices          # should show your phone as "device"
```

**ngeDqu' (Windows Linux je):** *ghuHmey → ADB yISuq…* Google ADB 'oHbogh
platform-tools Google vo' ghun 'aplo' Daj SIbI' Suq (Windows:
`%LOCALAPPDATA%\phonebackup\platform-tools`, Linux: `~/.local/share/phonebackup/platform-tools`)
'ej He ghuHmoH - jombe'lu', admin chaw' poQbe'. ghun adb ngeHbe' qatlh
Google chaw' ngeHmeH chaw'be'.

**Windows (ghop)**

1. *SDK Platform-Tools for Windows* yISuq
   https://developer.android.com/tools/releases/platform-tools vo'
2. yIpoSmoH 'ej `platform-tools` 'aplo' **`smartphone_media_backup.py` retlhDaq** lan (ghaH ta' tu'lu'),
   pagh *ghuHmey*Daq `adb.exe` He yIghItlh.
3. Google Pixel: HablI' tu'lu'be'chugh, *Google USB Driver* yIjom.

ADB Qapbe'chugh, ghun yIqIm 'agh 'ej **MTP lanwI'** lo':

* Linux: HablI' gvfs/`gio` Dung ghaH ta' chu'lu'. HablI' USB QInDaq *File transfer*
  yIwIv.
* Windows: wa'logh `py -m pip install pywin32` poQ. vaj Explorer ghItlhmey ghItlhqa'.
  QIt 'oH, 'ej ghun chenmoHlu'taHvIS jan teHDaq juvlu'be' (bIngDaq yIlegh).

## HablI' ghun (Wi-Fi, USB debugging ghajbe')

**HablI' ghun yIghuHmoH…** QR ngoq 'agh. HablI' camera Dung yIlaD: ghItlh (De'wI' vam
nob) **1. ghun yISuq** (ghItlh yIpoSmoH, *Install* yIHot) **2. ghun De'wI' rap yIrar** je nob.
HablI' De'wI' je 6 mI' ngoq rap 'agh - **HablI'Daq 'ej De'wI'Daq** yIHarqang
(DaHotDI' neH HablI' ngoq Daj nob). wa'logh neH. USB tlhegh Dung rapmoHghach
rap Qap: 'agh cha' ngoq 'agh, rapchugh neH HablI'Daq *yIrapmoH* yIHot.

tlhegh Dung ghun Hutlh ghun jomlaH je – reH **wa'DIch tlhob** 'ej
nuq HablI', nuq Segh, qatlh, nuq qaS je QIj; DaHotbe'chugh pagh
jomlu'.

polghachvaD: HablI'Daq *My Media Backup* yIpoSmoH → **polmeH Dotlh yIchu'**. De'wI' tu' 'ej
rar; polghach rInDI' HablI' polmeH Dotlh Qempa' Hutlh (5 rep
lo'be'lu'DI' je). ghun mIlloghmey HaStamey je laDlaH neH; rarghach So'lu' (TLS, certificate
rapmoHDI' ngaQ). De'wI' ghItlhmey **luqeq**: Hoch ghItlh tlhob, HablI'
De'wI' rapmoHlu'bogh neH jang 'ej Hutlh pagh ngeH reH. ADB Dung rur ghItlhmey Hemey je rap, vaj polghachmey ghajbogh tlha' neH.

## Wi-Fi polghach (tlhegh ghajbe')

Android **Wireless debugging** lo' (Android 11+, HablI'Daq ghun poQbe'). Hoch
USB rur Qap, HablI'Daq SHA-256 nID je; QIt law' neH (Wi-Fi
Dotlh lo', motlh 10–40 MB/s).

1. HablI': *Settings → System → Developer options → Wireless debugging* → chu' (Dup vaD
   yIchaw').
2. ghun: **Wi-Fi Dung yIrapmoH…** → HablI'Daq *Pair device with QR code* yIHot 'ej ngoq yIlaD
   (pagh *Pair device with pairing code* yIlo' 'ej 6 mI' yIghItlh). wa'logh neH poQlu'.
3. vaj Wireless debugging chu'lu'DI' 'ej HablI' De'wI' je Wi-Fi rapDaq taHDI'
   HablI' ghaH ta' tu'lu' reH. USB Wi-Fi je tu'lu'chugh, USB lo'lu'.

**router ghajbe''a'? Wi-Fi De'wI'vamDaq:** **Wi-Fi De'wI'vamDaq…** De'wI' Wi-Fi Dup Daj poSmoHmoH
(Linux: NetworkManager hotspot, laHchugh 5 GHz; Windows: *Mobile hotspot*
ghuHmey poSmoH). HablI' muv (camera vaD QR ngoq), 'ej HablI' De'wI' je joj SIbI'
polghach Qap. Wi-Fi adapter law' Wi-Fi motlh chagh poHvam; Wi-Fi De'wI'vamDaq
mevlu'DI' cheghqa' (DaSoQmoHDI' ghun tlhob).

Wi-Fi Direct (P2P) teH HablI'Daq ghun latlh poQ; tugh Hergh 'oH.

## De' jengva' Hoch polghach mIw

*polghach chu'* De' jengva' tetlhDaq Hoch polghach De' jengva' **polghach mIw** ghaj:

* **Simple** – wa' 'aplo' tIn, mIlloghmey HaStamey chu' neH chellu' (Dung 'aghlu'bogh rur).
* **vav'a'-vav-puqloD** – polghachmey jaj ghajbogh latlh Daq rur (bIngDaq yIlegh): Hoch wej jar
  **full** polghach, Hoch jar **differential** polghach, joj **incremental** polghachmey.
  full/differential polghach ghItlh ngo' poQbogh ghaj je (De' jengva'Daq ghItlhqa'lu' 'ej
  nIDlu'), vaj mIlloghmey HablI'vo' teqlu'bogh Hoch full polghachDaq ratlh.

cha' DuH lIngchoHlaH, rur HDD wa'Daq *Simple* 'ej latlhDaq *vav'a'-vav-puqloD*. HablI'
'aplo' mIw taghlu'pu'bogh pol.

## latlh Daq (lel)

*polghachmey yIlo' → latlh Daq* polghach latlh De' jengva'Daq pagh Google DriveDaq ghItlhqa'. Hoch lel
'aplo' Daj Suq:

```
PhoneBackups-Export/Pixel 10 Pro - Sam/
├── 2026-11-02_14-30-00_full/
├── 2026-11-20_09-12-45_incremental/
├── 2026-12-01_18-03-10_differential/
└── .phonebackup-export/catalog.sqlite
```

| Segh          | ghItlhqa'                                          |
|---------------|----------------------------------------------------|
| full          | Hoch                                               |
| differential  | **full** lel Qav vo' Hoch chu'                     |
| incremental   | lel **Qav** vo' Hoch chu' (Hoch Segh)              |

**Automatic – vav'a'-vav-puqloD** (motlh) Segh wIv: Hoch wej jar full
(vav'a'), Hoch jar differential (vav), joj incremental (puqloD); ghun 'agh
nuq veb 'ej qatlh. full lel chu'qu' 4, differential 3, incremental 6 je
pol, cheghmoHmeH poQbogh Hoch je; ngo'mey teqmeH chup 'ej
**DaHarqangDI' neH** teqlu' (*lel ngo' yIpoSmoH…*).

Hoch ghItlh lellu'bogh pollu'DI' SHA-256 qonlu'bogh rap nIDlu'. ghItlh
wa'DIch De' jengva'Daq QIHlu'pu'bogh (bit rot) yIqIm ja'.
*cheghmoH* mIr ngaqqu' vo' 'aplo' naQ wa' chenmoHqa' (full + differential chu'qu' +
incrementals ret) 'ej Hoch ghItlh nID.

### Google Drive

*cloud Daq yIchel → Google Drive* browser Dung 'el. ghun ghItlhmey
Hutlh ngeHbogh neH leghlaH (Google `drive.file` chaw'); 'elghach De'wI' vamDaq ratlh.
cha' lel Segh:

* **Chaq** – *My Drive/My Smartphone Media Backup/Phone - Owner*Daq polghach qIl:
  ghItlh chu' neH ngeHlu', pagh teqlu'be' lajlu'be' je.
* **vav'a'-vav-puqloD** *Phone - Owner (Grandfather-Father-Son)*Daq: Hoch mIllogh
  **wa'logh** neH pollu' – full differential je lel Google DriveDaq ghItlhmey ghajbogh rar
  (shortcuts, Daq latlh poQbe'; Chaq je). teqDI' ghItlhmey lel chu' law' lo'taHbogh
  lelDaq vIHlu' wa'DIch, vaj pagh teqlu'. cheghmoH ghItlhmey Suq 'ej nID. pa'
  mIllogh wa' ghop yIteqQo' – lel Hoch rarbogh Hutlh.

Hoch ngeH Google SHA-256 Daj rap nIDlu'; ngeHpa' Daq chIm nIDlu'.
pegh chut: <https://machetso.github.io/my-smartphone-media-backup/privacy.html>

Hal ngoq vo' chenmoHmeH ghun Google ngoq poQlu': `python3 tools/set_google_key.py client_secret_….json`
(git-ignored `phonebackup/_gkey.py` ghItlh); ghun chu' GitHub secrets vo' Suq.

## ghuHmey

`~/.config/phonebackup/config.json`Daq pollu' (Windows: `%APPDATA%\PhoneBackup\config.json`):
ghajwI' pong, HablI' 'aplo'mey (motlh `DCIM/Camera`, ghunDaq latlh wIvlaH),
De' jengva'mey, adb He.

## nIDmey

```
python3 -m unittest discover tests
```

## juvlu'

* Linux (Pop!_OS) Google Pixel 10 Pro (Android 17) je, USB 3 Dung ADB:
  1372 ghItlh / 20 GB pa' HDD cha'Daq rapDaq poH pollu' 'ej nIDlu', ~24 MB/s.
* Samsung Galaxy S20 FE USB (ADB) Dung 'ej Wi-Fi Dung HablI' ghun 0.3.3 je:
  Wi-Fi Dung 12.4 MB/s, Qagh pagh; tlhegh Dung HablI' ghun chu'moH jom tlhob je.
* Google Drive: Chaq vav'a'-vav-puqloD je 20 GB polghach (1381 ghItlh, ~
  4 MB/s ngeH), shortcuts, teq, cheghmoH je nIDlu'.
* jan teHDaq juvlu'be' wej: MTP lanwI' (Linux gvfs, Windows Explorer) 'ej Windows Hoch.

## chaw'

MIT – [LICENSE](LICENSE) yIlegh.
