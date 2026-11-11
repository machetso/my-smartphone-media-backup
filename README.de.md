# My Smartphone Media Backup

Geprüftes, inkrementelles Backup von Fotos und Videos von einem Android-Telefon auf ein oder mehrere
externe Laufwerke, sortiert nach Jahr und Monat, mit einem Bericht nach jedem Durchlauf.
Python 3.8+, läuft unter Linux und Windows. Die grafische Oberfläche braucht PySide6; die
Terminal-Version braucht keine zusätzlichen Pakete.

## Download

Fertige Programme für Linux und Windows findest du auf der
[Releases-Seite](../../releases) – keine Python-Installation nötig.
Windows: Lade `My-Smartphone-Media-Backup-v….exe` herunter und doppelklicke darauf (oder die `.zip` mit
README und Lizenz); Linux: die `.tar.gz`.
Was neu ist, steht in [CHANGELOG.md](CHANGELOG.md).

**Updates:** Beim Start schaut das Programm, ob eine neuere Version erschienen ist (einmal am Tag; lässt sich
in den Einstellungen abschalten), und bietet **Jetzt aktualisieren** oder **Jetzt nicht** an. *Jetzt aktualisieren* lädt die neue
Version herunter, prüft, ob sie mit dem Release-Schlüssel des Projekts signiert ist, tauscht das Programm aus und startet
es neu – Einstellungen, Laufwerke, Telefone und Kopplungen bleiben erhalten. Startet die neue Version nicht, wird die alte
automatisch wiederhergestellt. (Aus dem Quellcode gestartet: stattdessen mit `git pull` aktualisieren.)

**Ein Release erstellen (Maintainer):** Tag pushen → GitHub Actions baut das Release als Entwurf →
`python3 tools/sign_release.py sign vX.Y.Z` auf dem Computer des Maintainers (fügt die signierte
`update-manifest.json` hinzu; der private Schlüssel kommt nie zu GitHub) → Release veröffentlichen.

## Aus dem Quellcode starten

**Grafische Oberfläche** (braucht PySide6):

```
./start-linux.sh                   # Linux (uses the project's .venv, PySide6 is already installed there)
start-windows.pyw                 # Windows: double-click (after: py -m pip install PySide6)
```

