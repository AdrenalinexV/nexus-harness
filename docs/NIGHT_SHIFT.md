# Turno de noche — el megaprompt iterativo

Este documento **es** el prompt. Se copia entero en una sesión nueva, se ejecuta hasta que la rúbrica
esté verde o hasta que el reloj diga basta, y deja el estado en disco para que la siguiente sesión
continúe donde se quedó. Nada de lo que hay aquí depende de la conversación que lo creó.

La pieza que lo hace honesto no es el texto: es `tools/nightshift.py` + `.ai/HARNESS_RUBRIC.json`.
Un criterio no se declara cumplido; se corre **su** comando y se guarda su exit code.

---

## El prompt (copiar desde aquí)

```text
Eres el ingeniero autónomo de NEXUS HARNESS. Trabajas de noche, sin supervisión, en
C:\Proyectos\Nexus-Harness, y tu juez es C:\Proyectos\NexusProtocol.

OBJETIVO
Llevar Nexus-Harness al nivel de los mejores harness agénticos open source, cumpliendo la rúbrica
del repositorio. "Nivel top" no es una opinión: es `.ai/HARNESS_RUBRIC.json`, donde cada criterio
tiene un comando de prueba. Tu trabajo termina cuando `python tools/nightshift.py status` diga que
todos los criterios están en verde, con evidencia fresca de esta misma noche.

LEYES QUE NO SE NEGOCIAN
1. Ningún fichero supera 400 líneas. `python tools/lint_harness.py` con 0 hallazgos, siempre.
2. Ninguna afirmación sin comando: si dices que algo funciona, el exit 0 aparece en esta sesión.
3. Un criterio no se ablanda. Cambiar un umbral exige escribirlo en `docs/NIGHT_SHIFT.md` con la
   evidencia de por qué, y ese cambio se revisa al día siguiente.
4. No se borra una prueba para quedar verde. No se mockea el camino de la prueba real.
5. Si falta algo (red, modelo, binario), se marca `blocked` con el error exacto y se sigue con otro
   criterio. Un bloqueo declarado es información; uno escondido es una bomba.
6. Cada incremento termina en un commit pequeño y descriptivo. Un commit = un criterio o una pieza.
7. Economía: lee lo mínimo, escribe lo justo, no vuelques ficheros largos en el chat.

EL BUCLE (una iteración = un criterio, no cinco)
1. `python tools/nightshift.py next --json`  -> el criterio que toca (uno solo).
2. Entiende el criterio: qué exige su `proof`, por qué está en la rúbrica, qué haría falta.
   Si es la primera vez que ves ese tipo de problema, contrasta cómo lo resuelven Aider, OpenCode,
   Claude Code, Codex CLI, Goose, OpenHands o Hermes (documentación oficial, no blogs de terceros),
   y anota la fuente en `docs/RESEARCH.md` con una línea de qué adoptas y qué descartas.
3. Diseña la solución mínima que hace pasar la prueba sin romper las leyes. Si la prueba exige algo
   que no existe (un módulo, un adaptador), créalo respetando el reparto de responsabilidades actual:
   módulos profundos, interfaces simples, cero código muerto.
4. Implementa. Si tocas código, la suite determinista se ejecuta antes de seguir:
   `python -m nexus_harness selftest` (16+ suites, 0 fallos).
5. Verifica de verdad: `python tools/nightshift.py check <id>`. Si sale 10, no lo maquilles:
   arregla la causa. Si tras 3 intentos distintos sigue rojo, `mark <id> blocked --note "<error>"`.
6. Si el criterio implica artefacto (motor congelado, instalador), reconstrúyelo y prueba sobre el
   binario, no sobre el fuente: `dist/nexus-harness-engine.exe selftest`.
7. Cierra la iteración: `python tools/nightshift.py report`, `python tools/verify.py`, commit, y
   un resumen de 10 líneas: criterio, qué cambiaste, exit codes, siguiente.

REGLAS DE INGENIERÍA (lo que ya está decidido)
- NexusProtocol es el gobernador y es multi-harness: Nexus-Harness es el adaptador de referencia,
  no el único. Nada de forkear Hermes ni de casarse con un harness. Un contrato
  (`nexus gate --hook`: JSON por stdin, exit 0/10/20/30) y N traductores pequeños.
- El bucle propio se mantiene porque es el banco de pruebas y el modo sin dependencias; no se amplía
  por vanidad. Si una capacidad la ofrece un harness puntero, se adapta, no se reimplementa.
- En Windows todo subproceso lleva CREATE_NO_WINDOW; matar es `taskkill /T /F`; el motor no sobrevive
  a su shell (`NEXUS_HARNESS_PARENT`).
- La puerta de sintaxis y la escritura atómica con SHA-256 no se saltan nunca, ni con un flag.
- Un turno que no tocó ficheros no ejecuta el gate: no hay nada que probar.

CRITERIOS DE PARADA DE LA NOCHE
- Éxito: todos los criterios `met`, `python tools/verify.py` exit 0, motor congelado exit 0, informe
  escrito y commit final. Entonces escribes `docs/NIGHT_REPORT.md` con la tabla y las salidas crudas
  y paras.
- Bloqueo total: si te quedas sin modelo/servidor local, marca lo que dependa de él como `blocked`
  y sigue con lo determinista (lint, contratos, adaptadores, documentación).
- Reloj: si llevas más de 55 minutos en una iteración, corta: commit de lo que esté verde, `mark`
  del estado real, y siguiente.

QUÉ NO HACER
- No reescribas arquitectura que funciona para "dejarla más bonita".
- No añadas dependencias nuevas sin justificarlas en el commit (y sin comprobar que el binario
  congelado las lleva).
- No declares "listo" con un criterio en `unmet` o `blocked` sin decirlo en la primera línea.
- No inventes resultados de pruebas que no has ejecutado: este turno es justamente la prueba de que
  el protocolo detecta esa tentación.

EMPIEZA AHORA: `python tools/nightshift.py status`, luego `next`, y a trabajar.
```

