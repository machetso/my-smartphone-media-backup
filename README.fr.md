# My Smartphone Media Backup

Sauvegarde vérifiée et incrémentielle des photos et vidéos d’un téléphone Android vers un ou plusieurs
disques externes, triées par année et par mois, avec un rapport après chaque passage.
Python 3.8+, fonctionne sous Linux et Windows. L’interface graphique nécessite PySide6 ; la version
en ligne de commande ne nécessite aucun paquet supplémentaire.

## Téléchargement

Des programmes prêts à l’emploi pour Linux et Windows se trouvent sur la
[page des versions](../../releases) - aucune installation de Python n’est nécessaire.
Windows : télécharge `My-Smartphone-Media-Backup-v….exe` et double-clique dessus (ou le `.zip` avec
le README et la licence) ; Linux : le `.tar.gz`.
Consulte [CHANGELOG.md](CHANGELOG.md) pour voir les nouveautés.

**Mises à jour :** au démarrage, le programme vérifie si une version plus récente est disponible (une fois par jour ; peut être
désactivé dans les Paramètres) et propose **Mettre à jour maintenant** ou **Pas maintenant**. *Mettre à jour maintenant* télécharge la nouvelle
version, vérifie qu’elle est signée avec la clé de publication du projet, remplace le programme et le redémarre
– les paramètres, disques, téléphones et associations sont conservés. Si la nouvelle version ne démarre pas, l’ancienne est
automatiquement remise en place. (Si tu l’as démarré depuis le code source : mets à jour avec `git pull` à la place.)

**Publier une version (mainteneur) :** pousser le tag → GitHub Actions construit le brouillon de version →
`python3 tools/sign_release.py sign vX.Y.Z` sur l’ordinateur du mainteneur (ajoute le fichier signé
`update-manifest.json` ; la clé privée ne va jamais sur GitHub) → publier la version.

## Démarrer depuis le code source

**Interface graphique** (nécessite PySide6) :

```
./start-linux.sh                   # Linux (uses the project's .venv, PySide6 is already installed there)
start-windows.pyw                 # Windows: double-click (after: py -m pip install PySide6)
```

