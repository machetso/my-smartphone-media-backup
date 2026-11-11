# My Smartphone Media Backup

Copia de seguridad incremental y verificada de fotos y vídeos de un teléfono Android en una o
varias unidades externas, ordenada por año y mes, con un informe después de cada ejecución.
Python 3.8+, funciona en Linux y Windows. La interfaz gráfica necesita PySide6; la versión de
terminal no necesita paquetes adicionales.

## Descarga

Los programas listos para usar en Linux y Windows están en la
[página de versiones (Releases)](../../releases), sin necesidad de instalar Python.
Windows: descarga `My-Smartphone-Media-Backup-v….exe` y haz doble clic en él (o el `.zip` con el
README y la licencia); Linux: el `.tar.gz`.
Consulta [CHANGELOG.md](CHANGELOG.md) para ver las novedades.

**Actualizaciones:** al iniciarse, el programa comprueba si hay una versión más nueva (una vez al
día; se puede desactivar en Ajustes) y ofrece **Actualizar ahora** o **Ahora no**. *Actualizar ahora*
descarga la nueva versión, comprueba que está firmada con la clave de versiones del proyecto,
sustituye el programa y lo reinicia; los ajustes, las unidades, los teléfonos y los emparejamientos
se conservan. Si la nueva versión no arranca, la anterior se restablece automáticamente. (Si lo
iniciaste desde el código fuente, actualiza con `git pull`).

**Publicar una versión (mantenedor):** sube la etiqueta (tag) → GitHub Actions crea el borrador de
la versión → `python3 tools/sign_release.py sign vX.Y.Z` en el equipo del mantenedor (añade el
`update-manifest.json` firmado; la clave privada nunca va a GitHub) → publica la versión.

## Iniciar desde el código fuente

**Interfaz gráfica** (necesita PySide6):

```
./start-linux.sh                   # Linux (uses the project's .venv, PySide6 is already installed there)
start-windows.pyw                 # Windows: double-click (after: py -m pip install PySide6)
```

