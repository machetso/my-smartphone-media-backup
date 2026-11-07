# My Smartphone Media Backup

Backup verificat și incremental al fotografiilor și videoclipurilor de pe un telefon Android pe una sau mai multe
unități externe, sortate pe ani și luni, cu un raport după fiecare rulare.
Python 3.8+, rulează pe Linux și Windows. Interfața grafică are nevoie de PySide6; versiunea
pentru terminal nu are nevoie de pachete suplimentare.

## Descărcare

Programele gata de rulat pentru Linux și Windows se află pe
[pagina Releases](../../releases) - nu este nevoie de instalarea Python.
Windows: descarcă `My-Smartphone-Media-Backup-v….exe` și fă dublu clic pe el (sau `.zip` cu
README și licență); Linux: `.tar.gz`.
Vezi [CHANGELOG.md](CHANGELOG.md) pentru noutăți.

**Actualizări:** la pornire, programul verifică dacă a apărut o versiune mai nouă (o dată pe zi; se poate
dezactiva în Setări) și oferă **Actualizează acum** sau **Nu acum**. *Actualizează acum* descarcă noua
versiune, verifică dacă este semnată cu cheia de release a proiectului, înlocuiește programul și îl repornește
– setările, unitățile, telefoanele și asocierile rămân. Dacă noua versiune nu pornește, cea veche este
pusă înapoi automat. (Dacă pornești din codul sursă: actualizează în schimb cu `git pull`.)

**Publicarea unui release (maintainer):** fă push la tag → GitHub Actions construiește release-ul ca draft →
`python3 tools/sign_release.py sign vX.Y.Z` pe computerul maintainer-ului (adaugă fișierul semnat
`update-manifest.json`; cheia privată nu ajunge niciodată pe GitHub) → publică release-ul.

## Pornire din codul sursă

**Interfața grafică** (are nevoie de PySide6):

```
./start-linux.sh                   # Linux (uses the project's .venv, PySide6 is already installed there)
start-windows.pyw                 # Windows: double-click (after: py -m pip install PySide6)
```