**Écran d’accueil :** **Tes téléphones** – une entrée par sauvegarde (p. ex. *Sam's Pixel 10 Pro*,
*Kim's Galaxy A55*) avec la date de sa dernière sauvegarde et son propre bouton **Mettre à jour la sauvegarde**,
activé lorsque exactement ce téléphone et l’un de ses disques sont connectés (mêmes dossiers et disques,
seulement les nouvelles photos et vidéos). Les sauvegardes faites avant l’existence de cette liste sont retrouvées sur les
disques connectés. *Tout sélectionner* / *Retirer de la liste* masquent des téléphones (leurs sauvegardes restent sur les disques). En dessous :
**Nouvelle sauvegarde…** (un autre téléphone, ou d’autres dossiers / disques), **Paramètres de sauvegarde…** et
**Gérer les sauvegardes…** (les onglets ci-dessous).

**☰ Menu** (en haut à droite de l’écran d’accueil, dès le tout premier démarrage) : **Langue**, **Manuel** (ce texte, dans la langue choisie), **Paramètres du programme…** et **À propos**.

**Paramètres de sauvegarde** (sous-page) :

* **Connexion du téléphone** – le programme **utilise toujours la connexion la plus rapide qu’il trouve** ; tu n’as pas
  à en choisir une. L’aperçu affiche la vitesse de chaque mode de connexion, celui utilisé est marqué, et
  le journal indique s’il s’agit du plus rapide et ce qui serait plus rapide. Si le téléphone apparaît avec le débogage
  USB sur le câble alors qu’il est connecté par Wi-Fi, le programme passe de lui-même au câble.
  **Trouver la connexion la plus rapide** vérifie le câble, le Wi-Fi et le Bluetooth et affiche
  ce qui est disponible.

  **Vue simple :** seulement l’état de la connexion et, quand c’est utile, un conseil en dessous.
  Un téléphone sans sauvegarde : le conseil propose le câble USB avec le débogage USB (la première
  sauvegarde copie toutes les photos et vidéos). Un téléphone sur le câble sans débogage USB, ou
  connecté par Wi-Fi / transfert de fichiers : le conseil indique combien le débogage USB est plus
  rapide – *Comment activer le débogage USB…* ouvre le guide pas à pas (voir ci-dessous),
  *Continuer sans (transfert de fichiers plus lent)* utilise le transfert de fichiers normal du
  téléphone. Coche **Paramètres de connexion avancés** pour voir l’aperçu des vitesses, tous les
  boutons de connexion et *Désactiver … après la sauvegarde*.

  | Connexion | Vitesse |
  |---|---|
  | Câble USB + débogage USB (activé par l’app du téléphone, ou à la main) | 45–50 MB/s (USB 3), ~20–30 MB/s (USB 2) |
  | Câble USB, transfert de fichiers normal (MTP – seulement sur demande) | 10–20 MB/s |
  | Wi-Fi : app du téléphone ou débogage sans fil | 10–40 MB/s, selon le Wi-Fi |
  | Wi-Fi directement vers cet ordinateur (sans routeur) | 10–30 MB/s |

  *Activer le débogage USB (première fois)…* est un guide pas à pas : il lit le modèle du
  téléphone branché sur le câble (fonctionne avant que le débogage USB soit activé), contient les étapes pour Pixel, Samsung,
  Xiaomi / Redmi / POCO, OnePlus / OPPO / realme, Motorola, Huawei / Honor, Sony et Nothing, et
  *Rechercher ce téléphone sur le web* pour tous les autres. Android exige de le faire une fois à la main – aucun programme
  ne peut activer le débogage USB avant cela.
  **L’app du téléphone s’en charge :** lors de la première connexion avec débogage USB, le programme propose d’installer
  l’app du téléphone *My Media Backup* et de lui donner le droit d’activer le débogage USB (l’autorisation Android
  `WRITE_SECURE_SETTINGS`, accordée par le câble – l’app ne peut pas l’obtenir seule). À partir de là :
  ouvre l’app → **Autoriser la sauvegarde par câble** → branche le câble. Après chaque sauvegarde, l’ordinateur
  désactive à nouveau le débogage USB (ou le débogage sans fil) (*Désactiver … après la sauvegarde*, activé
  par défaut). Seul le débogage USB est désactivé ; les options pour les développeurs restent.

  **Règles de désactivation du débogage** (l’app du téléphone les applique même si l’ordinateur a disparu) :
  1. Les sauvegardes par Wi-Fi passent normalement par l’app du téléphone avec le débogage désactivé ; le débogage sans fil
     seulement pour les téléphones sans l’app.
  2. Une seule connexion par sauvegarde : par câble → le débogage sans fil est désactivé au démarrage ;
     via l’app par Wi-Fi → le débogage USB est désactivé au démarrage.
  3. L’app du téléphone n’active jamais le débogage sans fil.
  4. 5 minutes après *Autoriser la sauvegarde par câble* sans démarrage de sauvegarde → désactivé (compte à rebours sur le téléphone).
  5. Pendant une sauvegarde, l’ordinateur dit « toujours là » toutes les 30 s ; rien pendant 2 minutes → désactivé.
  6. Juste après la sauvegarde, l’ordinateur le désactive (et met fin au mode sauvegarde sur le téléphone).

  **Reconnaître le téléphone en toute sécurité :** lors de l’association, l’app du téléphone crée une clé dans la puce de
  sécurité du téléphone ; l’ordinateur enregistre son empreinte. Le modèle, le numéro de série ou les noms ne sont jamais
  considérés comme fiables – chaque connexion vérifie cette clé (TLS avec le certificat épinglé) avant que le
  secret de l’ordinateur soit envoyé.
  * **Câble :** pendant que l’app tourne, l’ordinateur la joint par le câble (`adb forward`) et
    vérifie la clé – l’état affiche alors *vérifié*. La première fois : l’ordinateur installe l’app,
    l’ouvre et demande l’association par le câble ; tu appuies sur **Associer** sur le téléphone (aucun code nécessaire, le
    câble sert de preuve).
  * **Wi-Fi :** l’app s’annonce de façon anonyme : un nom aléatoire et un code qui change toutes les
    10 minutes, que seul un ordinateur associé peut reconnaître (HMAC du secret d’association). Les inconnus
    sur le même réseau ne peuvent pas voir de quel téléphone il s’agit ni le suivre.
  * **Bluetooth (dernier recours, uniquement pour trouver le téléphone) :** le même code changeant plus l’adresse
    Wi-Fi du téléphone (chiffrée) dans un signal Bluetooth LE. Si l’ordinateur peut joindre cette adresse, il
    se connecte par Wi-Fi ; sinon il l’indique. **Aucun fichier n’est jamais envoyé par Bluetooth.**
    Nécessite le paquet Python `bleak` (dans requirements.txt) et l’autorisation « Appareils à proximité »
    du téléphone.
* **Dossiers du téléphone** – **Appareil photo** ajoute le dossier standard de l’appareil photo Android `DCIM/Camera` ;
  *Choisir des dossiers…* liste les dossiers du téléphone (captures d’écran `Pictures/Screenshots`, Samsung
  `DCIM/Screenshots`, WhatsApp `Android/media/com.whatsapp/WhatsApp/Media`, `Movies`, `Download`
  …) ou te permet d’en saisir un (*Tout sélectionner* / *Tout désélectionner*) ; *Retirer*.
  **Conserver la structure des dossiers du téléphone** (option) : les fichiers provenant d’autres dossiers que le dossier
  de l’appareil photo atterrissent dans les mêmes dossiers dans la sauvegarde, p. ex. `Pixel 10 Pro - Sam/Pictures/Screenshots/` ;
  le dossier de l’appareil photo est toujours trié en dossiers année/mois. Les fichiers déjà sauvegardés restent
  là où ils sont ; les fichiers identiques ne sont toujours stockés qu’une seule fois.
* **Destinations de sauvegarde** – la liste des disques de destination ; les noms de dossier longs peuvent défiler
  horizontalement (nom complet en info-bulle).
  Coche-en un ou plusieurs. *Ajouter un disque…* liste les disques externes connectés, y compris
  ceux qui sont branchés mais pas encore montés (Linux : ils sont montés en un clic, sans mot de
  passe). *Ajouter un dossier…* ouvre un sélecteur de dossier. Un disque coché qui est branché
  mais pas monté est monté automatiquement au démarrage de la sauvegarde. Un aperçu montre
  exactement où les fichiers iront. Le téléphone est détecté automatiquement dès qu’il est branché
  via ADB. La liste n’affiche que les disques déjà utilisés avec ce téléphone (et ce
  propriétaire), déjà cochés ; un téléphone sans sauvegarde commence avec une liste vide. *Ajouter
  un disque…* propose aussi les dossiers de sauvegarde utilisés avec d’autres téléphones.

**Jamais le mauvais téléphone.** Chaque dossier de sauvegarde mémorise son téléphone dans `.phonebackup/phone.json`
(modèle, numéro de série du téléphone, identifiant de clé de l’app du téléphone ; pour les sauvegardes plus anciennes, le programme les lit
dans les rapports). Quand tu cliques sur *Démarrer la sauvegarde*, le téléphone connecté est identifié en direct et
comparé : un numéro de série ou une clé différents → **refusé, rien n’est copié**. Si seul le modèle peut être
comparé, ou si le modèle ne correspond pas au nom de la sauvegarde, tu dois confirmer. Juste avant le
premier fichier, le téléphone est identifié une seconde fois (un téléphone échangé arrête la sauvegarde). Un téléphone qui
se connecte ne remplace jamais le nom de smartphone que tu as défini, et tant qu’un téléphone est sur le câble USB, aucun
autre téléphone n’est pris par Wi-Fi. La confirmation affiche la connexion et, si ce n’est pas la plus
rapide, comment la rendre plus rapide (câble + débogage USB ; câble USB 3 au lieu d’USB 2).

**Gérer les sauvegardes…** comporte quatre onglets :

* **Importer une ancienne sauvegarde** – deux possibilités :
  * *Ajouter à une sauvegarde existante* – ajoute d’anciennes sauvegardes ou n’importe quels dossiers (photos et vidéos mélangées, RAW,
    dossiers imbriqués, doublons) à l’une de tes sauvegardes, triés dans les mêmes dossiers année/mois.
  * *Nouvelle sauvegarde d’un ancien téléphone* – l’ancien téléphone reçoit sa propre sauvegarde (« Galaxy S7 - Sam ») :
    saisis le nom du téléphone et le propriétaire, et coche le ou les disques de destination.

  Ajoute un ou plusieurs dossiers (p. ex. la copie de l’ancien téléphone et de sa carte SD) et clique sur
  *Choisir les dossiers à importer…* : chaque dossier contenant des fichiers est listé avec ses photos / vidéos /
  autres fichiers ; les données d’apps, caches, miniatures, corbeilles et dossiers cachés sont exclus. Coche les
  dossiers et choisis pour chacun *Appareil photo* (→ dossiers année/mois) ou *Autre* (→ conserve son
  dossier d’origine sous `Year/other/pictures | movies | other-files/`). Pour un ancien téléphone, les
  dossiers de l’appareil photo et les dossiers normaux d’images/vidéos/téléchargements sont pré-cochés, les dossiers de messagerie et de
  captures d’écran ne le sont pas. Chaque fichier est haché à la source et vérifié après écriture,
  les fichiers identiques ne sont stockés qu’une seule fois (y compris par rapport à ce qui est déjà dans la sauvegarde), les anciens
  dossiers sont seulement lus. Les fichiers ignorés sont listés dans le rapport « Import <nom> <date> ».
* **Second stockage (export)** – choisis la sauvegarde, un second disque ou **Google Drive** et le type
  d’export (*Automatique – Grand-père-Père-Fils* par défaut). Les exports précédents sont listés ; les anciens peuvent
  être nettoyés (seulement après ta confirmation). Voir *Second stockage* ci-dessous.
* **Restaurer** – choisis le jeu d’export (sur un disque ou sur Google Drive), l’état et le dossier
  cible.
* **Paramètres** – chemin d’adb (normalement vide = trouvé automatiquement), temps d’attente, fsync, garder
  l’ordinateur éveillé. Survole un paramètre pour obtenir une explication.

**Pourquoi ADB ?** ADB (Android Debug Bridge, l’outil USB de Google pour Android) est la méthode rapide et sûre :
environ 45–50 MB/s par un câble USB 3 (mesuré avec un Pixel 10 Pro), alors que MTP - le mode normal
de « transfert de fichiers » - atteint généralement 10–20 MB/s. Avec ADB, chaque fichier est en plus vérifié avec
SHA-256 sur le téléphone lui-même. Si ADB ne fonctionne pas, l’app se rabat sur MTP et l’indique.

**Garder l’ordinateur éveillé :** pendant une sauvegarde, un import, un export ou une restauration, l’ordinateur est
empêché de se mettre en veille (activé par défaut, désactivable sous *Paramètres*). Les paramètres d’alimentation
eux-mêmes ne sont pas modifiés – le blocage prend fin automatiquement avec la tâche, même après un plantage.
Linux : la veille, la mise en veille pour inactivité, la fermeture du capot et un arrêt normal sont bloqués (inhibiteur
logind), et le minuteur d’inactivité du bureau est mis en pause (inhibition D-Bus `org.freedesktop.ScreenSaver`,
comme le fait un lecteur vidéo - nécessaire sur COSMIC et d’autres bureaux qui se mettent en veille d’eux-mêmes
après une période d’inactivité). Pendant qu’une tâche tourne, l’écran reste donc allumé.
Windows : la mise en veille pour inactivité est empêchée et Windows demande confirmation avant de s’éteindre ;
la fermeture du capot et le bouton d’alimentation suivent toujours les paramètres d’alimentation de Windows.

**Icône de bureau (Linux) :** `./install-linux-desktop.sh` place une icône de démarrage sur le bureau et dans
le menu des applications (relance-le après avoir déplacé le dossier, `--remove` la supprime à nouveau).
Les icônes sont générées à partir de `assets/PhoneBKP_Logo.webp` avec `.venv/bin/python tools/make_icons.py`.

La barre de progression, la vitesse, le temps restant et le journal se trouvent en bas, avec *Annuler* (s’arrête
après le fichier en cours), *Ouvrir le rapport* et *Ouvrir le dossier de sauvegarde*.

**Version en ligne de commande** (aucun paquet supplémentaire) : `python3 smartphone_media_backup.py --cli`
ou directement `smartphone_media_backup.py backup | export | restore | settings`.
Si PySide6 est absent, `smartphone_media_backup.py` démarre automatiquement la version en ligne de commande.

## Résultat sur le disque

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

* Nom du dossier du mois = année + mois : `26.02` est février 2026. Les sauvegardes des versions
  précédentes (`02.February-photos` / `02.February-videos`) sont converties avant la prochaine
  sauvegarde ou exportation – le programme affiche d’abord les anciens dossiers de mois et vous
  décochez ceux qui doivent **garder leur nom et leur structure** (ils ne sont jamais modifiés). Le
  choix vaut pour chaque disque et pour Google Drive ; les fichiers sont seulement déplacés, jamais
  supprimés. Vos propres dossiers ne sont jamais touchés.
* Les dossiers d’année et de mois ne sont créés que lorsqu’un fichier y est placé - pas de dossiers vides.
* Mois = date de prise de vue issue des métadonnées de la photo/vidéo → sinon le nom de fichier
  (`PXL_20261102_…`) → sinon la date du fichier.
* Les photos animées (`*.MP.jpg`), HEIC, PNG, … comptent comme des photos ; les DNG et autres fichiers RAW vont dans `raw/`.
* Un second rapport le même jour reçoit l’heure en plus dans son nom.
* Rien n’est jamais supprimé : ni sur le téléphone, ni dans la sauvegarde.
* Même nom mais contenu différent → le nouveau fichier est enregistré sous `name_1.jpg`. Un contenu identique
  n’est stocké qu’une seule fois.

## Sécurité

* **Téléphone → ordinateur :** avec ADB, le téléphone calcule lui-même le SHA-256, qui est comparé
  avec les données reçues. Avec MTP, ce n’est pas possible, et le rapport l’indique.
* **Ordinateur → disque :** chaque copie est forcée sur le disque, relue et son SHA-256 comparé.
* Les fichiers sont écrits comme fichiers temporaires et ne sont renommés qu’après la vérification. Une sauvegarde interrompue
  ne laisse jamais de fichiers à moitié écrits ; le passage suivant continue simplement.
* Deux disques (ou plus) sont écrits **en même temps**. Le téléphone n’est lu qu’une seule fois.
* L’espace libre est vérifié d’abord. Si un disque tombe en panne ou est plein, la sauvegarde continue sur
  l’autre disque et le rapport l’affiche en rouge.

## Configuration d’ADB (une fois). Le téléphone est ainsi utilisable en ~2 secondes au lieu d’attendre MTP

**Sur le téléphone**

1. Paramètres → À propos du téléphone → appuie 7× sur *Numéro de build* (mode développeur activé).
2. Paramètres → Système → Options pour les développeurs → active le **Débogage USB**.
3. Connecte le téléphone, déverrouille-le et confirme *Autoriser le débogage USB* avec
   **Toujours autoriser cet ordinateur**.

**Linux (Pop!_OS / Ubuntu)**

```
sudo apt install adb
adb devices          # should show your phone as "device"
```

**Le plus simple (Windows et Linux) :** *Paramètres → Télécharger ADB…* récupère les platform-tools officiels de Google
directement chez Google dans le dossier propre à l’app (Windows :
`%LOCALAPPDATA%\phonebackup\platform-tools`, Linux : `~/.local/share/phonebackup/platform-tools`)
et définit le chemin - sans installation, sans droits d’administrateur. adb n’est pas fourni avec l’app car
la licence de Google ne permet pas de le redistribuer.

**Windows (à la main)**

1. Télécharge *SDK Platform-Tools for Windows* depuis
   https://developer.android.com/tools/releases/platform-tools
2. Décompresse-le de sorte que le dossier `platform-tools` se trouve **à côté de `smartphone_media_backup.py`** (trouvé automatiquement),
   ou saisis le chemin vers `adb.exe` sous *Paramètres*.
3. Google Pixel : si le téléphone n’est pas trouvé, installe le *Google USB Driver*.

Si ADB ne fonctionne pas, le programme affiche un avertissement clair et passe au **repli MTP** :

* Linux : le téléphone est monté automatiquement via gvfs/`gio`. Choisis *Transfert de fichiers* dans la
  notification USB du téléphone.
* Windows : nécessite une fois `py -m pip install pywin32`. L’Explorateur copie alors les fichiers.
  C’est lent, et cela n’a pas été testé sur du vrai matériel pendant le développement (voir ci-dessous).

## App du téléphone (Wi-Fi, sans débogage USB)

**Configurer l’app du téléphone…** affiche un code QR. Scanne-le avec l’appareil photo du téléphone : la page (servie par cet
ordinateur) propose **1. Télécharger l’app** (ouvre le fichier, appuie sur *Installer*) et **2. Connecter l’app**.
Le téléphone et l’ordinateur affichent le même code à 6 chiffres - confirme-le **sur le téléphone et sur l’ordinateur**
(le téléphone ne transmet sa clé qu’après ton appui à cet endroit). À faire une seule fois. L’association par le câble USB
fonctionne de la même manière : les deux écrans affichent un code, n’appuie sur *Associer* sur le téléphone que s’ils correspondent.

Par le câble, le programme peut aussi installer l’app lui-même – il **demande toujours d’abord** et
explique quel téléphone, quelle version, pourquoi et ce qui se passe exactement ; rien n’est installé sans
ton clic.

Pour une sauvegarde : ouvre *My Media Backup* sur le téléphone → **Démarrer le mode sauvegarde**. L’ordinateur le trouve et
se connecte ; après la sauvegarde, le téléphone désactive lui-même le mode sauvegarde (aussi après 5 minutes
sans utilisation). L’app peut seulement lire les photos et vidéos ; la connexion est chiffrée (TLS, certificat
épinglé lors de l’association). L’ordinateur **récupère** les fichiers : il demande chaque fichier, le téléphone ne
répond qu’à l’ordinateur associé et n’envoie jamais rien de lui-même. Mêmes fichiers et chemins que par ADB, les sauvegardes existantes continuent donc simplement.

## Sauvegarde par Wi-Fi (sans câble)

Utilise le **débogage sans fil** intégré à Android (Android 11+, aucune app sur le téléphone). Tout
fonctionne comme par USB, y compris la vérification SHA-256 sur le téléphone ; c’est seulement plus lent (selon le
Wi-Fi, généralement 10–40 MB/s).

1. Téléphone : *Paramètres → Système → Options pour les développeurs → Débogage sans fil* → activé (autorise-le pour le
   réseau).
2. App : **Associer par Wi-Fi…** → sur le téléphone, appuie sur *Associer l’appareil avec un code QR* et scanne le code
   (ou utilise *Associer l’appareil avec un code d’association* et saisis les 6 chiffres). Nécessaire une seule fois.
3. À partir de là, le téléphone est trouvé automatiquement dès que le débogage sans fil est activé et que le téléphone et
   l’ordinateur sont sur le même Wi-Fi. Si l’USB et le Wi-Fi sont tous deux disponibles, l’USB est utilisé.

**Pas de routeur ? Wi-Fi direct :** **Wi-Fi direct…** permet à l’ordinateur d’ouvrir son propre réseau Wi-Fi
(Linux : point d’accès NetworkManager, 5 GHz si possible ; Windows : ouvre les paramètres du *Point d’accès mobile*).
Le téléphone s’y connecte (code QR pour l’appareil photo), et la sauvegarde se fait directement entre le
téléphone et l’ordinateur. La plupart des adaptateurs Wi-Fi coupent le Wi-Fi normal pendant ce temps ; il revient lorsque le
Wi-Fi direct est arrêté (l’app le demande quand tu la fermes).

Un vrai Wi-Fi Direct (P2P) nécessiterait une app compagnon sur le téléphone ; c’est prévu pour une étape ultérieure.

## Plan de sauvegarde par disque

Dans la liste des disques de *Nouvelle sauvegarde*, chaque disque de sauvegarde a un **Plan de sauvegarde** :

* **Simple** – un dossier qui grandit, seules les nouvelles photos et vidéos sont ajoutées (comme montré ci-dessus).
* **Grand-père-Père-Fils** – des sauvegardes datées comme sur un second stockage (voir ci-dessous) : une sauvegarde **complète**
  tous les 3 mois, une **différentielle** chaque mois, des **incrémentielles** entre les deux.
  Une sauvegarde complète/différentielle contient aussi les fichiers antérieurs dont elle a besoin (copiés sur le disque et
  vérifiés), de sorte que les photos supprimées du téléphone restent dans chaque sauvegarde complète.

Les deux peuvent être combinés, p. ex. *Simple* sur un disque dur et *Grand-père-Père-Fils* sur l’autre. Un dossier de
téléphone conserve le plan avec lequel il a été commencé.

## Second stockage (export)

*Gérer les sauvegardes → Second stockage* copie une sauvegarde vers un autre disque ou vers Google Drive. Chaque export
reçoit son propre dossier :

```
PhoneBackups-Export/Pixel 10 Pro - Sam/
├── 2026-11-02_14-30-00_full/
├── 2026-11-20_09-12-45_incremental/
├── 2026-12-01_18-03-10_differential/
└── .phonebackup-export/catalog.sqlite
```

| Type          | Copie                                              |
|---------------|----------------------------------------------------|
| complète      | tout                                               |
| différentielle | tout ce qui est nouveau depuis le dernier export **complet** |
| incrémentielle | tout ce qui est nouveau depuis le **dernier** export (tout type) |

**Automatique – Grand-père-Père-Fils** (par défaut) choisit le type : complète tous les 3 mois
(grand-père), différentielle chaque mois (père), incrémentielle entre les deux (fils) ; l’app indique
lequel vient ensuite et pourquoi. Elle conserve les 4 exports complets, 3 différentiels et 6 incrémentiels
les plus récents ainsi que tout ce dont ils ont besoin pour une restauration ; les plus anciens sont proposés à la suppression et supprimés
**seulement après ta confirmation** (*Nettoyer les anciens exports…*).

Chaque fichier exporté est vérifié par rapport au SHA-256 enregistré au moment de la sauvegarde. Un fichier qui a été
endommagé sur le premier disque (dégradation des données) est signalé par un ATTENTION.
*Restaurer* reconstruit un dossier complet à partir de la chaîne la plus courte (complète + différentielle la plus récente +
incrémentielles qui la suivent) et vérifie chaque fichier.

### Google Drive

*Ajouter au stockage cloud → Google Drive* te connecte via le navigateur. L’app ne peut voir que les
fichiers qu’elle a elle-même envoyés (le droit `drive.file` de Google) ; la connexion reste sur cet ordinateur.
Deux types d’export :

* **Copie** – un miroir de la sauvegarde dans *My Drive/My Smartphone Media Backup/Phone - Owner* :
  seuls les nouveaux fichiers sont envoyés, rien n’est supprimé ni écrasé.
* **Grand-père-Père-Fils** dans *Phone - Owner (Grandfather-Father-Son)* : chaque photo n’est stockée
  qu’**une seule fois** – les exports complets et différentiels pointent vers des fichiers déjà présents sur Google Drive
  (raccourcis, sans espace supplémentaire ; y compris vers la Copie). Le nettoyage déplace les fichiers encore utilisés par des exports plus récents
  dans ceux-ci avant de supprimer quoi que ce soit. La restauration télécharge les fichiers et les vérifie. Merci
  de ne pas y supprimer de photos isolées à la main – chaque export qui pointe vers elles les perdrait.

Chaque envoi est vérifié par rapport au SHA-256 propre à Google ; l’espace libre est vérifié avant l’envoi.
Politique de confidentialité : <https://machetso.github.io/my-smartphone-media-backup/privacy.html>

Les builds depuis le code source nécessitent la clé Google de l’app : `python3 tools/set_google_key.py client_secret_….json`
(écrit le fichier `phonebackup/_gkey.py` ignoré par git) ; les builds de publication la reçoivent des secrets GitHub.

## Paramètres

Enregistrés dans `~/.config/phonebackup/config.json` (Windows : `%APPDATA%\PhoneBackup\config.json`) :
nom du propriétaire, dossiers du téléphone (par défaut `DCIM/Camera`, d’autres peuvent être sélectionnés dans le programme),
disques, chemin d’adb.

## Tests

```
python3 -m unittest discover tests
```

## Testé

* Linux (Pop!_OS) avec un Google Pixel 10 Pro (Android 17) via ADB en USB 3 :
  1372 fichiers / 20 Go sauvegardés simultanément sur deux disques durs externes et vérifiés, environ 24 MB/s.
* Samsung Galaxy S20 FE par USB (ADB) et par Wi-Fi avec l’app du téléphone 0.3.3 :
  12,4 MB/s par Wi-Fi, sans erreur ; mise à jour de l’app du téléphone par le câble avec la question d’installation.
* Google Drive : Copie et Grand-père-Père-Fils avec une sauvegarde de 20 Go (1381 fichiers, environ
  4 MB/s en envoi), raccourcis, nettoyage et restauration vérifiés.
* Pas encore testé sur du vrai matériel : le repli MTP (Linux gvfs, Explorateur Windows) et Windows en général.

## Licence

MIT – voir [LICENSE](LICENSE).
