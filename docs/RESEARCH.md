# RESEARCH — lo que se adopta de los harness punteros, y lo que se descarta

Una línea por decisión, con la fuente oficial que la sostiene. Existe para que la próxima sesión no
vuelva a investigar lo mismo, y para que se vea qué se copió, qué se adaptó y qué se rechazó a
propósito. Fuentes: documentación oficial de cada proyecto, no blogs.

## Contrato de hook multi-harness (criterio `hook-contract`)

| Fuente | Qué dice | Qué hacemos |
|---|---|---|
| [Claude Code — Hooks reference](https://code.claude.com/docs/en/hooks) | El hook es un comando de shell: recibe el evento como JSON por **stdin** y contesta por stdout; `exit 2` bloquea y el motivo va por stderr. `Stop` y `PostToolUse` son los puntos de cierre de turno. | Se adopta el transporte (JSON por stdin, veredicto por exit code) porque es el único que los cinco harness comparten. Se descarta su tabla de códigos: `2` no distingue «el trabajo está mal» de «no se pudo verificar». |
| [Codex CLI — Hooks](https://learn.chatgpt.com/docs/hooks) | `hooks.json` o `[hooks]` en `config.toml`; `Stop` exige JSON en stdout y `{"decision":"block","reason":...}` continúa el turno; `exit 2` con stderr también vale. | Se adopta el vocabulario de eventos (`Stop`/`PostToolUse`) y el JSON en stdout. Se descarta el bloqueo por `decision`: un adaptador que traduce un veredicto a un booleano pierde la diferencia entre 10, 20 y 30, que es justo lo que hace útil a la puerta. |
| [Aider — Linting and testing](https://aider.chat/docs/usage/lint-test.html) | No hay hooks: `--lint-cmd` / `--test-cmd` (+`--auto-test`) ejecutan un comando tras cada edición y un exit distinto de 0 realimenta al modelo. | Se adopta tal cual: para Aider no se escribe adaptador, se apunta su `--lint-cmd`/`--test-cmd` a la puerta. Es el coste más bajo de la lista y cubre el segmento de edición CLI maduro. |
| Hermes (este harness) | `pre_verify` dispara cuando el agente editó ficheros y va a cerrar; el hook devuelve `{"action":"continue","message":...}` y el bucle se reanuda acotado. | Es el adaptador de referencia: `nexus/gates/hook.py` ya habla ese idioma y el contrato genérico es una traducción sobre el mismo cuerpo, no una segunda implementación. |

**Decisión de diseño**: un solo contrato (`nexus gate --hook`: un JSON por stdin, exit `0/10/20/30`) y
N traductores pequeños. El exit code **es** el veredicto; el cuerpo de la puerta es el mismo que ya usa
Hermes, así que gobernar otro harness no añade una segunda implementación del juicio, sólo una
traducción. Cuando el código no se puede atar a un veredicto, el contrato responde `10` (vuelve), nunca
`0`: un adaptador que no sabe qué pasó no puede dejar cerrar el turno.

## Compactación de contexto (criterio `context-compaction`)

| Fuente | Qué dice | Qué hacemos |
|---|---|---|
| [Claude Code — Explore the context window](https://code.claude.com/docs/en/context-window) | Al acercarse al límite, la conversación se compacta **automáticamente**: el resumen conserva patrones de código, estado de ficheros y decisiones, y tras compactar re-lee hasta cinco ficheros vistos en la sesión. El umbral es configurable (`/autocompact <tokens>`). | Se adopta el disparador por **umbral configurable** (`compact_threshold`, 0.55 por defecto, por debajo del 0.70 del relevo) y la idea de preservar lo reciente en vez de truncarlo por antigüedad. Se descarta la re-lectura automática de ficheros: en este harness el Obrero ya tiene `read_file` y el gate vuelve a medir, así que re-inyectar contenido sin que el turno lo pida solo infla la ventana. |
| [OpenCode — Compaction](https://opencode.ai/v2/docs/compaction/) | El esquema es explícito: `[system prompt][conversación vieja][recent 15k][trabajo pendiente]` -> se resume lo viejo y **se conservan intactos** el system prompt, los tokens recientes y el trabajo pendiente; hay una compactación en segundo plano al 85 % del umbral que se aplica al cruzar el umbral. | Se adopta el **layout** (system prompt y cola reciente intactos, el medio condensado) y que la compactación sea un paso previo, no el final de la sesión. Se descarta la compactación en segundo plano: aquí no hay un resumen «en vuelo» que sostener, y un proceso de fondo por sesión añade un huérfano potencial a cambio de nada. |
| [Anthropic — Compaction (server-side)](https://platform.claude.com/docs/en/build-with-claude/compaction) | El resumen lo escribe el modelo en el servidor; el cliente no aporta código de resumen. | Se descarta, y es la decisión de diseño central: **un resumen escrito por el modelo puede afirmar un hecho que el turno nunca tuvo**, y este repositorio exige que la misma entrada dé la misma salida. El digest es una función pura de los mensajes (herramientas contadas, ficheros tocados, errores vistos, líneas de texto), así que es determinista, testeable y no puede alucinar. |

**Decisión de diseño**: la compactación es una **rampa** antes del acantilado del relevo. A `0.55` del
presupuesto el transcript se reescribe en sitio (cabeza, objetivo, digest del medio, cola verbatim); a
`0.70` el relevo sigue haciendo lo suyo. La cola se corta siempre en una frontera válida de OpenAI
—nunca se deja un mensaje `tool` sin su `tool_calls`— porque un huérfano es un 400 en cualquier
servidor con esa forma.

## El instalador, medido (criterio `installer`)

| Fuente | Qué dice | Qué hacemos |
|---|---|---|
| [NSIS — Command line usage](https://nsis.sourceforge.io/Docs/Chapter3.html) | `/S` instala o desinstala en silencio; `/D=<ruta>` fija `$INSTDIR` y **tiene que ser el último parámetro, sin comillas**, y solo admite rutas absolutas. El desinstalador admite `_?=<ruta>`, que evita que se copie a TEMP y permite esperarlo con `ExecWait`, a cambio de dejar el `uninstall.exe` en su sitio. | Se adopta `/S /D=` como la prueba real, con dos consecuencias en el código: la sala tiene que ser absoluta y **no llevar espacios** (si los lleva, la prueba se declara *no verificable* en vez de pasar en falso) y `/D=` viaja como último argumento. Se descarta `_?=`: interesa observar que la sala desaparece de verdad —el ejemplo del propio manual tiene que hacer `RMDir` después—, así que se espera a que se vacíe. |
| [Tauri — Windows Installer](https://v2.tauri.app/distribute/windows-installer/) | El bundle NSIS es por usuario (`installMode: currentUser`, sin permisos de administrador) y la guía de empaquetado recomienda probar el artefacto con `/passive`, `/quiet` o `/silent` en lugar de dar por bueno que compila. | Se adopta la regla de fondo: **un instalador no está verificado hasta que se instala**, y se instala en una sala de usar y tirar (`%LOCALAPPDATA%\NexusHarnessVerify`) para no tocar la instalación real del usuario. Se descarta el `.msi`/WiX: un instalador que exige habilitar VBSCRIPT opcional en Windows es una dependencia del equipo, no del producto. |

**Decisión de diseño**: la prueba instala de verdad y compara **sha256** del motor instalado con el del
repositorio. La `--version` no vale: se midió `0.1.0` en la instalación frente a `0.3.0` en el repo (rojo,
bien), pero dos builds `0.3.0` distintos se habrían dado por buenos, y el instalador llegó a llevar un
motor con 16 suites mientras el fuente corría 17. Además se comprueba que la ventana instalada es un
binario de interfaz leyendo el **subsistema PE** (`2` = GUI, `3` = consola), y se desinstala. El registro
de HKCU que el instalador escribe se fotografía antes y se devuelve como estaba: verificar no le cambia
nada al usuario.

## Política de comandos (criterio `shell-policy`)

| Fuente | Qué dice | Qué hacemos |
|---|---|---|
| [Claude Code — Configure permissions](https://code.claude.com/docs/en/permissions) | Las reglas `deny` **ganan** sobre las `allow` y sobre cualquier ámbito (si el usuario permite y el proyecto deniega, deniega). Una regla `Bash(...)` coincide con el texto del comando **tal y como se escribe**, y la propia documentación avisa de que un `deny` no ve dentro de `sh -c`: es un límite declarado, no una jaula. | Se adopta la **precedencia denegar-primero** (en `classify` lo catastrófico se mira antes que lo demás y no hay modo que lo levante) y la coincidencia sobre el texto escrito, con el límite escrito también en el docstring del módulo. Se descarta el modelo `allow`/`deny` por herramienta: aquí la decisión tiene que caber en una línea de configuración, no en un fichero de reglas. |
| [Claude Code — Sandboxed Bash tool](https://code.claude.com/docs/en/sandboxing) | El aislamiento real es del sistema operativo (ficheros y red); además, `rm`/`rmdir` sobre una **ruta crítica** sigue pasando por el prompt normal aunque el sandbox esté en modo auto-permitir. | Se adopta la idea de que hay comandos que **no se delegan al modo**: esa es la tabla `catastrophic`, que ni `unrestricted` levanta. Se descarta el sandbox por SO: exige un contenedor o un job object por comando, es dependiente de la plataforma y añade un modo de fallo propio (y en este arnés el gate y la ley de 400 ya son el backstop). |
| [Codex — Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security) | Separa dos controles que trabajan juntos: `sandbox_mode` (qué puede hacer técnicamente) y `approval_policy` (cuándo debe parar y preguntar), ambos en `config.toml`. | Se adopta la separación **política vs. aprobación** y se resuelve en el eje que este arnés sí tiene: la política se decide **antes** de la llamada (`shell_policy` en `~/.nexus/harness.json`) y no hay prompt interactivo, porque el turno corre a las 03:00 sin nadie al teclado: una aprobación que nadie puede contestar es un cuelgue, no un control. Se descarta `on-request`. |

**Decisión de diseño**: la denegación es una **observación**, no una excepción. `tools.Registry.call`
ya convertía `ValueError` en `ok=False` con el texto del motivo, así que la política se limitó a hablar
ese idioma: el modelo lee `refused [standard/reckless]: empujar con --force -- sube la politica ...` y
puede corregirse en el turno siguiente, que es justo lo que la ley 2 del protocolo pide. Y el nivel se
elige por **efecto medido**, no por el texto de la config: la suite crea un directorio con `standard`,
lo borra con `unrestricted` y comprueba que un `read_only` ni eso.

## Deshacer el turno (criterio `turn-checkpoint`)

| Fuente | Qué dice | Qué hacemos |
|---|---|---|
| [Claude Code — Checkpointing](https://code.claude.com/docs/en/checkpointing) | La instantanea se toma **antes de cada turno**, cubre lo que tocaron sus herramientas de edicion, `Restore code` revierte los ficheros dejando la conversacion, y una instantanea que ya no esta **falla fuerte** (`No files were restored`) en vez de restaurar a medias. La propia pagina avisa de que un checkpoint **no sustituye** al control de versiones, y que un symlink o hard link se salta con aviso. | Se adopta la unidad **turno** (no fichero), la restauracion de bytes y el fallo ruidoso: si falta un blob o su sha256 no cuadra, `undo` devuelve `ok=False` con la ruta en `skipped` y el fichero se queda como estaba -- nunca media restauracion contada como exito. Se adopta tambien quedarse en el nivel de sesion: git sigue siendo del operador. |
| [Aider — Git integration](https://aider.chat/docs/git.html) y [In-chat commands](https://aider.chat/docs/usage/commands.html) | `/undo` es `git revert` del ultimo commit de aider, y aider commitea **cada** edicion para que ese undo exista; sin repositorio, `--no-git` desactiva la funcion entera. | Se descarta git como mecanismo: exige que el proyecto sea un repositorio y que el arnes escriba commits en la historia del operador. El bucle propio se mantiene como modo **sin dependencias**, asi que el diario es propio (`.nexus/checkpoints/NNNN-slug`, manifiesto + blobs) y no toca la historia de nadie. |
| [Claude Code — Checkpointing](https://code.claude.com/docs/en/checkpointing) (retencion) | Guarda los 100 checkpoints mas recientes por sesion, borra lo que ya no referencia nadie, y barre por antiguedad (~30 dias). | Se adopta la idea de que el diario **se poda solo** y se simplifica: los ultimos 20 turnos del proyecto, podados al abrir el siguiente (`prune` en `begin`). Sin barrido por fecha: un diario viejo es disco, no historia, y el reloj no tiene que decidir nada. |

**Decisión de diseño**: el gancho vive en `file_ops`, el suelo por el que pasa **toda** escritura del
arnes, y no en cada herramienta. Asi una edicion que entra por `edit.patch_replace`, por `write_file` o
por un parche V4A queda anotada sin que ninguna de ellas sepa que existe un diario, y la suite lo
comprueba con la herramienta real (`edit.patch_replace` sobre el fichero del proyecto de usar y tirar).
La instantanea se toma **antes** del `os.replace`, porque una copia tomada despues ya no sirve para
deshacer nada; y el diario escribe su propio manifiesto con `atomic_write_bytes` -- el suelo que **no**
consulta el diario -- para que anotar un turno no se anote a si mismo.


## El turno tiene un techo en dolares (criterio `cost-budget`)

| Fuente | Qué dice | Qué hacemos |
|---|---|---|
| [Claude Code — Manage costs](https://code.claude.com/docs/en/costs) | `--max-budget-usd` es un **tope duro**: "when the cumulative cost of API calls reaches this amount, Claude Code stops making additional calls". El coste se calcula localmente desde los tokens a precio de lista, salvo que un `modelPricing` gestionado pise las tarifas; la cifra es una **estimacion**, no la factura. Avisa de que el calculo es aproximado. | Se adopta el tope duro en USD y la comprobacion **antes** de cada llamada: cruzar el techo no pide una llamada mas. Se adopta tambien el aviso de estimacion: la cifra es para decidir, no para cuadrar la factura. Se descarta el `modelPricing` gestionado por MDM: este arnes lee su tabla de `harness.json`. |
| [Aider — FAQ y metadata de modelos](https://aider.chat/docs/faq.html) | Aider no cobra; cobra el modelo. Si un modelo no trae `input_cost_per_token` en su metadata, Aider **no imprime `$0.00`: no imprime linea de coste**, porque no sabe. | Se adopta el mismo rigor: un modelo sin precio conocido **no cuesta cero**; la llamada se cuenta como `unpriced` y se declara. Un motor local (`lmstudio:`, `ollama:`) si cuesta 0, pero como precio **declarado**, que no es lo mismo que no saberlo. |

**Decisión de diseño**: el presupuesto de tokens que ya existia (`compaction`, `session_relay`) es
higiene de contexto, no dinero: `max_steps` limita el **numero** de llamadas, no su **precio**, y una
entrada de 100k tokens no cuesta lo mismo que una salida de 100k. Por eso el techo es en USD, separa
entrada de salida y vive en `nexus_harness/budget.py`, con la parada en el mismo punto que el medidor
de tokens: el bucle. La suite mide la parada **comparando** el mismo guion con techo y sin techo (1
llamada contra 2), que es la unica forma de probar que la parada es lo que corta y no el azar.
