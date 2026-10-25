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