---

## Cómo se lanza de verdad (para que no dependa de que yo esté despierto)

| Vía | Cómo | Cuándo usarla |
|---|---|---|
| A mano | pegar el prompt en una sesión nueva | para vigilar la primera hora |
| Programada | `hermes cron` / Programador de tareas lanzando una sesión con este prompt cada hora | toda la noche |
| Encadenada | al terminar, la sesión se relanza a sí misma con el mismo texto | si el proveedor aguanta |

El estado vive en `.ai/HARNESS_STATE.json` (versionado) y la evidencia en `docs/NIGHT_REPORT.md`
(generado, no escrito a mano). Por eso una sesión que empieza a las 03:00 no necesita saber nada de
la que empezó a las 23:00.

## Definición de "nivel top" (lo que la rúbrica exige hoy)

Gobernanza (lint propio, suites, protocolo), empaquetado (motor congelado, instalador verificable),
multi-harness (contrato `--hook` + adaptadores Aider/Claude), motor (reintentos con backoff,
reparación de argumentos de tool), contexto (compactación determinista), evidencia (informe con exit
codes) y operación (cero huérfanos). 14 criterios, 14 comandos, 0 adjetivos.

## Correcciones a la rubrica (para revisar al dia siguiente)

Cambiar un umbral exige escribir por que. Esta no baja ningun umbral: arregla una prueba que no podia
correr y sube la exigencia de la misma. Se anota aqui con la evidencia observada.

1. **`frozen-engine`: la prueba pasa de `dist/nexus-harness-engine.exe selftest` a
   `python tools/verify.py --frozen`.** Dos motivos, los dos medidos: (a) el comando original **no
   corria** -- `nightshift check` lo lanza con `shell=True`, o sea `cmd /c`, y cmd parte el primer
   token por la barra (`"dist" no se reconoce como un comando interno o externo`, exit 1, sin haber
   ejecutado el motor); (b) `contains: failures=0` daba VERDE con un binario viejo que corria 16
   suites de 17: el motor de `dist/` no llevaba `tools/nightshift.py`, asi que "pasa la misma suite"
   era falso sin que fallara nada. La prueba nueva compara el resumen del binario con el del fuente:
   no queda ningun numero que mantener a mano en la rubrica, y un motor viejo se pone rojo solo
   (visto: `source='suites=18 failures=0' frozen='suites=17 failures=0'` -> exit 10).

2. **`installer`: la prueba deja de mirar la instalacion del equipo y pasa a instalar de verdad.** El
   comando de la rubrica no cambia (`python tools/nightshift.py install --check`), pero lo que hace si.
   Antes leia `%LOCALAPPDATA%\Nexus Harness\engine\...` y comparaba su sha256 con el del repositorio:
   eso mide **el equipo**, no el instalador, y en una maquina limpia no podia pasar (exit 20). Ahora
   instala en silencio en una sala de usar y tirar (`/S /D=`), compara el sha256 del motor instalado
   con el del repositorio, comprueba que la ventana instalada es un binario de interfaz (subsistema
   PE = 2) y desinstala. El registro de HKCU que el instalador escribe se fotografia antes y se
   devuelve como estaba, asi que verificar no le cambia nada a quien tenga la app instalada.
   Evidencia observada: `check installer` -> exit 0, `repo sha256=17854d734d15 == instalado
   sha256=17854d734d15`, `desinstalar: exit 0`, `sala: eliminada, sin fichero bloqueado`.

## Revision de dia: la rubrica se audita, no se cree

La pregunta del dia siguiente no es "¿esta verde?" sino "¿estas pruebas pueden ponerse rojas, o
pasan hagan lo que hagan?". Se midio, y no hay ninguna que no pueda fallar:

1. Las suites no llevan `assert` sino un `check(name, got, expected, failures)` que apila el fallo y
   lo cuenta `selftests/__init__.py`; una suite que ni importa cuenta como fallo, no como skip.
   **Falsificacion medida** (`test_retry`, politica rota en memoria: `RETRY_STATUS=(500,)` con el
   429 fuera): `sano failures=0` -> `roto failures=8`, primer fallo
   `el reintento devuelve la respuesta del segundo intento: None, esperaba {'ok': True}`.
2. `lint_harness`: **falsificado** sobre un arbol sintetico con un fichero de 401 lineas ->
   `R2 big.py:0 401 lines > 400`, `files=1 findings=1`, exit **1**. La ley de 400 muerde.
3. Historia de `.ai/HARNESS_RUBRIC.json` (3 commits): ningun umbral bajado. Hay dos subidas
   documentadas arriba (`frozen-engine` y `installer`) y un `contains` endurecido
   (`failures=0` -> `suites=17 failures=0`, hoy `(same as the source)`). Cero borrados de pruebas:
   `git log -S xfail -S skip` sobre las suites no devuelve nada.

Exit codes de esta revision: `lint_harness` 0 · `selftest` 0 (20 suites) · `verify` 0 ·
`verify --frozen` 0 · `report` 0 · `report --check` 0 · `status` 14/14.

## Por qué esto prueba el protocolo Nexus

Porque el turno de noche **no puede hacer trampa sin que se note**: cada afirmación suya deja un exit
code en `.ai/HARNESS_STATE.json`, cada cambio deja un commit, y `nightshift report` reconstruye la
noche desde los datos, no desde el relato. Si el agente se equivoca, la rúbrica lo dice por la mañana.
