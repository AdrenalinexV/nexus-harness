# Nexus Harness Desktop — la app instalable

Lo que se instala es un programa de escritorio con su icono, su ventana y su desinstalador. Dentro
corre el motor de este repositorio, congelado, y el protocolo Nexus vive en él: no es un hook, no es un
plugin, no depende de tener Python en el equipo destino.

```
NexusHarness-Setup-0.3.0.exe          instalador NSIS, por usuario, sin permisos de administrador
└── %LOCALAPPDATA%\Nexus Harness\
    ├── nexus-harness-desktop.exe     ventana nativa (Tauri 2 / WebView2)
    ├── engine\nexus-harness-engine.exe   motor congelado (Python + NexusProtocol dentro)
    ├── uninstall.exe
    └── icons...
```

## Bandeja del sistema y cierre limpio (0.3.0)

- La X de la ventana **oculta** la app en la bandeja: el trabajo en curso no se pierde por un clic.
- Menú de la bandeja: `Abrir Nexus Harness`, `Estado del motor` (trae la ventana al frente) y
  `Salir completamente`.
- Salir es ordenado: `POST /api/shutdown` (el motor cierra su socket y llama a `os._exit(0)`, y con él
  cae el *bootloader* de PyInstaller) y, si no responde, `taskkill /T /F` sobre el árbol.
  Así no quedan motores huérfanos sosteniendo su propio `.exe`, que era lo que impedía al instalador
  siguiente reemplazarlo.

## Cómo arranca

1. La ventana elige un **puerto libre** (no pelea por el 8765 con otra copia ni con el CLI).
2. Genera un **token de lanzamiento** y arranca el motor como proceso hijo con
   `NEXUS_HARNESS_TOKEN` y `CREATE_NO_WINDOW` (sin consola negra).
3. Espera a que el puerto acepte conexiones (30 s como máximo) y solo entonces abre la vista sobre
   `http://127.0.0.1:<puerto>/?token=…`.
4. Al cerrar la ventana, mata el motor: no quedan procesos huérfanos.

El motor sirve la **misma** interfaz que el CLI (`nexus_harness/web`), así que una corrección en la UI
aparece en la ventana y en el navegador a la vez. Hay un front-end, no uno por cáscara.

## Qué se puede hacer desde la ventana

- Conversar con el agente: herramientas reales (`read_file`, `search`, `patch`, `shell`, `fetch_url`…),
  gate automático en cuanto se toca un fichero, y reparación sin intervención si sale rojo.
- Elegir proyecto de `C:\Proyectos` (el compositor queda bloqueado hasta que haya proyecto: un chat no
  debe editar tu carpeta de instalación).
- Cambiar de modelo por rol (director / obrero / juez) en caliente.
- Escribir memoria durable (viaja en cada prompt) y ver las skills que se inyectan en RAM.
- Ver el presupuesto de la conversación y el estado del gate y del juez del último turno.
- Retomar conversaciones: se guardan en `<proyecto>/.nexus/harness/chat/`.

## Construirlo desde el código

```
python tools/make_icon.py apps/desktop/src-tauri/app-icon.png     # icono (sin librerías)
.build/venv/Scripts/pyinstaller.exe --noconfirm \
  --distpath dist --workpath .build/pyi tools/engine.spec         # el motor, con la receta del repo
cp dist/nexus-harness-engine.exe apps/desktop/src-tauri/engine/
cd apps/desktop && npm install && npx tauri icon src-tauri/app-icon.png && npx tauri build
```

Salida: `apps/desktop/src-tauri/target/release/bundle/nsis/Nexus Harness_0.3.0_x64-setup.exe`.

## Verificarlo sin tocar tu instalación

Un instalador no está verificado hasta que se instala, y hacerlo sobre la instalación real del usuario
es justo lo que no queremos en una prueba que corre cada noche. La verificación instala en silencio en
una sala de usar y tirar, compara bytes y la desinstala:

```
$ python tools/nightshift.py install --check
sala       : C:\Users\<usuario>\AppData\Local\NexusHarnessVerify (no existia)
instalador : NexusHarness-Setup-0.3.0.exe -> exit 0
ventana    : nexus-harness-desktop.exe subsystem=2 (2 = interfaz)
motor      : repo     sha256=82589bc520e8
           : instalado sha256=82589bc520e8
desinstalar: exit 0
sala       : eliminada, sin fichero bloqueado
registro   : devuelto como estaba
ok: el instalador deja el motor del repositorio y una ventana de interfaz, y se desinstala limpio
```

Por qué **sha256** y no `--version`: dos builds `0.3.0` distintos se darían por buenos, y el instalador
llegó a llevar un motor con 16 suites mientras el fuente corría 17. El sha256 no tiene ese hueco: o el
fichero instalado **es** el del repositorio, o no lo es. El **subsistema PE** de la ventana (`2` = GUI,
`3` = consola) es lo que distingue una app de escritorio de un motor con un `.exe` al lado. El registro
de HKCU que el instalador escribe se fotografía antes y se devuelve como estaba, así que verificar no le
cambia nada a quien tenga la app instalada. El código de esta prueba vive en `tools/installer_verify.py`.

## Firma

El instalador sale **sin firmar**: Windows mostrará «editor desconocido» la primera vez (SmartScreen).
Una firma autofirmada no elimina ese aviso; solo cambia el nombre del editor, y añade un certificado que
hay que instalar en el equipo para que sea creíble. Si algún día hay un certificado de firma de código
real, el paso es `signtool sign /fd sha256 /f cert.pfx /p <pass> "Nexus Harness_0.3.0_x64-setup.exe"`
antes de distribuir; Tauri también acepta `bundle.windows.certificateThumbprint`.

## Límites conocidos

- **WebView2** debe existir en el sistema (Windows 11 lo trae; en Windows 10 el instalador de Tauri
  puede descargarlo si se activa `webviewInstallMode`).
- El motor incluye `NexusProtocol` congelado: si el protocolo cambia, hay que reconstruir el motor
  (no lee tu copia de `C:\Proyectos\NexusProtocol` en tiempo de ejecución).
- El instalador no se actualiza solo: no hay canal de updates todavía.