**Startbildschirm:** **Deine Telefone** – ein Eintrag pro Backup (z. B. *Sam's Pixel 10 Pro*,
*Kim's Galaxy A55*) mit dem Datum des letzten Backups und einer eigenen Schaltfläche **Backup aktualisieren**,
die aktiv ist, wenn genau dieses Telefon und eines seiner Laufwerke angeschlossen sind (gleiche Ordner und Laufwerke,
nur neue Fotos und Videos). Backups, die angelegt wurden, bevor es diese Liste gab, werden auf den angeschlossenen
Laufwerken gefunden. *Alle auswählen* / *Aus Liste entfernen* blenden Telefone aus (ihre Backups bleiben auf den Laufwerken). Darunter:
**Neues Backup…** (ein anderes Telefon oder andere Ordner / Laufwerke), **Backup-Einstellungen…** und
**Backups verwalten…** (die Tabs weiter unten).

**☰ Menü** (oben rechts auf dem Startbildschirm, schon beim allerersten Start): **Sprache**, **Anleitung** (dieser Text, in der gewählten Sprache), **Programmeinstellungen…** und **Über**.

**Backup-Einstellungen** (Unterseite):

* **Telefonverbindung** – das Programm **nutzt immer die schnellste Verbindung, die es findet**; du musst
  keine auswählen. Die Übersicht zeigt die Geschwindigkeit jeder Verbindungsart, die genutzte ist markiert, und
  das Protokoll sagt, ob sie die schnellste ist und was schneller wäre. Taucht das Telefon mit USB-Debugging
  am Kabel auf, während es über Wi-Fi verbunden ist, wechselt das Programm von selbst
  zum Kabel. **Schnellste Verbindung finden** prüft Kabel, Wi-Fi und Bluetooth und zeigt,
  was verfügbar ist.

  **Einfache Ansicht:** nur der Verbindungsstatus und, wenn es hilft, ein Tipp darunter. Ein
  Telefon ohne bisheriges Backup: Der Tipp empfiehlt das USB-Kabel mit USB-Debugging (das erste
  Backup kopiert alle Fotos und Videos). Ein Telefon am Kabel ohne USB-Debugging oder über Wi-Fi /
  Dateiübertragung verbunden: Der Tipp sagt, wie viel schneller USB-Debugging ist – *So schaltest
  du USB-Debugging ein…* öffnet die Schritt-für-Schritt-Anleitung (siehe unten), *Ohne fortfahren
  (langsamere Dateiübertragung)* nutzt die normale Dateiübertragung des Telefons. Hake
  **Erweiterte Verbindungseinstellungen** an, um die Geschwindigkeitsübersicht, alle
  Verbindungsknöpfe und *… nach dem Backup ausschalten* zu sehen.

  | Verbindung | Geschwindigkeit |
  |---|---|
  | USB-Kabel + USB-Debugging (von der Telefon-App oder von Hand eingeschaltet) | 45–50 MB/s (USB 3), ~20–30 MB/s (USB 2) |
  | USB-Kabel, normale Dateiübertragung (MTP – nur auf Wunsch) | 10–20 MB/s |
  | Wi-Fi: Telefon-App oder Kabelloses Debugging | 10–40 MB/s, abhängig vom Wi-Fi |
  | Wi-Fi direkt zu diesem Computer (ohne Router) | 10–30 MB/s |

  *USB-Debugging einschalten (erstes Mal)…* ist eine Schritt-für-Schritt-Anleitung: Sie liest das Modell des
  Telefons am Kabel aus (funktioniert, bevor USB-Debugging an ist), enthält die Schritte für Pixel, Samsung,
  Xiaomi / Redmi / POCO, OnePlus / OPPO / realme, Motorola, Huawei / Honor, Sony und Nothing und
  *Im Web nach diesem Telefon suchen* für alle anderen. Android verlangt das einmal von Hand – kein Programm
  kann USB-Debugging vorher einschalten.
  **Die Telefon-App schaltet es:** Bei der ersten Verbindung über USB-Debugging bietet das Programm an,
  die Telefon-App *My Media Backup* zu installieren und ihr das Recht zu geben, USB-Debugging zu schalten (Androids
  `WRITE_SECURE_SETTINGS`, über das Kabel erteilt – die App kann es sich nicht selbst holen). Ab dann:
  App öffnen → **Backup über Kabel erlauben** → anstecken. Nach jedem Backup schaltet der Computer
  USB-Debugging (oder Kabelloses Debugging) wieder aus (*USB-Debugging / Kabelloses Debugging nach dem Backup auf dem Telefon ausschalten*,
  standardmäßig an). Nur USB-Debugging wird ausgeschaltet; die Entwickleroptionen bleiben.

  **Regeln für das Ausschalten des Debuggings** (die Telefon-App setzt sie durch, auch wenn der Computer weg ist):
  1. Backups über Wi-Fi laufen normalerweise über die Telefon-App mit ausgeschaltetem Debugging; Kabelloses Debugging
     nur für Telefone ohne die App.
  2. Eine Verbindung pro Backup: über das Kabel → Kabelloses Debugging wird beim Start ausgeschaltet;
     über die App per Wi-Fi → USB-Debugging wird beim Start ausgeschaltet.
  3. Die Telefon-App schaltet Kabelloses Debugging nie ein.
  4. 5 Minuten nach *Backup über Kabel erlauben* ohne Backup-Start → aus (Countdown auf dem Telefon).
  5. Während eines Backups meldet der Computer alle 30 s „noch da“; 2 Minuten lang nichts → aus.
  6. Direkt nach dem Backup schaltet der Computer es aus (und beendet den Backup-Modus auf dem Telefon).

  **Das Telefon sicher erkennen:** Beim Koppeln erzeugt die Telefon-App einen Schlüssel im
  Sicherheitschip des Telefons; der Computer speichert dessen Fingerabdruck. Modell, Seriennummer oder Namen wird nie
  vertraut – jede Verbindung prüft diesen Schlüssel (TLS mit dem fest hinterlegten Zertifikat), bevor das
  Geheimnis des Computers gesendet wird.
  * **Kabel:** Solange die App läuft, erreicht der Computer sie über das Kabel (`adb forward`) und
    prüft den Schlüssel – der Status zeigt dann *geprüft*. Beim ersten Mal installiert der Computer die App,
    öffnet sie und bittet darum, über das Kabel zu koppeln; du tippst auf dem Telefon auf **Koppeln** (kein Code nötig, das
    Kabel ist der Beweis).
  * **Wi-Fi:** Die App meldet sich anonym: mit einem zufälligen Namen und einem Code, der sich alle
    10 Minuten ändert und den nur ein gekoppelter Computer erkennen kann (HMAC des Kopplungsgeheimnisses). Fremde
    im selben Netzwerk können nicht sehen, welches Telefon es ist, und es nicht verfolgen.
  * **Bluetooth (letzter Ausweg, nur um das Telefon zu finden):** derselbe wechselnde Code plus die
    Wi-Fi-Adresse des Telefons (verschlüsselt) in einem Bluetooth-LE-Signal. Kann der Computer diese Adresse erreichen,
    verbindet er sich über Wi-Fi; andernfalls sagt er es. **Über Bluetooth werden nie Dateien gesendet.**
    Braucht das Python-Paket `bleak` (in requirements.txt) und die Berechtigung „Geräte in der Nähe“
    auf dem Telefon.
* **Ordner auf dem Telefon** – **Kamera** fügt Androids Standard-Kameraordner `DCIM/Camera` hinzu;
  *Ordner wählen…* listet die Ordner des Telefons auf (Screenshots `Pictures/Screenshots`, Samsung
  `DCIM/Screenshots`, WhatsApp `Android/media/com.whatsapp/WhatsApp/Media`, `Movies`, `Download`
  …) oder lässt dich einen eintippen (*Alle auswählen* / *Keine auswählen*); *Entfernen*.
  **Ordnerstruktur des Telefons beibehalten** (Option): Dateien aus anderen Ordnern als dem Kamera-
  ordner landen im Backup in denselben Ordnern, z. B. `Sam/Pixel 10 Pro/Pictures/Screenshots/`;
  der Kameraordner wird immer in Jahres-/Monatsordner sortiert. Bereits gesicherte Dateien bleiben,
  wo sie sind; identische Dateien werden weiterhin nur einmal gespeichert.
* **Backup-Ziele** – die Liste der Ziellaufwerke; lange Ordnernamen lassen sich
  seitlich scrollen (voller Name als Tooltip).
  Hake eines oder mehrere an. *Laufwerk hinzufügen…* listet die angeschlossenen externen Laufwerke
  auf, auch Laufwerke, die angeschlossen, aber noch nicht eingebunden sind (Linux: Sie werden mit
  einem Klick eingebunden, ohne Passwort). *Ordner hinzufügen…* öffnet eine Ordnerauswahl. Ein
  angehaktes Laufwerk, das angeschlossen, aber nicht eingebunden ist, wird beim Start des Backups
  automatisch eingebunden. Eine Vorschau zeigt genau, wohin die Dateien kommen. Das Telefon wird
  automatisch erkannt, sobald es per ADB angeschlossen ist. Die Liste zeigt nur die Laufwerke, die
  schon mit diesem Telefon (und Besitzer) genutzt wurden, bereits angehakt; ein Telefon ohne
  Backup beginnt mit einer leeren Liste. *Laufwerk hinzufügen…* bietet auch die Backup-Ordner an,
  die mit anderen Telefonen genutzt wurden.

**Nie das falsche Telefon.** Jeder Backup-Ordner merkt sich sein Telefon in `.phonebackup/phone.json`
(Modell, Seriennummer des Telefons, Schlüssel-ID der Telefon-App; bei älteren Backups liest das Programm
sie aus den Berichten). Wenn du auf *Backup starten* klickst, wird das angeschlossene Telefon live erkannt und
verglichen: andere Seriennummer oder anderer Schlüssel → **abgelehnt, nichts kopiert**. Lässt sich nur das Modell
vergleichen oder passt das Modell nicht zum Namen des Backups, musst du es bestätigen. Direkt vor der
ersten Datei wird das Telefon ein zweites Mal erkannt (ein ausgetauschtes Telefon stoppt das Backup). Ein Telefon, das
sich verbindet, ersetzt nie den von dir festgelegten Smartphone-Namen, und solange ein Telefon am USB-Kabel hängt, wird kein
anderes Telefon über Wi-Fi übernommen. Die Bestätigung zeigt die Verbindung und, falls sie nicht die
schnellste ist, wie es schneller geht (Kabel + USB-Debugging; USB-3-Kabel statt USB 2).

**Backups verwalten…** hat vier Tabs:

* **Altes Laufwerk / altes Handy** – sichert die Fotos und Videos einer alten Festplatte oder eines alten
  Telefons wie ein Telefon-Backup. Zwei Wege:
  * *Zu einem vorhandenen Backup hinzufügen* – fügt alte Backups oder beliebige Ordner (gemischte Fotos, Videos, RAW,
    verschachtelte Ordner, Duplikate) zu einem deiner Backups hinzu.
  * *Neues Backup (altes Handy oder altes Laufwerk)* – bekommt ein eigenes Backup (z. B. „Galaxy S7 - Sam“ oder
    „Alte Festplatte - Sam“): einen Namen und den Besitzer eingeben und das oder die Ziellaufwerke anhaken.

  Füge einen oder mehrere Ordner hinzu (z. B. die Kopie des alten Telefons und seiner SD-Karte oder die Fotoordner
  des alten Laufwerks) und klicke auf *Zu importierende Ordner wählen…*: Jeder Ordner mit Dateien wird mit seinen
  Fotos / Videos / sonstigen Dateien aufgelistet; App-Daten, Caches, Vorschaubilder, Papierkorb und versteckte Ordner
  werden ausgelassen. Hake die Ordner an und wähle für jeden:
  * *In Jahres-/Monatsordner sortieren* – die Fotos und Videos werden genau wie bei einem Telefon-Backup nach Datum
    sortiert (`2019/19.07`, RAW → `2019/raw/19.07`).
  * *Ordner so lassen, wie er ist* – der Ordner wird 1:1 mit Namen und Pfad oben ins Backup kopiert
    (z. B. `Urlaub Italien 2019/Tag 1/`). Jeder Ordner wird mit seinen eigenen Dateien importiert, seine
    Unterordner sind eigene Zeilen – hake sie ebenfalls an, um den ganzen Ordnerbaum zu behalten.

  Bei einem alten Telefon werden die Kameraordner zum Sortieren vorgeschlagen, normale Bild-/Film-/Download-Ordner
  zum Beibehalten; Messenger- und Screenshot-Ordner sind nicht vorab angehakt. Jede Datei wird an der Quelle gehasht
  und nach dem Schreiben geprüft, identische Dateien werden nur einmal gespeichert (auch im Abgleich mit dem, was
  schon im Backup ist), die alten Ordner werden nur gelesen. Übersprungene Dateien stehen im Bericht
  „Import <name> <date>“. (Importe vor Version 0.9.8.3 haben beibehaltene Ordner unter
  `Year/other/pictures | movies | other-files/` abgelegt – dort bleiben sie.)
* **Zweitspeicher (Export)** – wähle das Backup, ein zweites Laufwerk oder **Google Drive** und die Export-
  art (standardmäßig *Automatisch – Großvater-Vater-Sohn*). Frühere Exporte werden aufgelistet; alte können
  aufgeräumt werden (nur nach deiner Bestätigung). Siehe *Zweitspeicher* weiter unten.
* **Wiederherstellen** – wähle den Export-Satz (auf einem Laufwerk oder auf Google Drive), den Stand und den Ziel-
  ordner.
* **Einstellungen** – adb-Pfad (normalerweise leer = wird automatisch gefunden), Wartezeit, fsync, Computer
  wach halten. Fahre mit der Maus über eine Einstellung, um eine Erklärung zu sehen.

**Warum ADB?** ADB (Android Debug Bridge, Googles USB-Werkzeug für Android) ist der schnelle und sichere Weg:
etwa 45–50 MB/s über ein USB-3-Kabel (gemessen mit einem Pixel 10 Pro), während MTP – der normale
Modus „Dateiübertragung“ – typischerweise 10–20 MB/s erreicht. Mit ADB wird außerdem jede Datei direkt auf dem Telefon mit
SHA-256 geprüft. Funktioniert ADB nicht, weicht die App auf MTP aus und sagt das.

**Computer wach halten:** Während ein Backup, Import, Export oder eine Wiederherstellung läuft, wird der Computer
daran gehindert, in den Standby zu gehen (standardmäßig an, abschaltbar unter *Einstellungen*). Die Energieeinstellungen
selbst werden nicht geändert – die Sperre endet automatisch mit dem Auftrag, selbst nach einem Absturz.
Linux: Standby, Ruhezustand bei Leerlauf, das Zuklappen des Deckels und ein normales Herunterfahren werden blockiert (logind-
Inhibitor), und der eigene Leerlauf-Timer des Desktops wird angehalten (D-Bus `org.freedesktop.ScreenSaver`
inhibit, wie es ein Videoplayer macht – nötig unter COSMIC und anderen Desktops, die nach Inaktivität
von selbst in den Ruhezustand gehen). Während ein Auftrag läuft, bleibt der Bildschirm daher an.
Windows: Der Ruhezustand bei Inaktivität wird verhindert, und Windows fragt vor dem Herunterfahren nach;
das Zuklappen des Deckels und der Ein-/Aus-Schalter folgen weiterhin den Windows-Energieeinstellungen.

**Desktop-Symbol (Linux):** `./install-linux-desktop.sh` legt ein Startsymbol auf den Desktop und ins
App-Menü (nach dem Verschieben des Ordners erneut ausführen, `--remove` entfernt es wieder).
Die Symbole werden aus `assets/PhoneBKP_Logo.webp` mit `.venv/bin/python tools/make_icons.py` erstellt.

Fortschrittsbalken, Geschwindigkeit, Restzeit und das Protokoll befinden sich unten, mit *Abbrechen* (stoppt
nach der aktuellen Datei), *Bericht öffnen* und *Backup-Ordner öffnen*.

**Terminal-Version** (keine zusätzlichen Pakete): `python3 smartphone_media_backup.py --cli`
oder direkt `smartphone_media_backup.py backup | export | restore | settings`.
Fehlt PySide6, startet `smartphone_media_backup.py` automatisch die Terminal-Version.

## Ergebnis auf dem Laufwerk

```
PhoneBackups/
└── Sam/                                     ← one folder per owner
    └── Pixel 10 Pro/                        ← the backup of this phone
        ├── Logs/                            ← reports and logs
        │   └── Backup Pixel 10 Pro Sam 2026-11-02.txt / .html / .csv
        ├── 2026/
        │   ├── 26.01/  …  26.12/            (photos + videos of each month)
        │   ├── raw/26.01/ …  raw/26.12/     (only if RAW/DNG files exist)
        │   └── other/pictures|movies|other-files/<original folder>/   (only old phone imports)
        └── .phonebackup/index.sqlite        ← what is already backed up (do not delete)
```

* Name des Monatsordners = Jahr + Monat: `26.02` ist Februar 2026. Backups älterer Versionen
  (`02.February-photos` / `02.February-videos`) werden vor dem nächsten Backup oder Export
  umgestellt – vorher zeigt das Programm die alten Monatsordner, und du entfernst den Haken bei
  denen, die **ihren alten Namen und ihre Struktur behalten** sollen (sie werden nie geändert). Die
  Wahl gilt für jedes Laufwerk und für Google Drive; Dateien werden nur verschoben, nie gelöscht.
  Eigene Ordner und Ordner mit „Ordnerstruktur beibehalten“ werden nie angefasst.
* Jahres- und Monatsordner werden nur angelegt, wenn eine Datei hineinkommt – keine leeren Ordner.
* Monat = Aufnahmedatum aus den Foto-/Video-Metadaten → sonst der Dateiname
  (`PXL_20261102_…`) → sonst das Dateidatum.
* Bewegte Fotos (`*.MP.jpg`), HEIC, PNG, … zählen als Fotos; DNG und andere RAW-Dateien kommen nach `raw/`.
* Backup-Ordner = Besitzer / Telefon (`Sam/Pixel 10 Pro`). Backups älterer Versionen
  (`Pixel 10 Pro - Sam`) werden automatisch dorthin verschoben; gibt es beide, werden sie zusammengeführt – nichts
  wird überschrieben oder gelöscht.
* Berichte (`.txt` / `.html` / `.csv`) und das Protokoll eines Auftrags, der ohne Bericht endete, kommen in den
  Ordner `Logs` neben den Jahresordnern. Berichte älterer Versionen werden vor dem nächsten Backup, Import oder
  Export automatisch dorthin verschoben.
* Ein zweiter Bericht am selben Tag bekommt die Uhrzeit an den Namen angehängt.
* Es wird nie etwas gelöscht: nicht auf dem Telefon, nicht im Backup.
* Gleicher Name, aber anderer Inhalt → die neue Datei wird als `name_1.jpg` gespeichert. Identischer Inhalt
  wird nur einmal gespeichert.

## Sicherheit

* **Telefon → Computer:** Mit ADB berechnet das Telefon die SHA-256 selbst, und sie wird mit den
  empfangenen Daten verglichen. Mit MTP ist das nicht möglich, und der Bericht sagt das.
* **Computer → Laufwerk:** Jede Kopie wird fest auf den Datenträger geschrieben, zurückgelesen und ihre SHA-256 verglichen.
* Dateien werden als temporäre Dateien geschrieben und erst nach der Prüfung umbenannt. Ein abgebrochenes Backup
  hinterlässt nie halbe Dateien; der nächste Durchlauf macht einfach weiter.
* Zwei (oder mehr) Laufwerke werden **gleichzeitig** beschrieben. Das Telefon wird nur einmal gelesen.
* Der freie Speicherplatz wird vorher geprüft. Fällt ein Laufwerk aus oder läuft es voll, macht das Backup auf dem
  anderen Laufwerk weiter, und der Bericht zeigt das in Rot.

## ADB einrichten (einmalig). Damit ist das Telefon in ~2 Sekunden bereit, statt auf MTP zu warten

**Auf dem Telefon**

1. Einstellungen → Über das Telefon → 7× auf *Build-Nummer* tippen (Entwicklermodus an).
2. Einstellungen → System → Entwickleroptionen → **USB-Debugging** einschalten.
3. Telefon anschließen, entsperren und *USB-Debugging zulassen* mit
   **Von diesem Computer immer zulassen** bestätigen.

**Linux (Pop!_OS / Ubuntu)**

```
sudo apt install adb
adb devices          # should show your phone as "device"
```

**Am einfachsten (Windows und Linux):** *Einstellungen → ADB herunterladen…* holt Googles offizielle
Platform-Tools direkt von Google in den eigenen Ordner der App (Windows:
`%LOCALAPPDATA%\phonebackup\platform-tools`, Linux: `~/.local/share/phonebackup/platform-tools`)
und setzt den Pfad – keine Installation, keine Administratorrechte. adb wird nicht mit der App ausgeliefert, weil
Googles Lizenz die Weitergabe nicht erlaubt.

**Windows (von Hand)**

1. *SDK Platform-Tools for Windows* herunterladen von
   https://developer.android.com/tools/releases/platform-tools
2. So entpacken, dass der Ordner `platform-tools` **neben `smartphone_media_backup.py`** liegt (wird automatisch gefunden),
   oder den Pfad zu `adb.exe` unter *Einstellungen* eintragen.
3. Google Pixel: Wird das Telefon nicht gefunden, installiere den *Google USB Driver*.

Funktioniert ADB nicht, zeigt das Programm eine deutliche Warnung und wechselt zum **MTP-Ausweichweg**:

* Linux: Das Telefon wird automatisch über gvfs/`gio` eingebunden. Wähle in der USB-Benachrichtigung des Telefons
  *Dateiübertragung*.
* Windows: Braucht einmalig `py -m pip install pywin32`. Der Explorer kopiert dann die Dateien.
  Das ist langsam und wurde während der Entwicklung nicht auf echter Hardware getestet (siehe unten).

## Telefon-App (Wi-Fi, ohne USB-Debugging)

**Telefon-App einrichten…** zeigt einen QR-Code. Scanne ihn mit der Kamera des Telefons: Die Seite (von diesem
Computer bereitgestellt) bietet **1. App herunterladen** (Datei öffnen, auf *Installieren* tippen) und **2. App mit diesem Computer verbinden**.
Telefon und Computer zeigen denselben 6-stelligen Code – bestätige ihn **auf dem Telefon und auf dem Computer**
(das Telefon gibt seinen Schlüssel erst nach deinem Tippen dort heraus). Nur einmal nötig. Das Koppeln über das USB-Kabel
funktioniert genauso: Beide Bildschirme zeigen einen Code, tippe auf dem Telefon nur dann auf *Koppeln*, wenn sie übereinstimmen.

Über das Kabel kann das Programm die App auch selbst installieren – es **fragt immer vorher** und
erklärt, welches Telefon, welche Version, warum und was genau passiert; ohne deinen Klick wird nichts
installiert.

Für ein Backup: Öffne *My Media Backup* auf dem Telefon → **Backup-Modus starten**. Der Computer findet es und
verbindet sich; nach dem Backup schaltet das Telefon den Backup-Modus selbst aus (auch nach 5 Minuten
ohne Nutzung). Die App kann nur Fotos und Videos lesen; die Verbindung ist verschlüsselt (TLS, Zertifikat
beim Koppeln fest hinterlegt). Der Computer **holt** die Dateien: Er fragt nach jeder Datei, das Telefon antwortet nur
dem gekoppelten Computer und sendet nie von selbst etwas. Dieselben Dateien und Pfade wie über ADB, vorhandene Backups gehen also einfach weiter.

## Backup über Wi-Fi (ohne Kabel)

Nutzt Androids eingebautes **Kabelloses Debugging** (Android 11+, keine App auf dem Telefon). Alles
funktioniert wie über USB, einschließlich der SHA-256-Prüfung auf dem Telefon; es ist nur langsamer (abhängig vom
Wi-Fi, typischerweise 10–40 MB/s).

1. Telefon: *Einstellungen → System → Entwickleroptionen → Kabelloses Debugging* → an (für das
   Netzwerk erlauben).
2. App: **Über Wi-Fi koppeln…** → auf dem Telefon auf *Gerät über QR-Code koppeln* tippen und den Code scannen
   (oder *Gerät mit Kopplungscode koppeln* verwenden und die 6 Ziffern eintippen). Nur einmal nötig.
3. Ab dann wird das Telefon automatisch gefunden, sobald Kabelloses Debugging an ist und Telefon und
   Computer im selben Wi-Fi sind. Sind sowohl USB als auch Wi-Fi verfügbar, wird USB genutzt.

**Kein Router? Direktes Wi-Fi:** **Direktes Wi-Fi…** lässt den Computer ein eigenes Wi-Fi-Netzwerk öffnen
(Linux: NetworkManager-Hotspot, wenn möglich 5 GHz; Windows: öffnet die Einstellungen für den *Mobilen Hotspot*). Das Telefon verbindet sich damit (QR-Code für die Kamera), und das Backup läuft direkt zwischen
Telefon und Computer. Die meisten Wi-Fi-Adapter trennen währenddessen das normale Wi-Fi; es kommt zurück, wenn das
direkte Wi-Fi beendet wird (die App fragt beim Schließen nach).

Echtes Wi-Fi Direct (P2P) bräuchte eine Begleit-App auf dem Telefon; das ist als späterer Schritt geplant.

## Backup-Plan pro Laufwerk

In der Laufwerksliste von *Neues Backup* hat jedes Backup-Laufwerk einen **Backup-Plan**:

* **Einfach** – ein Ordner, der wächst; nur neue Fotos und Videos kommen hinzu (wie oben gezeigt).
* **Großvater-Vater-Sohn** – datierte Backups wie auf einem Zweitspeicher (siehe unten): alle 3 Monate ein **volles**
  Backup, jeden Monat ein **differenzielles**, dazwischen **inkrementelle**.
  Ein volles/differenzielles Backup enthält auch die früheren Dateien, die es braucht (auf dem Laufwerk kopiert und
  geprüft), sodass vom Telefon gelöschte Fotos in jedem vollen Backup erhalten bleiben.

Beides lässt sich mischen, z. B. *Einfach* auf der einen HDD und *Großvater-Vater-Sohn* auf der anderen. Ein Telefon-
ordner behält den Plan, mit dem er begonnen wurde.

## Zweitspeicher (Export)

*Backups verwalten → Zweitspeicher* kopiert ein Backup auf ein anderes Laufwerk oder zu Google Drive. Jeder Export
bekommt einen eigenen Ordner:

```
PhoneBackups-Export/Sam/Pixel 10 Pro/
├── 2026-11-02_14-30-00_full/            (with the export report in Logs/)
├── 2026-11-20_09-12-45_incremental/
├── 2026-12-01_18-03-10_differential/
└── .phonebackup-export/catalog.sqlite
```

| Art           | Kopiert                                            |
|---------------|----------------------------------------------------|
| voll          | alles                                              |
| differenziell | alles Neue seit dem letzten **vollen** Export      |
| inkrementell  | alles Neue seit dem **letzten** Export (beliebige Art) |

**Automatisch – Großvater-Vater-Sohn** (Standard) wählt die Art: voll alle 3 Monate
(Großvater), differenziell jeden Monat (Vater), dazwischen inkrementell (Sohn); die App zeigt,
welche als Nächstes kommt und warum. Sie behält die neuesten 4 vollen, 3 differenziellen und 6 inkrementellen
Exporte plus alles, was sie für eine Wiederherstellung brauchen; ältere werden zum Entfernen vorgeschlagen und
**erst nach deiner Bestätigung** gelöscht (*Alte Exporte aufräumen…*).

Jede exportierte Datei wird mit der SHA-256 geprüft, die beim Backup festgehalten wurde. Eine Datei, die
auf dem ersten Laufwerk beschädigt wurde (Bit Rot), wird als WARNUNG gemeldet.
*Wiederherstellen* baut einen vollständigen Ordner aus der kürzesten Kette wieder auf (voll + neuestes differenzielles +
die inkrementellen danach) und prüft jede Datei.

### Google Drive

*Zum Cloud-Speicher hinzufügen → Google Drive* meldet sich über den Browser an. Die App darf nur die
Dateien sehen, die sie selbst hochgeladen hat (Googles Recht `drive.file`); die Anmeldung bleibt auf diesem Computer.
Zwei Exportarten:

* **Kopie** – ein Spiegel des Backups in *My Drive/My Smartphone Media Backup/Telefon - Besitzer*:
  Nur neue Dateien werden hochgeladen, nichts wird gelöscht oder überschrieben.
* **Großvater-Vater-Sohn** in *Telefon - Besitzer (Großvater-Vater-Sohn)*: Jedes Foto wird
  nur **einmal** gespeichert – volle und differenzielle Exporte verweisen auf Dateien, die schon auf Google Drive liegen
  (Verknüpfungen, kein zusätzlicher Speicherplatz; auch auf die Kopie). Das Aufräumen verschiebt Dateien, die neuere Exporte noch
  nutzen, in diese, bevor etwas gelöscht wird. Die Wiederherstellung lädt die Dateien herunter und prüft sie. Bitte
  lösche dort keine einzelnen Fotos von Hand – jeder Export, der auf sie verweist, würde sie verlieren.

Jeder Upload wird mit Googles eigener SHA-256 geprüft; der freie Speicherplatz wird vor dem Upload geprüft.
Datenschutzerklärung: <https://machetso.github.io/my-smartphone-media-backup/privacy.html>

Builds aus dem Quellcode brauchen den Google-Schlüssel der App: `python3 tools/set_google_key.py client_secret_….json`
(schreibt die von git ignorierte `phonebackup/_gkey.py`); Release-Builds bekommen ihn aus den GitHub-Secrets.

## Einstellungen

Gespeichert in `~/.config/phonebackup/config.json` (Windows: `%APPDATA%\PhoneBackup\config.json`):
Name des Besitzers, Telefonordner (Standard `DCIM/Camera`, weitere lassen sich im Programm auswählen),
Laufwerke, adb-Pfad.

## Tests

```
python3 -m unittest discover tests
```

## Getestet

* Linux (Pop!_OS) mit einem Google Pixel 10 Pro (Android 17) per ADB über USB 3:
  1372 Dateien / 20 GB gleichzeitig auf zwei externe HDDs gesichert und geprüft, etwa 24 MB/s.
* Samsung Galaxy S20 FE über USB (ADB) und über Wi-Fi mit der Telefon-App 0.3.3:
  12,4 MB/s über Wi-Fi, keine Fehler; Update der Telefon-App über das Kabel mit der Installationsfrage.
* Google Drive: Kopie und Großvater-Vater-Sohn mit einem 20-GB-Backup (1381 Dateien, etwa
  4 MB/s Upload), Verknüpfungen, Aufräumen und Wiederherstellung geprüft.
* Noch nicht auf echter Hardware getestet: der MTP-Ausweichweg (Linux gvfs, Windows Explorer) und Windows allgemein.

## Lizenz

MIT – siehe [LICENSE](LICENSE).
