# Nexus Harness Desktop — la app instalable

Lo que se instala es un programa de escritorio con su icono, su ventana y su desinstalador. Dentro
corre el motor de este repositorio, congelado, y el protocolo Nexus vive en él: no es un hook, no es un
plugin, no depende de tener Python en el equipo destino.

```
NexusHarness-Setup-0.2.0.exe          instalador NSIS, por usuario, sin permisos de administrador
└── %LOCALAPPDATA%\Nexus Harness\
    ├── nexus-harness-desktop.exe     ventana nativa (Tauri 2 / WebView2)
    ├── engine\nexus-harness-engine.exe   motor congelado (Python + NexusProtocol dentro)
    ├── uninstall.exe
    └── icons...
```

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
.build/venv/Scripts/python.exe -m PyInstaller --onefile --console \
  --name nexus-harness-engine --paths C:/Proyectos/NexusProtocol --paths . \
  --collect-submodules nexus --collect-submodules nexus_harness \
  --add-data "<repo>/nexus_harness/web;web" \
  --distpath dist --workpath .build/pyi --specpath .build tools/engine_entry.py
cp dist/nexus-harness-engine.exe apps/desktop/src-tauri/engine/
cd apps/desktop && npm install && npx tauri icon src-tauri/app-icon.png && npx tauri build
```

Salida: `apps/desktop/src-tauri/target/release/bundle/nsis/Nexus Harness_0.2.0_x64-setup.exe`.

## Firma

El instalador sale **sin firmar**: Windows mostrará «editor desconocido» la primera vez (SmartScreen).
Una firma autofirmada no elimina ese aviso; solo cambia el nombre del editor, y añade un certificado que
hay que instalar en el equipo para que sea creíble. Si algún día hay un certificado de firma de código
real, el paso es `signtool sign /fd sha256 /f cert.pfx /p <pass> "Nexus Harness_0.2.0_x64-setup.exe"`
antes de distribuir; Tauri también acepta `bundle.windows.certificateThumbprint`.

## Límites conocidos

- **WebView2** debe existir en el sistema (Windows 11 lo trae; en Windows 10 el instalador de Tauri
  puede descargarlo si se activa `webviewInstallMode`).
- El motor incluye `NexusProtocol` congelado: si el protocolo cambia, hay que reconstruir el motor
  (no lee tu copia de `C:\Proyectos\NexusProtocol` en tiempo de ejecución).
- El instalador no se actualiza solo: no hay canal de updates todavía.
