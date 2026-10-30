# Nexus Harness Desktop — la app instalable

> Corrida narrada: 2026-10-30 (las cifras de dentro son de su momento, no del árbol actual).

Lo que se instala es un programa de escritorio con su icono, su ventana y su desinstalador. Dentro
corre el motor de este repositorio, congelado, y el protocolo Nexus vive en él: no es un hook, no es un
plugin, no depende de tener Python en el equipo destino.

```
NexusHarness-Setup-1.0.0.exe          instalador NSIS, por usuario, sin permisos de administrador
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

`Nexus-Harness.bat` (doble clic) abre la **app nativa**:

1. Cierra cualquier motor huérfano que esté escuchando en el 8765 (`netstat` + `taskkill /T /F`): un
   motor que sobrevivió a su ventana deja el puerto cogido y el `.exe` bloqueado.
2. Lanza `nexus-harness-desktop.exe` — la ventana Tauri, con su icono — y **nunca** el navegador.
3. La ventana elige un **puerto libre** (no pelea por el 8765 con otra copia ni con el CLI), genera un
   **token de lanzamiento** y arranca el motor como proceso hijo con `NEXUS_HARNESS_TOKEN` y
   `CREATE_NO_WINDOW` (sin consola negra).
4. Espera a que el puerto acepte conexiones (30 s como máximo) y solo entonces abre la vista sobre
   `http://127.0.0.1:<puerto>/?token=…`.
5. Al cerrar la ventana, mata el motor: no quedan procesos huérfanos.

El navegador es una decisión explícita, no el camino por defecto: `Nexus-Harness.bat --web` arranca el
motor en `127.0.0.1:8765` y abre ahí la interfaz. Cualquier otro argumento se pasa al CLI (`run`,
`gate`, `selftest`, `lint`, `models`, `bridge`).

El motor sirve la **misma** interfaz que el CLI (`nexus_harness/web`), así que una corrección en la UI
aparece en la ventana y en el navegador a la vez. Hay un front-end, no uno por cáscara.

Si la ventana no aparece, el `.bat` dice qué falta (la app no está instalada y cómo instalarla) en vez
de abrir el navegador por su cuenta.

## Qué se puede hacer desde la ventana

- Conversar con el agente: herramientas reales (`read_file`, `search`, `patch`, `shell`, `fetch_url`…),
  gate automático en cuanto se toca un fichero, y reparación sin intervención si sale rojo.
- Elegir proyecto de `C:\Proyectos` (el compositor queda bloqueado hasta que haya proyecto: un chat no
  debe editar tu carpeta de instalación).
- Cambiar el modelo del Director al vuelo, bajo la caja de escribir.
- Buscar, renombrar y borrar conversaciones desde la barra lateral.
- Retomar conversaciones: se guardan en `<proyecto>/.nexus/harness/chat/`.
- Todo lo demás (modelos de la tríada, claves, memoria y contexto, skills, MCP, puente móvil,
  estadísticas) vive en **⚙ Configuración**, una pantalla propia.

## El chat, y una pantalla de Configuración (0.4.0)

La ventana tiene **dos** pantallas y ni una pestaña más:

- **El chat** (`/`): ocupando el ancho entero, sin barra lateral derecha. Lo que pasa durante un turno
  (una herramienta, el veredicto del gate, el juez, las skills que viajan en RAM) aparece como una
  **tira discreta dentro del propio hilo**, no en un panel fijo. Abajo, la caja de escribir ocupa todo
  el ancho, con `+ Adjuntar`, `Enviar`, `Detener` cuando trabaja, y el selector del modelo del Director
  a un lado. El campo de «comando de test» que había ahí se fue a Configuración: es un ajuste del
  proyecto, no algo que se toque en cada mensaje.
- **⚙ Configuración** (`/settings`), con el botón en la barra lateral izquierda del chat: pantalla
  completa, buscador arriba (`Ctrl+K`), `✕` arriba a la derecha (o `Esc`) para volver, y un árbol de
  categorías desplegables a la izquierda con **ocho secciones**: `⚙ Modelos (Tríada IA)` (con sus
  submenús de Director / Obrero / Juez / Subagentes), `📁 Espacio de trabajo & Proyectos` (incluido el
  **Auto-Spec Generator** y el comando de test por proyecto), `🛡 Seguridad & Bóveda`, `🧠 Memoria y
  contexto`, `⚡ Skills & Skill Architect`, `🔌 Conectores MCP`, `📱 Puente Móvil (Bots)` y
  `📊 Estadísticas & Auditoría`.

Cómo está montado, y por qué así:

- **Cada panel lo escribe su módulo dueño** (`settings_models.py`, `settings_work.py`,
  `settings_tools.py`) y el marco (`settings.py`) solo pinta el árbol y el panel. Guardar es un
  `<form>` de verdad contra `/api/settings`: responde un **303** de vuelta al panel con una nota, así
  que funciona con el script bloqueado y recargar no reenvía nada. `settings.js` solo añade `Ctrl+K`.
- **Un ajuste, una casa.** El presupuesto de contexto y el umbral de relevo salen en dos secciones
  (Modelos y Memoria) a propósito: son los MISMOS campos del mismo fichero, así que dos puertas dan a
  la misma habitación. Un ajuste duplicado solo es un problema cuando cada puerta guarda en un sitio.