**Pantalla de inicio:** **Tus teléfonos**: una entrada por copia (p. ej. *Sam's Pixel 10 Pro*,
*Kim's Galaxy A55*) con la fecha de su última copia y su propio botón **Actualizar copia**,
que se activa cuando están conectados exactamente ese teléfono y una de sus unidades (mismas
carpetas y unidades, solo fotos y vídeos nuevos). Las copias hechas antes de que existiera esta
lista se encuentran en las unidades conectadas. *Seleccionar todo* / *Quitar de la lista* ocultan
teléfonos (sus copias se quedan en las unidades). Debajo: **Nueva copia…** (otro teléfono, u otras
carpetas / unidades), **Ajustes de copia** (botón con el engranaje) y **Gestionar copias…** (las
pestañas que se describen más abajo).

**☰ Menú** (arriba a la derecha en la pantalla de inicio, desde el primer arranque): **Idioma**, **Manual** (este texto, en el idioma elegido), **Ajustes del programa…** y **Acerca de**.

**Ajustes de copia** (subpágina):

* **Conexión del teléfono**: el programa **siempre usa la conexión más rápida que encuentra**; tú
  no eliges ninguna. El resumen muestra la velocidad de cada forma de conexión, la que está en uso
  aparece marcada y el registro indica si es la más rápida y qué sería más rápido. Si el teléfono
  aparece con la depuración por USB en el cable mientras está conectado por Wi-Fi, el programa
  cambia al cable por sí solo. **Buscar la conexión más rápida** comprueba el cable, el Wi-Fi y el
  Bluetooth y muestra lo que está disponible.

  **Vista sencilla:** solo el estado de la conexión y, cuando ayuda, un consejo debajo. Un
  teléfono sin copia todavía: el consejo propone el cable USB con depuración USB (la primera copia
  copia todas las fotos y vídeos). Un teléfono en el cable sin depuración USB, o conectado por
  Wi-Fi / transferencia de archivos: el consejo dice cuánto más rápida es la depuración USB –
  *Cómo activar la depuración USB…* abre la guía paso a paso (ver abajo), *Continuar sin ella
  (transferencia de archivos más lenta)* usa la transferencia de archivos normal del móvil. Marca
  **Ajustes avanzados de conexión** para ver el resumen de velocidades, todos los botones de
  conexión y *Desactivar … después de la copia*.

  | Conexión | Velocidad |
  |---|---|
  | Cable USB + depuración por USB (activada por la app del teléfono, o a mano) | 45–50 MB/s (USB 3), ~20–30 MB/s (USB 2) |
  | Cable USB, transferencia de archivos normal (MTP, solo si se solicita) | 10–20 MB/s |
  | Wi-Fi: app del teléfono o Depuración inalámbrica | 10–40 MB/s, depende del Wi-Fi |
  | Wi-Fi directamente a este equipo (sin router) | 10–30 MB/s |

  *Activar la depuración por USB (primera vez)…* es una guía paso a paso: lee el modelo del
  teléfono conectado al cable (funciona antes de activar la depuración por USB), incluye los pasos
  para Pixel, Samsung, Xiaomi / Redmi / POCO, OnePlus / OPPO / realme, Motorola, Huawei / Honor,
  Sony y Nothing, y *Buscar en la web para este teléfono* para cualquier otro. Android exige hacer
  esto una vez a mano: ningún programa puede activar la depuración por USB antes de eso.
  **La app del teléfono la activa:** en la primera conexión con depuración por USB, el programa
  ofrece instalar la app del teléfono *My Media Backup* y darle permiso para activar la depuración
  por USB (`WRITE_SECURE_SETTINGS` de Android, concedido por el cable; la app no puede obtenerlo
  por sí misma). A partir de ahí: abre la app → **Permitir copia por cable** → conecta el cable.
  Después de cada copia, el equipo vuelve a desactivar la depuración por USB (o la Depuración
  inalámbrica) (*Desactivar … después de la copia*, activado por defecto). Solo se desactiva la
  depuración por USB; las Opciones para desarrolladores se mantienen.

  **Reglas para desactivar la depuración** (la app del teléfono las aplica aunque el equipo ya no esté):
  1. Las copias por Wi-Fi se hacen normalmente a través de la app del teléfono con la depuración
     desactivada; la Depuración inalámbrica solo para teléfonos sin la app.
  2. Una conexión por copia: por cable → la Depuración inalámbrica se desactiva al empezar;
     mediante la app por Wi-Fi → la depuración por USB se desactiva al empezar.
  3. La app del teléfono nunca activa la Depuración inalámbrica.
  4. 5 minutos después de *Permitir copia por cable* sin que empiece una copia → se desactiva (cuenta atrás en el teléfono).
  5. Durante una copia, el equipo dice "sigo aquí" cada 30 s; si no hay nada durante 2 minutos → se desactiva.
  6. Justo después de la copia, el equipo la desactiva (y termina el modo de copia en el teléfono).

  **Reconocer el teléfono de forma segura:** al emparejar, la app del teléfono crea una clave en el
  chip de seguridad del teléfono; el equipo guarda su huella digital. Nunca se confía en el modelo,
  el número de serie ni los nombres: cada conexión comprueba esa clave (TLS con el certificado
  fijado) antes de enviar el secreto del equipo.
  * **Cable:** mientras la app está abierta, el equipo la alcanza por el cable (`adb forward`) y
    comprueba la clave; el estado indica entonces *verificado*. La primera vez: el equipo instala la
    app, la abre y pide emparejar por el cable; tú tocas **Emparejar** en el teléfono (no hace falta
    código, el cable es la prueba).
  * **Wi-Fi:** la app se anuncia de forma anónima: un nombre aleatorio y un código que cambia cada
    10 minutos, que solo un equipo emparejado puede reconocer (HMAC del secreto de emparejamiento).
    Los desconocidos en la misma red no pueden ver qué teléfono es ni seguirlo.
  * **Bluetooth (último recurso, solo para encontrar el teléfono):** el mismo código cambiante más
    la dirección Wi-Fi del teléfono (cifrada) en una señal Bluetooth LE. Si el equipo puede alcanzar
    esa dirección, se conecta por Wi-Fi; si no, lo indica. **Nunca se envían archivos por Bluetooth.**
    Necesita el paquete de Python `bleak` (en requirements.txt) y el permiso "Dispositivos cercanos"
    del teléfono.
* **Carpetas del teléfono**: **Cámara** añade la carpeta de cámara estándar de Android `DCIM/Camera`;
  *Elegir carpetas…* muestra las carpetas del teléfono (capturas de pantalla `Pictures/Screenshots`,
  Samsung `DCIM/Screenshots`, WhatsApp `Android/media/com.whatsapp/WhatsApp/Media`, `Movies`,
  `Download` …) o te permite escribir una (*Seleccionar todo* / *No seleccionar nada*); *Quitar*.
  **Mantener la estructura de carpetas del teléfono** (opción): los archivos de carpetas distintas
  de la carpeta de cámara van a las mismas carpetas en la copia, p. ej.
  `Sam/Pixel 10 Pro/Pictures/Screenshots/`; la carpeta de cámara siempre se ordena en carpetas
  de año/mes. Los archivos que ya están copiados se quedan donde están; los archivos idénticos se
  siguen guardando una sola vez.
* **Destinos de la copia**: la lista de unidades de destino; los nombres de carpeta largos se pueden
  desplazar lateralmente (el nombre completo aparece como información emergente).
  Marca una o varias. *Añadir unidad…* muestra las unidades externas conectadas, incluidas las que
  están enchufadas pero aún no montadas (Linux: se montan con un clic, sin contraseña). *Añadir
  carpeta…* abre un selector de carpetas. Una unidad marcada que está enchufada pero no montada se
  monta automáticamente al empezar la copia. Una vista previa muestra exactamente adónde irán los
  archivos. El teléfono se detecta automáticamente en cuanto se conecta por ADB. La lista muestra
  solo las unidades usadas antes con este teléfono (y propietario), ya marcadas; un teléfono sin
  copia empieza con la lista vacía. *Añadir unidad…* también ofrece las carpetas de copia usadas
  antes con otros teléfonos.

**Nunca el teléfono equivocado.** Cada carpeta de copia recuerda su teléfono en `.phonebackup/phone.json`
(modelo, número de serie del teléfono, id de la clave de la app del teléfono; en copias más antiguas
el programa los lee de los informes). Al hacer clic en *Iniciar copia*, el teléfono conectado se
identifica en ese momento y se compara: un número de serie o una clave distintos → **rechazado, no se
copia nada**. Si solo se puede comparar el modelo, o el modelo no coincide con el nombre de la copia,
tienes que confirmarlo. Justo antes del primer archivo, el teléfono se identifica una segunda vez (un
teléfono cambiado detiene la copia). Un teléfono que se conecta nunca sustituye el nombre de smartphone
que has puesto, y mientras haya un teléfono en el cable USB no se toma ningún otro teléfono por Wi-Fi.
La confirmación muestra la conexión y, si no es la más rápida, cómo hacerla más rápida (cable +
depuración por USB; cable USB 3 en lugar de USB 2).

**Gestionar copias…** tiene cuatro pestañas:

* **Disco antiguo / teléfono antiguo**: copia las fotos y los vídeos de un disco duro antiguo o de un
  teléfono antiguo como si fuera la copia de un teléfono. Dos formas:
  * *Añadir a una copia existente*: añade copias antiguas o cualquier carpeta (fotos, vídeos y RAW
    mezclados, carpetas anidadas, duplicados) a una de tus copias.
  * *Nueva copia (teléfono o disco antiguo)*: recibe su propia copia (p. ej. “Galaxy S7 - Sam” u
    “Old drive - Sam”): introduce un nombre y el propietario y marca la(s) unidad(es) de destino.

  Añade una o varias carpetas (p. ej. la copia del teléfono antiguo y de su tarjeta SD, o las carpetas
  de fotos del disco antiguo) y haz clic en *Elegir carpetas que importar…*: se muestra cada carpeta
  con archivos con sus fotos / vídeos / otros archivos; los datos de apps, cachés, miniaturas,
  papelera y carpetas ocultas se omiten. Marca las carpetas y elige para cada una:
  * *Ordenar en carpetas de año/mes*: las fotos y los vídeos se ordenan por fecha exactamente igual
    que en la copia de un teléfono (`2019/19.07`, RAW → `2019/raw/19.07`).
  * *Dejar la carpeta tal como está*: la carpeta se copia 1:1, con su nombre y su ruta, al nivel
    superior de la copia (p. ej. `Urlaub Italien 2019/Tag 1/`). Cada carpeta se importa con sus
    propios archivos; sus subcarpetas son líneas aparte: márcalas también para conservar todo el
    árbol de carpetas.

  En un teléfono antiguo, las carpetas de cámara se proponen para ordenar y las carpetas normales de
  imágenes/películas/descargas para dejarlas tal como están; las de mensajería y capturas de pantalla
  no vienen marcadas. Cada archivo se calcula con hash en el origen y se verifica después de
  escribirlo, los archivos idénticos se guardan una sola vez (también frente a lo que ya está en la
  copia) y las carpetas antiguas solo se leen. Los archivos omitidos se enumeran en el informe
  “Import <name> <date>”. (Las importaciones hechas antes de la versión 0.9.8.3 ponían las carpetas
  conservadas en `Year/other/pictures | movies | other-files/`; allí se quedan.)
* **Segundo almacenamiento (exportación)**: elige la copia, una segunda unidad o **Google Drive** y el
  tipo de exportación (*Automático – Abuelo-Padre-Hijo* por defecto). Las exportaciones anteriores
  aparecen en una lista; las antiguas se pueden limpiar (solo después de que lo confirmes). Consulta
  *Segundo almacenamiento* más abajo.
* **Restaurar**: elige el conjunto de exportación (en una unidad o en Google Drive), el estado y la
  carpeta de destino.
* **Ajustes**: ruta de adb (normalmente vacía = se encuentra automáticamente), tiempo de espera,
  fsync, mantener el equipo activo. Pasa el ratón sobre un ajuste para ver una explicación.

**¿Por qué ADB?** ADB (Android Debug Bridge, la herramienta USB de Google para Android) es la forma
rápida y segura: unos 45–50 MB/s con un cable USB 3 (medido con un Pixel 10 Pro), mientras que MTP,
el modo normal de "transferencia de archivos", suele alcanzar 10–20 MB/s. Con ADB, además, cada
archivo se comprueba con SHA-256 en el propio teléfono. Si ADB no funciona, la app recurre a MTP y
lo indica.

**Mantener el equipo activo:** mientras se ejecuta una copia, importación, exportación o
restauración, se impide que el equipo entre en suspensión (activado por defecto, se desactiva en
*Ajustes*). Los ajustes de energía en sí no se modifican: el bloqueo termina automáticamente con la
tarea, incluso tras un fallo.
Linux: se bloquean la suspensión, la suspensión por inactividad, el cierre de la tapa y un apagado
normal (inhibidor de logind), y se pausa el temporizador de inactividad del propio escritorio (D-Bus
`org.freedesktop.ScreenSaver` inhibit, como hace un reproductor de vídeo; necesario en COSMIC y otros
escritorios que se suspenden solos tras un tiempo de inactividad). Por eso, mientras se ejecuta una
tarea, la pantalla permanece encendida.
Windows: se impide la suspensión por inactividad y Windows pregunta antes de apagarse;
cerrar la tapa y el botón de encendido siguen los ajustes de energía de Windows.

**Icono de escritorio (Linux):** `./install-linux-desktop.sh` pone un icono de inicio en el
escritorio y en el menú de aplicaciones (vuelve a ejecutarlo después de mover la carpeta; `--remove`
lo quita de nuevo).
Los iconos se generan a partir de `assets/PhoneBKP_Logo.webp` con `.venv/bin/python tools/make_icons.py`.

La barra de progreso, la velocidad, el tiempo restante y el registro están en la parte inferior, con
*Cancelar* (se detiene después del archivo actual), *Abrir informe* y *Abrir carpeta de copia*.

**Versión de terminal** (sin paquetes adicionales): `python3 smartphone_media_backup.py --cli`
o directamente `smartphone_media_backup.py backup | export | restore | settings`.
Si falta PySide6, `smartphone_media_backup.py` inicia automáticamente la versión de terminal.

## Resultado en la unidad

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

* Nombre de la carpeta del mes = año + mes: `26.02` es febrero de 2026. Las copias de versiones
  anteriores (`02.February-photos` / `02.February-videos`) se convierten antes de la siguiente
  copia o exportación – antes el programa muestra las carpetas de mes antiguas y desmarcas las que
  deben **conservar su nombre y estructura** (nunca se cambian). La elección vale para cada disco y
  para Google Drive; los archivos solo se mueven, nunca se borran. Tus propias carpetas y las carpetas
  de "mantener la estructura de carpetas" nunca se tocan.
* Las carpetas de año y mes solo se crean cuando un archivo va a parar a ellas: no hay carpetas vacías.
* Mes = fecha de captura de los metadatos de la foto/vídeo → si no, el nombre del archivo
  (`PXL_20261102_…`) → si no, la fecha del archivo.
* Las fotos con movimiento (`*.MP.jpg`), HEIC, PNG, … cuentan como fotos; DNG y otros archivos RAW van a `raw/`.
* Carpeta de copia = propietario / teléfono (`Sam/Pixel 10 Pro`). Las copias de versiones anteriores
  (`Pixel 10 Pro - Sam`) se mueven allí automáticamente; si existen ambas, se unen: no se sobrescribe
  ni se borra nada.
* Los informes (`.txt` / `.html` / `.csv`) y el registro de una tarea que terminó sin informe van a
  la carpeta `Logs`, junto a las carpetas de año. Los informes de versiones anteriores se mueven allí
  automáticamente antes de la siguiente copia, importación o exportación.
* Un segundo informe del mismo día lleva la hora añadida a su nombre.
* Nunca se borra nada: ni en el teléfono ni en la copia.
* Mismo nombre pero contenido distinto → el archivo nuevo se guarda como `name_1.jpg`. El contenido
  idéntico se guarda una sola vez.

## Seguridad

* **Teléfono → equipo:** con ADB, el teléfono calcula el SHA-256 por sí mismo y se compara con los
  datos recibidos. Con MTP esto no es posible, y el informe lo indica.
* **Equipo → unidad:** cada copia se fuerza al disco, se vuelve a leer y se compara su SHA-256.
* Los archivos se escriben como archivos temporales y solo se renombran después de la comprobación.
  Una copia interrumpida nunca deja archivos a medias; la siguiente ejecución simplemente continúa.
* Dos (o más) unidades se escriben **al mismo tiempo**. El teléfono se lee una sola vez.
* Primero se comprueba el espacio libre. Si una unidad falla o se llena, la copia continúa en la
  otra unidad y el informe lo muestra en rojo.

## Configuración de ADB (una vez). Así el teléfono está listo en ~2 segundos en lugar de esperar a MTP

**En el teléfono**

1. Ajustes → Acerca del teléfono → toca 7 veces *Número de compilación* (activa el modo desarrollador).
2. Ajustes → Sistema → Opciones para desarrolladores → activa **Depuración por USB**.
3. Conecta el teléfono, desbloquéalo y confirma *Permitir depuración por USB* con
   **Permitir siempre desde este ordenador**.

**Linux (Pop!_OS / Ubuntu)**

```
sudo apt install adb
adb devices          # should show your phone as "device"
```

**Lo más fácil (Windows y Linux):** *Ajustes → Descargar ADB…* descarga las platform-tools oficiales
de Google directamente desde Google en la carpeta propia de la app (Windows:
`%LOCALAPPDATA%\phonebackup\platform-tools`, Linux: `~/.local/share/phonebackup/platform-tools`)
y configura la ruta, sin instalación y sin derechos de administrador. adb no se incluye con la app
porque la licencia de Google no permite redistribuirlo.

**Windows (a mano)**

1. Descarga *SDK Platform-Tools for Windows* desde
   https://developer.android.com/tools/releases/platform-tools
2. Descomprímelo de forma que la carpeta `platform-tools` quede **junto a `smartphone_media_backup.py`** (se encuentra automáticamente),
   o introduce la ruta a `adb.exe` en *Ajustes*.
3. Google Pixel: si no se encuentra el teléfono, instala el *Google USB Driver*.

Si ADB no funciona, el programa muestra un aviso claro y cambia a la **alternativa MTP**:

* Linux: el teléfono se monta automáticamente mediante gvfs/`gio`. Elige *Transferencia de archivos*
  en la notificación USB del teléfono.
* Windows: necesita `py -m pip install pywin32` una vez. Después, el Explorador copia los archivos.
  Es lento y no se probó en hardware real durante el desarrollo (ver más abajo).

## App del teléfono (Wi-Fi, sin depuración por USB)

**Configurar la app del teléfono…** muestra un código QR. Escanéalo con la cámara del teléfono: la
página (servida por este equipo) ofrece **1. Descargar la app** (abre el archivo, toca *Instalar*) y
**2. Conectar la app con este equipo**. El teléfono y el equipo muestran el mismo código de 6
dígitos: confírmalo **en el teléfono y en el equipo** (el teléfono solo entrega su clave después de
que toques allí). Se hace una sola vez. El emparejamiento por el cable USB funciona igual: ambas
pantallas muestran un código; toca *Emparejar* en el teléfono solo si coinciden.

Por el cable, el programa también puede instalar la app por sí mismo: siempre **pregunta antes** y
explica qué teléfono, qué versión, por qué y qué ocurre exactamente; no se instala nada sin tu clic.

Para una copia: abre *My Media Backup* en el teléfono → **Iniciar modo de copia**. El equipo lo
encuentra y se conecta; después de la copia, el teléfono desactiva el modo de copia por sí mismo
(también tras 5 minutos sin uso). La app solo puede leer fotos y vídeos; la conexión está cifrada
(TLS, certificado fijado durante el emparejamiento). El equipo **solicita** los archivos: pide cada
archivo, y el teléfono solo responde al equipo emparejado y nunca envía nada por sí mismo. Mismos archivos y rutas que por ADB, así que las copias existentes simplemente continúan.

## Copia por Wi-Fi (sin cable)

Usa la **Depuración inalámbrica** integrada en Android (Android 11+, sin app en el teléfono). Todo
funciona igual que por USB, incluida la comprobación SHA-256 en el teléfono; solo es más lento
(depende del Wi-Fi, normalmente 10–40 MB/s).

1. Teléfono: *Ajustes → Sistema → Opciones para desarrolladores → Depuración inalámbrica* → activar
   (permitirlo para la red).
2. App: **Emparejar por Wi-Fi…** → en el teléfono toca *Vincular dispositivo con código QR* y escanea
   el código (o usa *Vincular dispositivo con código de vinculación* y escribe los 6 dígitos). Solo
   hace falta una vez.
3. A partir de entonces, el teléfono se encuentra automáticamente siempre que la Depuración
   inalámbrica esté activada y el teléfono y el equipo estén en el mismo Wi-Fi. Si están disponibles
   tanto USB como Wi-Fi, se usa USB.

**¿Sin router? Wi-Fi directo:** **Wi-Fi directo…** hace que el equipo abra su propia red Wi-Fi
(Linux: punto de acceso de NetworkManager, 5 GHz si es posible; Windows: abre los ajustes de *Zona
con cobertura inalámbrica*). El teléfono se une a ella (código QR para la cámara) y la copia se hace
directamente entre el teléfono y el equipo. La mayoría de los adaptadores Wi-Fi desconectan mientras
tanto el Wi-Fi normal; vuelve cuando se detiene el Wi-Fi directo (la app lo pregunta al cerrarla).

Un Wi-Fi Direct real (P2P) necesitaría una app complementaria en el teléfono; está previsto como un paso posterior.

## Plan de copia por unidad

En la lista de unidades de *Nueva copia*, cada unidad de copia tiene un **Plan de copia**:

* **Simple**: una carpeta que crece; solo se añaden fotos y vídeos nuevos (como se muestra arriba).
* **Abuelo-Padre-Hijo**: copias con fecha como en un segundo almacenamiento (ver más abajo): una
  copia **completa** cada 3 meses, una **diferencial** cada mes e **incrementales** entre medias.
  Una copia completa/diferencial también contiene los archivos anteriores que necesita (copiados en
  la unidad y verificados), así que las fotos borradas del teléfono se conservan en cada copia completa.

Ambos se pueden combinar, p. ej. *Simple* en un disco duro y *Abuelo-Padre-Hijo* en el otro. Una
carpeta de teléfono conserva el plan con el que se empezó.

## Segundo almacenamiento (exportación)

*Gestionar copias → Segundo almacenamiento* copia una copia de seguridad a otra unidad o a Google
Drive. Cada exportación tiene su propia carpeta:

```
PhoneBackups-Export/Sam/Pixel 10 Pro/
├── 2026-11-02_14-30-00_full/            (with the export report in Logs/)
├── 2026-11-20_09-12-45_incremental/
├── 2026-12-01_18-03-10_differential/
└── .phonebackup-export/catalog.sqlite
```

| Tipo                       | Copia                                                         |
|----------------------------|---------------------------------------------------------------|
| completa (full)            | todo                                                          |
| diferencial (differential) | todo lo nuevo desde la última exportación **completa**        |
| incremental                | todo lo nuevo desde la **última** exportación (de cualquier tipo) |

**Automático – Abuelo-Padre-Hijo** (por defecto) elige el tipo: completa cada 3 meses (abuelo),
diferencial cada mes (padre), incremental entre medias (hijo); la app muestra cuál toca a
continuación y por qué. Conserva las 4 exportaciones completas, 3 diferenciales y 6 incrementales
más recientes, más todo lo que necesitan para una restauración; las más antiguas se proponen para
eliminarlas y se borran **solo después de que lo confirmes** (*Limpiar exportaciones antiguas…*).

Cada archivo exportado se comprueba con el SHA-256 registrado en el momento de la copia. Un archivo
que se dañó en la primera unidad (degradación de datos, "bit rot") se notifica como ADVERTENCIA.
*Restaurar* reconstruye una carpeta completa a partir de la cadena más corta (completa + diferencial
más reciente + incrementales posteriores) y verifica cada archivo.

### Google Drive

*Añadir al almacenamiento en la nube → Google Drive* inicia sesión a través del navegador. La app
solo puede ver los archivos que ella misma ha subido (permiso `drive.file` de Google); el inicio de
sesión se queda en este equipo.
Dos tipos de exportación:

* **Copia**: un espejo de la copia de seguridad en *My Drive/My Smartphone Media Backup/Phone - Owner*:
  solo se suben archivos nuevos, no se borra ni sobrescribe nada.
* **Abuelo-Padre-Hijo** en *Phone - Owner (Grandfather-Father-Son)*: cada foto se guarda solo **una
  vez**; las exportaciones completas y diferenciales enlazan con archivos que ya están en Google
  Drive (accesos directos, sin espacio adicional; también con la Copia). La limpieza traslada los
  archivos que las exportaciones más recientes todavía usan a esas exportaciones antes de borrar
  nada. La restauración descarga los archivos y los verifica. Por favor, no borres a mano fotos
  sueltas allí: todas las exportaciones que enlazan con ellas las perderían.

Cada subida se comprueba con el SHA-256 propio de Google; el espacio libre se comprueba antes de la subida.
Política de privacidad: <https://machetso.github.io/my-smartphone-media-backup/privacy.html>

Las compilaciones desde el código fuente necesitan la clave de Google de la app: `python3 tools/set_google_key.py client_secret_….json`
(escribe el archivo `phonebackup/_gkey.py`, ignorado por git); las compilaciones de versiones la obtienen de los secretos de GitHub.

## Ajustes

Se guardan en `~/.config/phonebackup/config.json` (Windows: `%APPDATA%\PhoneBackup\config.json`):
nombre del propietario, carpetas del teléfono (por defecto `DCIM/Camera`, se pueden seleccionar
más en el programa), unidades, ruta de adb.

## Pruebas

```
python3 -m unittest discover tests
```

## Probado

* Linux (Pop!_OS) con un Google Pixel 10 Pro (Android 17) mediante ADB por USB 3:
  1372 archivos / 20 GB copiados a la vez en dos discos duros externos y verificados, unos 24 MB/s.
* Samsung Galaxy S20 FE por USB (ADB) y por Wi-Fi con la app del teléfono 0.3.3:
  12,4 MB/s por Wi-Fi, sin errores; actualización de la app del teléfono por el cable con la pregunta de instalación.
* Google Drive: Copia y Abuelo-Padre-Hijo con una copia de 20 GB (1381 archivos, unos
  4 MB/s de subida); accesos directos, limpieza y restauración verificados.
* Aún no probado en hardware real: la alternativa MTP (gvfs en Linux, Explorador de Windows) y Windows en general.

## Licencia

MIT: consulta [LICENSE](LICENSE).