**Ecranul de start:** **Telefoanele tale** – câte o intrare pentru fiecare backup (ex. *Sam's Pixel 10 Pro*,
*Kim's Galaxy A55*) cu data ultimului backup și propriul buton **Actualizează backup-ul**,
activ atunci când exact acel telefon și una dintre unitățile lui sunt conectate (aceleași foldere și unități,
doar fotografii și videoclipuri noi). Backup-urile făcute înainte să existe această listă sunt găsite pe unitățile
conectate. *Selectează tot* / *Elimină din listă* ascund telefoanele (backup-urile lor rămân pe unități). Dedesubt:
**Backup nou…** (alt telefon sau alte foldere / unități), **Setări backup…** și
**Gestionează backup-urile…** (filele de mai jos).

**☰ Meniu** (în dreapta sus pe ecranul de start, chiar de la prima pornire): **Limbă**, **Manual** (acest text, în limba aleasă), **Setările programului…** și **Despre**.

**Setări backup** (subpagină):

* **Conexiunea telefonului** – programul **folosește întotdeauna cea mai rapidă conexiune pe care o găsește**; nu
  trebuie să alegi tu una. Prezentarea generală arată viteza fiecărui mod de conectare, cel folosit este marcat, iar
  jurnalul spune dacă este cel mai rapid și ce ar fi mai rapid. Dacă telefonul apare cu depanarea
  USB pe cablu în timp ce este conectat prin Wi-Fi, programul trece singur pe cablu.
  **Găsește cea mai rapidă conexiune** verifică cablul, Wi-Fi-ul și Bluetooth-ul și arată
  ce este disponibil.

  **Vizualizare simplă:** doar starea conexiunii și, când ajută, un sfat dedesubt. Un telefon fără
  backup încă: sfatul recomandă cablul USB cu depanarea USB (primul backup copiază toate
  fotografiile și videoclipurile). Un telefon pe cablu fără depanare USB sau conectat prin Wi-Fi /
  transfer de fișiere: sfatul spune cât de mult mai rapidă este depanarea USB – *Cum activați
  depanarea USB…* deschide ghidul pas cu pas (vezi mai jos), *Continuă fără (transfer de fișiere
  mai lent)* folosește transferul normal de fișiere al telefonului. Bifează **Setări avansate de
  conexiune** ca să vezi prezentarea vitezelor, toate butoanele de conectare și *Oprește … după
  backup*.

  | Conexiune | Viteză |
  |---|---|
  | Cablu USB + depanare USB (pornită de aplicația de pe telefon sau manual) | 45–50 MB/s (USB 3), ~20–30 MB/s (USB 2) |
  | Cablu USB, transfer de fișiere normal (MTP – doar la cerere) | 10–20 MB/s |
  | Wi-Fi: aplicația de pe telefon sau Depanare wireless | 10–40 MB/s, depinde de Wi-Fi |
  | Wi-Fi direct către acest computer (fără router) | 10–30 MB/s |

  *Activează depanarea USB (prima dată)…* este un ghid pas cu pas: citește modelul
  telefonului de pe cablu (funcționează înainte ca depanarea USB să fie pornită), conține pașii pentru Pixel, Samsung,
  Xiaomi / Redmi / POCO, OnePlus / OPPO / realme, Motorola, Huawei / Honor, Sony și Nothing, iar
  *Caută pe web pentru acest telefon* pentru oricare altul. Android cere acest lucru o singură dată manual – niciun program
  nu poate porni depanarea USB înainte de asta.
  **Aplicația de pe telefon o pornește:** la prima conexiune cu depanare USB, programul se oferă să instaleze
  aplicația de pe telefon *My Media Backup* și să îi dea dreptul de a comuta depanarea USB (permisiunea Android
  `WRITE_SECURE_SETTINGS`, acordată prin cablu – aplicația nu o poate obține singură). De atunci
  înainte: deschide aplicația → **Permite backup prin cablu** → conectează cablul. După fiecare backup, computerul
  oprește din nou depanarea USB (sau Depanarea wireless) (*Oprește depanarea USB / Depanarea wireless pe telefon după backup*, activat
  implicit). Se oprește doar depanarea USB; Opțiunile pentru dezvoltatori rămân.

  **Reguli pentru oprirea depanării** (aplicația de pe telefon le aplică chiar dacă computerul nu mai este acolo):
  1. Backup-urile prin Wi-Fi rulează în mod normal prin aplicația de pe telefon, cu depanarea oprită; Depanarea wireless
     doar pentru telefoanele fără aplicație.
  2. O singură conexiune per backup: prin cablu → Depanarea wireless este oprită la început;
     prin aplicație, prin Wi-Fi → depanarea USB este oprită la început.
  3. Aplicația de pe telefon nu pornește niciodată Depanarea wireless.
  4. La 5 minute după *Permite backup prin cablu* fără ca un backup să pornească → oprită (numărătoare inversă pe telefon).
  5. În timpul unui backup, computerul spune „încă sunt aici” la fiecare 30 s; nimic timp de 2 minute → oprită.
  6. Imediat după backup, computerul o oprește (și încheie modul backup pe telefon).

  **Recunoașterea sigură a telefonului:** la asociere, aplicația de pe telefon creează o cheie în cipul de
  securitate al telefonului; computerul îi stochează amprenta. Modelul, numărul de serie sau numele nu sunt niciodată
  considerate de încredere – fiecare conexiune verifică acea cheie (TLS cu certificatul fixat) înainte ca
  secretul computerului să fie trimis.
  * **Cablu:** cât timp aplicația rulează, computerul o accesează prin cablu (`adb forward`) și
    verifică cheia – starea arată atunci *verificat*. Prima dată: computerul instalează aplicația,
    o deschide și cere asocierea prin cablu; tu atingi **Asociază** pe telefon (nu este nevoie de cod,
    cablul este dovada).
  * **Wi-Fi:** aplicația se anunță anonim: un nume aleatoriu și un cod care se schimbă la fiecare
    10 minute, pe care doar un computer asociat îl poate recunoaște (HMAC al secretului de asociere). Străinii
    din aceeași rețea nu pot vedea despre ce telefon este vorba și nici nu îl pot urmări.
  * **Bluetooth (ultima variantă, doar pentru a găsi telefonul):** același cod care se schimbă, plus adresa
    Wi-Fi a telefonului (criptată), într-un semnal Bluetooth LE. Dacă computerul poate accesa acea adresă, se
    conectează prin Wi-Fi; altfel îți spune acest lucru. **Prin Bluetooth nu se trimit niciodată fișiere.**
    Are nevoie de pachetul Python `bleak` (în requirements.txt) și de permisiunea „Dispozitive din apropiere”
    a telefonului.
* **Foldere pe telefon** – **Cameră** adaugă folderul standard al camerei Android `DCIM/Camera`;
  *Alege foldere…* listează folderele telefonului (capturi de ecran `Pictures/Screenshots`, Samsung
  `DCIM/Screenshots`, WhatsApp `Android/media/com.whatsapp/WhatsApp/Media`, `Movies`, `Download`
  …) sau te lasă să scrii unul (*Selectează tot* / *Deselectează tot*); *Elimină*.
  **Păstrează structura de foldere a telefonului** (opțiune): fișierele din alte foldere decât folderul
  camerei ajung în aceleași foldere în backup, ex. `Pixel 10 Pro - Sam/Pictures/Screenshots/`;
  folderul camerei este întotdeauna sortat în foldere an/lună. Fișierele deja salvate rămân
  unde sunt; fișierele identice sunt în continuare stocate o singură dată.
* **Destinații backup** – lista unităților de destinație; numele lungi de foldere pot fi derulate
  lateral (numele complet apare ca tooltip).
  Bifează una sau mai multe. *Adaugă unitate…* listează unitățile externe conectate, inclusiv
  unitățile atașate, dar încă nemontate (Linux: sunt montate cu un singur clic, fără parolă).
  *Adaugă folder…* deschide un selector de foldere. O unitate bifată care este atașată, dar
  nemontată, este montată automat la pornirea backup-ului. O previzualizare arată exact unde vor
  ajunge fișierele. Telefonul este detectat automat imediat ce este conectat prin ADB. Lista arată
  doar unitățile folosite anterior cu acest telefon (și proprietar), deja bifate; un telefon fără
  backup începe cu o listă goală. *Adaugă unitate…* oferă și folderele de backup folosite cu alte
  telefoane.

**Niciodată telefonul greșit.** Fiecare folder de backup își ține minte telefonul în `.phonebackup/phone.json`
(modelul, numărul de serie al telefonului, id-ul cheii aplicației de pe telefon; pentru backup-urile mai vechi programul le citește
din rapoarte). Când faci clic pe *Pornește backup-ul*, telefonul conectat este identificat pe loc și
comparat: un număr de serie sau o cheie diferită → **refuzat, nu se copiază nimic**. Dacă se poate compara doar
modelul sau modelul nu se potrivește cu numele backup-ului, trebuie să confirmi. Chiar înainte de
primul fișier, telefonul este identificat a doua oară (un telefon schimbat oprește backup-ul). Un telefon care
se conectează nu înlocuiește niciodată numele de smartphone setat de tine, iar cât timp un telefon este pe cablul USB, niciun
alt telefon nu este preluat prin Wi-Fi. Confirmarea arată conexiunea și, dacă nu este cea mai
rapidă, cum o poți face mai rapidă (cablu + depanare USB; cablu USB 3 în loc de USB 2).

**Gestionează backup-urile…** are patru file:

* **Importă backup vechi** – două variante:
  * *Adaugă la un backup existent* – adaugă backup-uri vechi sau orice foldere (fotografii, videoclipuri, RAW amestecate,
    foldere imbricate, duplicate) la unul dintre backup-urile tale, sortate în aceleași foldere an/lună.
  * *Backup nou al unui telefon vechi* – telefonul vechi primește un backup propriu („Galaxy S7 - Sam”):
    introdu numele telefonului și proprietarul și bifează unitatea (unitățile) de destinație.

  Adaugă unul sau mai multe foldere (ex. copia telefonului vechi și a cardului său SD) și fă clic pe
  *Alege folderele de importat…*: fiecare folder cu fișiere este listat cu fotografiile / videoclipurile /
  celelalte fișiere ale sale; datele aplicațiilor, cache-urile, miniaturile, coșul de gunoi și folderele ascunse sunt omise. Bifează
  folderele și alege pentru fiecare *Cameră* (→ foldere an/lună) sau *Altele* (→ își păstrează
  folderul original sub `Year/other/pictures | movies | other-files/`). Pentru un telefon vechi, folderele
  camerei și folderele normale de imagini/filme/descărcări sunt bifate dinainte, folderele de mesagerie și de
  capturi de ecran nu. Fiecărui fișier i se calculează hash-ul la sursă și este verificat după scriere,
  fișierele identice sunt stocate o singură dată (inclusiv față de ce există deja în backup), iar folderele
  vechi sunt doar citite. Fișierele omise sunt listate în raportul „Import <nume> <dată>”.
* **Al doilea spațiu de stocare (export)** – alege backup-ul, o a doua unitate sau **Google Drive** și tipul de
  export (implicit *Automat – Bunic-Tată-Fiu*). Exporturile anterioare sunt listate; cele vechi pot
  fi curățate (doar după ce confirmi). Vezi *Al doilea spațiu de stocare* mai jos.
* **Restaurează** – alege setul de export (pe o unitate sau pe Google Drive), starea și folderul
  țintă.
* **Setări** – calea adb (de obicei goală = găsită automat), timpul de așteptare, fsync, ținerea
  computerului treaz. Ține cursorul deasupra unei setări pentru o explicație.

**De ce ADB?** ADB (Android Debug Bridge, instrumentul USB al Google pentru Android) este varianta rapidă și sigură:
aproximativ 45–50 MB/s printr-un cablu USB 3 (măsurat cu un Pixel 10 Pro), în timp ce MTP - modul normal de
„transfer de fișiere” - atinge de obicei 10–20 MB/s. Cu ADB, fiecare fișier este verificat și cu
SHA-256 chiar pe telefon. Dacă ADB nu funcționează, aplicația trece la MTP și îți spune acest lucru.

**Ține computerul treaz:** cât timp rulează un backup, un import, un export sau o restaurare, computerul este
împiedicat să intre în standby (activat implicit, se dezactivează din *Setări*). Setările de alimentare
în sine nu sunt modificate – blocarea se încheie automat odată cu sarcina, chiar și după o cădere a programului.
Linux: standby-ul, suspendarea la inactivitate, închiderea capacului și o oprire normală sunt blocate (inhibitor
logind), iar temporizatorul de inactivitate al desktopului este pus pe pauză (D-Bus `org.freedesktop.ScreenSaver`
inhibit, așa cum face un player video - necesar pe COSMIC și alte desktopuri care se suspendă
singure după inactivitate). Prin urmare, cât timp rulează o sarcină, ecranul rămâne pornit.
Windows: trecerea în repaus la inactivitate este împiedicată, iar Windows întreabă înainte de oprire;
închiderea capacului și butonul de pornire urmează în continuare setările de alimentare din Windows.

**Pictogramă pe desktop (Linux):** `./install-linux-desktop.sh` pune o pictogramă de pornire pe desktop și în
meniul de aplicații (rulează-l din nou după mutarea folderului; `--remove` o elimină din nou).
Pictogramele sunt generate din `assets/PhoneBKP_Logo.webp` cu `.venv/bin/python tools/make_icons.py`.

Bara de progres, viteza, timpul rămas și jurnalul se află jos, cu *Anulează* (oprește
după fișierul curent), *Deschide raportul* și *Deschide folderul de backup*.

**Versiunea pentru terminal** (fără pachete suplimentare): `python3 smartphone_media_backup.py --cli`
sau direct `smartphone_media_backup.py backup | export | restore | settings`.
Dacă PySide6 lipsește, `smartphone_media_backup.py` pornește automat versiunea pentru terminal.

## Rezultatul pe unitate

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

* Folderele pentru ani și luni sunt create doar când un fișier ajunge în ele - fără foldere goale.
* Luna = data capturii din metadatele fotografiei/videoclipului → altfel numele fișierului
  (`PXL_20261102_…`) → altfel data fișierului.
* Fotografiile în mișcare (`*.MP.jpg`), HEIC, PNG, … contează ca fotografii; DNG și alte fișiere RAW ajung în `raw/`.
* Un al doilea raport în aceeași zi primește ora adăugată la nume.
* Nu se șterge niciodată nimic: nici pe telefon, nici în backup.
* Același nume, dar conținut diferit → noul fișier este salvat ca `name_1.jpg`. Conținutul identic
  este stocat o singură dată.

## Siguranță

* **Telefon → computer:** cu ADB, telefonul calculează singur SHA-256, iar acesta este comparat
  cu datele primite. Cu MTP acest lucru nu este posibil, iar raportul menționează acest lucru.
* **Computer → unitate:** fiecare copie este scrisă forțat pe disc, citită înapoi și SHA-256 comparat.
* Fișierele sunt scrise ca fișiere temporare și redenumite doar după verificare. Un backup întrerupt
  nu lasă niciodată fișiere pe jumătate; următoarea rulare pur și simplu continuă.
* Două (sau mai multe) unități sunt scrise **în același timp**. Telefonul este citit o singură dată.
* Spațiul liber este verificat mai întâi. Dacă o unitate cedează sau se umple, backup-ul continuă pe
  cealaltă unitate, iar raportul arată acest lucru cu roșu.

## Configurarea ADB (o singură dată). Astfel telefonul poate fi folosit în ~2 secunde, în loc să aștepți după MTP

**Pe telefon**

1. Setări → Despre telefon → atinge de 7 ori *Număr versiune* (modul dezvoltator activat).
2. Setări → Sistem → Opțiuni pentru dezvoltatori → activează **Depanare USB**.
3. Conectează telefonul, deblochează-l și confirmă *Permite depanarea USB* cu
   **Permiteți întotdeauna de pe acest computer**.

**Linux (Pop!_OS / Ubuntu)**

```
sudo apt install adb
adb devices          # should show your phone as "device"
```

**Cel mai simplu (Windows și Linux):** *Setări → Descarcă ADB…* descarcă platform-tools oficiale ale Google
direct de la Google în folderul propriu al aplicației (Windows:
`%LOCALAPPDATA%\phonebackup\platform-tools`, Linux: `~/.local/share/phonebackup/platform-tools`)
și setează calea - fără instalare, fără drepturi de administrator. adb nu este livrat împreună cu aplicația, deoarece
licența Google nu permite redistribuirea lui.

**Windows (manual)**

1. Descarcă *SDK Platform-Tools for Windows* de la
   https://developer.android.com/tools/releases/platform-tools
2. Dezarhivează-l astfel încât folderul `platform-tools` să fie **lângă `smartphone_media_backup.py`** (găsit automat),
   sau introdu calea către `adb.exe` în *Setări*.
3. Google Pixel: dacă telefonul nu este găsit, instalează *Google USB Driver*.

Dacă ADB nu funcționează, programul afișează un avertisment clar și trece la **varianta de rezervă MTP**:

* Linux: telefonul este montat automat prin gvfs/`gio`. Alege *Transfer de fișiere* în
  notificarea USB a telefonului.
* Windows: are nevoie o singură dată de `py -m pip install pywin32`. Apoi Explorer copiază fișierele.
  Este lent și nu a fost testat pe hardware real în timpul dezvoltării (vezi mai jos).

## Aplicația de pe telefon (Wi-Fi, fără depanare USB)

**Configurează aplicația de pe telefon…** afișează un cod QR. Scanează-l cu camera telefonului: pagina (servită de acest
computer) oferă **1. Descarcă aplicația** (deschide fișierul, atinge *Instalează*) și **2. Conectează aplicația la acest computer**.
Telefonul și computerul afișează același cod de 6 cifre - confirmă-l **pe telefon și pe computer**
(telefonul își dă cheia doar după atingerea ta acolo). Se face o singură dată. Asocierea prin cablul USB
funcționează la fel: ambele ecrane afișează un cod; atinge *Asociază* pe telefon doar dacă se potrivesc.

Prin cablu, programul poate instala și singur aplicația – **întreabă întotdeauna mai întâi** și
explică ce telefon, ce versiune, de ce și exact ce se întâmplă; nu se instalează nimic fără
clicul tău.

Pentru un backup: deschide *My Media Backup* pe telefon → **Pornește modul backup**. Computerul îl găsește și
se conectează; după backup, telefonul oprește singur modul backup (și după 5 minute fără
utilizare). Aplicația poate citi doar fotografii și videoclipuri; conexiunea este criptată (TLS, certificat
fixat la asociere). Computerul **preia** fișierele: cere fiecare fișier, iar telefonul răspunde doar
computerului asociat și nu trimite niciodată nimic din proprie inițiativă. Aceleași fișiere și căi ca prin ADB, deci backup-urile existente pur și simplu continuă.

## Backup prin Wi-Fi (fără cablu)

Folosește funcția Android integrată **Depanare wireless** (Android 11+, fără aplicație pe telefon). Totul
funcționează ca prin USB, inclusiv verificarea SHA-256 pe telefon; este doar mai lent (depinde de
Wi-Fi, de obicei 10–40 MB/s).

1. Telefon: *Setări → Sistem → Opțiuni pentru dezvoltatori → Depanare wireless* → activat (permite-o pentru
   rețea).
2. Aplicație: **Asociază prin Wi-Fi…** → pe telefon atinge *Asociază dispozitivul cu cod QR* și scanează codul
   (sau folosește *Asociază dispozitivul cu cod de asociere* și introdu cele 6 cifre). Necesar o singură dată.
3. De atunci înainte, telefonul este găsit automat ori de câte ori Depanarea wireless este pornită și telefonul și
   computerul sunt în același Wi-Fi. Dacă sunt disponibile atât USB, cât și Wi-Fi, se folosește USB.

**Fără router? Wi-Fi direct:** **Wi-Fi direct…** permite computerului să deschidă propria rețea Wi-Fi
(Linux: hotspot NetworkManager, 5 GHz dacă este posibil; Windows: deschide setările *Hotspot mobil*).
Telefonul se conectează la ea (cod QR pentru cameră), iar backup-ul rulează direct între
telefon și computer. Majoritatea adaptoarelor Wi-Fi renunță între timp la Wi-Fi-ul normal; acesta revine când
Wi-Fi-ul direct este oprit (aplicația întreabă când o închizi).

Un Wi-Fi Direct real (P2P) ar necesita o aplicație însoțitoare pe telefon; este planificat ca pas ulterior.

## Plan de backup per unitate

În lista de unități din *Backup nou*, fiecare unitate de backup are un **Plan de backup**:

* **Simplu** – un singur folder care crește, se adaugă doar fotografii și videoclipuri noi (ca mai sus).
* **Bunic-Tată-Fiu** – backup-uri datate ca pe un al doilea spațiu de stocare (vezi mai jos): un backup **complet**
  la fiecare 3 luni, unul **diferențial** în fiecare lună, **incrementale** între ele.
  Un backup complet/diferențial conține și fișierele anterioare de care are nevoie (copiate pe unitate și
  verificate), astfel încât fotografiile șterse de pe telefon rămân în fiecare backup complet.

Cele două pot fi combinate, ex. *Simplu* pe un HDD și *Bunic-Tată-Fiu* pe celălalt. Un folder de
telefon păstrează planul cu care a fost început.

## Al doilea spațiu de stocare (export)

*Gestionează backup-urile → Al doilea spațiu de stocare* copiază un backup pe altă unitate sau pe Google Drive. Fiecare export
primește propriul folder:

```
PhoneBackups-Export/Pixel 10 Pro - Sam/
├── 2026-11-02_14-30-00_full/
├── 2026-11-20_09-12-45_incremental/
├── 2026-12-01_18-03-10_differential/
└── .phonebackup-export/catalog.sqlite
```

| Tip           | Copiază                                            |
|---------------|----------------------------------------------------|
| completă      | tot                                                |
| diferențială  | tot ce este nou de la ultimul export **complet**   |
| incrementală  | tot ce este nou de la **ultimul** export (de orice tip) |

**Automat – Bunic-Tată-Fiu** (implicit) alege tipul: complet la fiecare 3 luni
(bunicul), diferențial în fiecare lună (tatăl), incremental între ele (fiul); aplicația arată
care urmează și de ce. Păstrează cele mai noi 4 exporturi complete, 3 diferențiale și 6 incrementale,
plus tot ce le trebuie pentru o restaurare; cele mai vechi sunt propuse pentru eliminare și șterse
**doar după ce confirmi** (*Curăță exporturile vechi…*).

Fiecare fișier exportat este verificat față de SHA-256 înregistrat la momentul backup-ului. Un fișier care a fost
deteriorat pe prima unitate (bit rot) este raportat ca ATENȚIE.
*Restaurează* reconstruiește un folder complet din cel mai scurt lanț (complet + cel mai nou diferențial +
incrementalele de după el) și verifică fiecare fișier.

### Google Drive

*Adaugă la spațiul de stocare cloud → Google Drive* te autentifică prin browser. Aplicația poate vedea doar
fișierele pe care le-a încărcat ea însăși (dreptul Google `drive.file`); autentificarea rămâne pe acest computer.
Două tipuri de export:

* **Copie** – o oglindă a backup-ului în *My Drive/My Smartphone Media Backup/Phone - Owner*:
  se încarcă doar fișiere noi, nimic nu este șters sau suprascris.
* **Bunic-Tată-Fiu** în *Phone - Owner (Grandfather-Father-Son)*: fiecare fotografie este stocată
  **o singură dată** – exporturile complete și diferențiale fac legătura cu fișierele aflate deja pe Google Drive
  (scurtături, fără spațiu suplimentar; inclusiv cu Copia). Curățarea mută fișierele pe care exporturile mai noi încă
  le folosesc în acestea, înainte de a șterge ceva. Restaurarea descarcă fișierele și le verifică. Te rugăm
  să nu ștergi manual fotografii individuale de acolo – fiecare export care face legătura cu ele le-ar pierde.

Fiecare încărcare este verificată față de SHA-256 propriu al Google; spațiul liber este verificat înainte de încărcare.
Politica de confidențialitate: <https://machetso.github.io/my-smartphone-media-backup/privacy.html>

Compilările din codul sursă au nevoie de cheia Google a aplicației: `python3 tools/set_google_key.py client_secret_….json`
(scrie fișierul `phonebackup/_gkey.py`, ignorat de git); compilările de release o primesc din secretele GitHub.

## Setări

Salvate în `~/.config/phonebackup/config.json` (Windows: `%APPDATA%\PhoneBackup\config.json`):
numele proprietarului, folderele de pe telefon (implicit `DCIM/Camera`, se pot selecta mai multe în program),
unitățile, calea adb.

## Teste

```
python3 -m unittest discover tests
```

## Testat

* Linux (Pop!_OS) cu un Google Pixel 10 Pro (Android 17) prin ADB pe USB 3:
  1372 de fișiere / 20 GB salvate pe două HDD-uri externe în același timp și verificate, aproximativ 24 MB/s.
* Samsung Galaxy S20 FE prin USB (ADB) și prin Wi-Fi cu aplicația de pe telefon 0.3.3:
  12,4 MB/s prin Wi-Fi, fără erori; actualizarea aplicației de pe telefon prin cablu, cu întrebarea de instalare.
* Google Drive: Copie și Bunic-Tată-Fiu cu un backup de 20 GB (1381 de fișiere, aproximativ
  4 MB/s la încărcare), scurtături, curățare și restaurare verificate.
* Încă netestat pe hardware real: varianta de rezervă MTP (Linux gvfs, Windows Explorer) și Windows în general.

## Licență

MIT – vezi [LICENSE](LICENSE).