- **Se enseña lo que se puede leer ahora**: el catálogo real de skills (escaneado por el protocolo),
  los servidores MCP que contestan, el demonio con su PID y su cola. Un panel que presume de 215 skills
  y no las puede abrir es un panel que miente.
- **Lo que no cabe aquí se dice, no se esconde**: la política de comandos muestra su tabla de rechazos;
  el cofre enseña nombres y nunca valores; el panel de espacio dice qué proyecto no tiene gobernanza.
- **Un motor viejo se detecta**: la página compara su contrato (`API_VERSION`) con el que publica
  `/api/health` y, si el proceso en marcha es anterior, lo dice en una banda con la instrucción de
  reiniciar. Sin eso, actualizar el código deja botones que no responden y ninguna pista.

## 1.0.0: barra en vivo, cola de proyectos y bucle autónomo

Cinco correcciones de producto, cada una con su prueba determinista (`selftests/test_ux.py` las mide
por HTTP y sobre el HTML servido, no sobre la intención):

1. **La esquina del chat ya no dice «en reposo».** Es una píldora viva (`activity.js` →
   `/api/activity`) que enseña la fase en curso con la herramienta (`🔧 Obrero: patch · a.py`), el gate
   (`⚖️ Gate: 3/3 checks en verde`), el juez, el backup del bucle o el commit. Al terminar un turno
   enseña el resultado medido (`✅ Gate OK · Juez VERDE · Contexto 18%`) y al pulsarla se abre el
   detalle: ficheros tocados, gate con sus checks, tokens y el control del Autopilot. Sondeo
   adaptativo: 400 ms mientras hay trabajo, 1,6 s cuando no pasa nada.
2. **Proyectos: cola de prioridad arrastrable.** Las tarjetas gobernadas se arrastran (HTML5 nativo,
   sin librería) y el orden se guarda en `~/.nexus/harness.json` (`project_order`); también hay flechas
   ▲▼ para quien prefiere el teclado. `+ Crear Nuevo Proyecto` pide nombre y objetivo, crea la carpeta,
   hace `git init` con primer commit, escribe `.ai/PROJECT_RULES.md`, genera el Auto-Spec y la mete al
   final de la cola. Las 28 carpetas sueltas viven en una tabla plegada con buscador.
3. **Skills:** el `Skill Architect + GitHub Scout` sube al principio; los cinco filtros pasan a una
   fila horizontal junto al buscador; la rejilla es `repeat(auto-fill, minmax(280px, 1fr))` (4 columnas
   a partir de 1600 px) y hay paginación de 24 tarjetas.
4. **Estadísticas:** KPIs en 4 columnas y **tres gráficos SVG nativos** (sin CDN, sin JavaScript):
   columnas de tokens consumidos vs evitados por proyecto, anillo de eficacia de la tríada y tres barras
   de salud por proyecto (criterios de spec, runs verdes, horas ahorradas). Cada gráfico declara su
   fuente, y lo que no está medido se dice con palabras en el mismo hueco.
5. **Bucle autónomo iterativo (`autonomy.py`).** Por proyecto o desde el chat: **backup → planifica →
   ejecuta la tríada → gate → commit limpio → progreso**, y al siguiente hito; si el gate queda rojo
   tras las reparaciones del Obrero, ese proyecto para y la cola pasa al #2. Sin snapshot no se edita:
   `git stash create` + tag cuando hay repositorio, zip en `.nexus/backups/` cuando no.

El motor sube su contrato a **`api: 3`**: una página nueva contra un motor viejo lo dice en una banda
en vez de dejar botones muertos.

## Construirlo desde el código

```
python tools/make_icon.py apps/desktop/src-tauri/app-icon.png     # icono (sin librerías)
.build/venv/Scripts/pyinstaller.exe --noconfirm \
  --distpath dist --workpath .build/pyi tools/engine.spec         # el motor, con la receta del repo
cp dist/nexus-harness-engine.exe apps/desktop/src-tauri/engine/
cd apps/desktop && npm install && npx tauri icon src-tauri/app-icon.png && npx tauri build
```

Salida: `apps/desktop/src-tauri/target/release/bundle/nsis/Nexus Harness_1.0.0_x64-setup.exe`.

## Verificarlo sin tocar tu instalación

Un instalador no está verificado hasta que se instala, y hacerlo sobre la instalación real del usuario
es justo lo que no queremos en una prueba que corre cada noche. La verificación instala en silencio en
una sala de usar y tirar, compara bytes y la desinstala:

```
$ python tools/nightshift.py install --check
sala       : C:\Users\<usuario>\AppData\Local\NexusHarnessVerify (no existia)
instalador : NexusHarness-Setup-1.0.0.exe -> exit 0
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
real, el paso es `signtool sign /fd sha256 /f cert.pfx /p <pass> "Nexus Harness_1.0.0_x64-setup.exe"`
antes de distribuir; Tauri también acepta `bundle.windows.certificateThumbprint`.

## Límites conocidos

- **WebView2** debe existir en el sistema (Windows 11 lo trae; en Windows 10 el instalador de Tauri
  puede descargarlo si se activa `webviewInstallMode`).
- El motor incluye `NexusProtocol` congelado: si el protocolo cambia, hay que reconstruir el motor
  (no lee tu copia de `C:\Proyectos\NexusProtocol` en tiempo de ejecución).
- El instalador no se actualiza solo: no hay canal de updates todavía.
