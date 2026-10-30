# Nexus-Harness · Dossier de release y posicionamiento

> Simulación honesta de dossier de marketing **y** de realidad. No hay una cifra aquí que no salga de un
> comando. Fecha de medición: **2026-10-29**. Base: `f8a2491` (v1.1.0).
> Todo lo que dice «medido» se puede reproducir con `python tools/verify.py`.

---

## 0. Resumen ejecutivo (si solo lees esto)

**Qué es.** Un harness de ingeniería autónoma en Python puro (0 dependencias), donde el Protocolo Nexus
**es el bucle de turno**: enrutado de skills antes de cada llamada, lint determinista como *gate*, y una
sesión que se releva sola al llenarse. Se instala como app de Windows y también corre por CLI y cabina web.

**El foso real.** No es «hace el trabajo mejor». Es que **el trabajo no se cierra con palabras, se cierra
con un recibo**: cada turno deja `exit 0/10/20` por comprobación, un juez distinto del obrero, y
contabilidad de tokens por request con baseline. **Ninguno de los once harnesses del estudio de referencia
publica el código de salida de cada criterio como artefacto del trabajo.**

**Veredicto sin adornos.**

| pregunta | respuesta |
|---|---|
| ¿Somos el mejor harness? | **No.** En código puro y orquestación agéntica, Claude Code y Codex están por delante. |
| ¿En algo somos los mejores? | **Sí, dos ejes: gobernanza/verificación y contabilidad de contexto/coste.** Ahí nadie ha publicado un equivalente. |
| ¿Un «10/10» global es alcanzable? | **No tal cual.** Nadie lo tiene hoy (el techo real del mercado es ~8). Pero **10/10 en nuestros dos ejes sí es alcanzable y cerrable**, y un **8/10 global sí** con 2–3 meses de la fase P1. |
| ¿Se puede hacer un release ya? | **Sí, pero honesto: `0.x / developer preview`**, no un 1.0 de marketing. El motor está; el producto alrededor (CI, changelog, sandbox de proceso, ecosistema) no. |
| Nota global de hoy | **6.0/10** (media simple) · **7.0/10** ponderado por lo que importa (gobernanza + coste + autonomía). |

**La frase de una línea:** *las demás herramientas son empleados muy listos; esta es un empleado muy listo
con un inspector que no cobra de la obra.* Y ahora mismo: un inspector excelente, para una obra todavía
pequeña.

---

## 1. Qué se ha medido (no estimado)

```
$ python tools/verify.py
lint      exit 0   files=224 findings=0 max_lines=400 ignored_runtime=0
selftest  exit 0   suites=63 failures=0
verify: GREEN

$ python -c "from nexus_harness.savings import skill_index; print(skill_index(force=True))"
{'skills': 180, 'index_tokens': 3561, 'body_tokens': 451606, ...}

$ python -m nexus_harness --help
run serve chat checkpoint selftest lint models gate relay spec daemon task notify bridge consult
```

| dato | valor | fuente |
|---|---|---|
| Suites deterministas | **63, 0 fallos, sin red** | `verify.py` |
| Hallazgos de lint / ficheros > 400 líneas | **0 / 0** en 224 ficheros | `verify.py` |
| Dependencias de terceros | **0** | `pyproject.toml` |
| Líneas de fuente | ~21.300 (motor) · ~27.500 (con tools/apps) | `wc -l` |
| Módulo más largo | 399 líneas (techo 400) — *en el techo* | `wc -l` |
| Proveedores | 6 (`lmstudio`, `ollama`, `openai`, `deepseek`, `openrouter`, `anthropic`) | `providers.py` |
| Wires de transporte | 3 (`openai_compat`, `ollama`, `anthropic`) + `http` | `transports/` |
| Herramientas del agente | ~16 nativas + MCP dinámico + `delegate_task` | `tools.py` |
| Skills indexadas | **180** → 3.561 tokens como índice / 451.606 como cuerpos | `savings.py` |
| Eval de capacidad | **7/7 tareas golden** resueltas (run real, modelo local, temp 0) | `docs/EVAL.md` |
| A/B de contexto | **−57,9 % de tokens de prompt** vs harness tradicional (misma tarea) | `docs/BENCHMARK_AB.md` |
| Instalador | `NexusHarness-Setup-1.0.0.exe` (~20 MB, motor congelado) | `dist/` |

**Lo que NO está verde, y se dice:** sin sandbox de proceso, sin streaming de tokens, sin LSP, sin
sistema de plugins/hooks. Y las llamadas en la nube (openai/deepseek/…): **no verificadas en vivo** (no
hay clave en esta máquina) — solo se prueban su construcción y sus parsers.

**Lo que sí está y esta edición corrige:** CI en Windows y Linux (`.github/workflows/verify.yml`),
`CHANGELOG.md` y remoto público (`AdrenalinexV/nexus-harness`) existen desde la publicación; las tres
frases que decían lo contrario se quedaron de la instantánea anterior. Y la media de §3 se publicaba
6,0/7,0 mientras su propia matriz daba otra cosa: ahora la escriben las filas, no la mano.

---

## 2. La categoría: dónde jugamos

Estudio de referencia: *«Harness Engineering: Anatomy, Architecture, and Evolution of Coding Agents»*
(arXiv **2609.00006**), anatomía a nivel de fuente de once sistemas productivos — Claude Code, Codex CLI,
Gemini CLI, Mistral Vibe, OpenHands, Aider, Mini-SWE-Agent, Hermes, Pi, OpenCode, OpenClaw. No los
puntúa; los describe. Define **siete subsistemas canónicos** de todo harness:

**bucle del agente · integración LLM · herramientas · memoria/contexto · seguridad/permisos ·
orquestación · extensibilidad.**

Ese es el mapa. Un «10/10» significa: **sin agujeros en los siete, y líder en al menos uno.** Nadie del
panel los tiene todos llenos a la vez. Nosotros somos fuertes en dos y tenemos agujeros claros en tres.

Estado Oct-2026 de los rivales relevantes (fuentes públicas, no opinión):

- **Claude Code** — TS, cerrado, ~43 herramientas, prompt-cache con forks, subagentes recursivos con
  worktrees, 5 modos de permiso, el sistema de extensión más profundo (CLAUDE.md, skills, hooks, MCP,
  plugins). Sin sandbox de proceso por defecto.
- **Codex CLI** — Rust, Apache-2.0, **el único con sandbox a nivel de SO en 3 plataformas** (Seatbelt /
  bwrap+seccomp / token restringido Windows); red apagada por defecto; guardián-subagente que revisa
  acciones. ~25 herramientas.
- **OpenCode** — MIT, el agente de código dedicado con más estrellas (**~220K**), 75+ proveedores, **LSP
  como herramienta de primera** (diagnósticos), sesiones en SQLite, cliente/servidor. Permisos por defecto
  más permisivos; sin sandbox de SO.
- **DeepSeek Harness (`dsh`)** — MIT, developer preview, **«todo es un plugin»** sobre el runtime Cordis
  (modelos, herramientas, skills, sandboxes, UI). Modelo-agnóstico (OpenAI-compatible). ~264K estrellas.
  Aviso propio: *cambios incompatibles garantizados*; riesgo de cadena de suministro de plugins.
- **Hermes** (el harness sobre el que corre este proyecto) — Python, el de crecimiento más rápido;
  bucle con presupuesto, skills auto-mejorables, verify-on-stop, 6 backends.
- **Aider** — Python, el veterano de edición polimórfica; **modo mantenimiento**; mono-agente por diseño.
- **OpenHands / Mini-SWE-Agent / Pi / OpenClaw** — el framework event-sourced, el suelo de 100 líneas, el
  «todo es extensión» minimalista, y el gateway multi-canal.

Dos ausencias que el paper destaca sobre ~4 M de líneas: **ningún runtime usa un framework agéntico
genérico**, y **ninguno recupera código con embeddings vectoriales** — todos van de loop a mano y
recuperación determinista (ripgrep, tree-sitter, glob). Estamos alineados con el estado del arte, no
contracorriente, con nuestro mapa AST + rg y sin vector DB.

---

## 3. La matriz: rúbrica por eje (1–10)

Escala: 1 = no existe · 5 = funcional pero con agujeros · 8 = competitivo · 10 = estado del arte hoy.
Las notas de terceros salen de sus fuentes públicas; las nuestras, de lo medido arriba. **Ponderación:
contexto y gobernanza pesan ×1,5** (es donde se decide el coste y la confianza).

| eje (peso) | **Nexus** | Claude Code | Codex CLI | OpenCode | DeepSeek `dsh` | Hermes | Aider |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **Código** (edición fina, diffs, LSP) ×1,5 | 6 | **9** | 9 | 8 | 7 | 7 | 7 |
| **Tareas** (resolver end-to-end) ×1,5 | 6 | **9** | 8 | 8 | 8 | 8 | 6 |
| **Agéntico** (loop, subagentes, paralelo, streaming) ×1,5 | 5 | **10** | 9 | 7 | 8 | 8 | 4 |
| **Autonomía** (background, triggers, sin humano) ×1,5 | 7 | 7 | 7 | 5 | 6 | **8** | 3 |
| **Gobernanza/verificación** (evidencia, gate, juez) ×1,5 | **9** | 5 | 4 | 3 | 3 | 6 | 3 |
| **Contexto/coste** (compaction, caché, ahorro) ×1,5 | **8** | 9 | 9 | 7 | 7 | 8 | 6 |
| **Seguridad/aislamiento** ×1,0 | 4 | 5 | **10** | 3 | 4 | 4 | 2 |
| **Extensibilidad** (plugins, hooks, MCP, skills) ×1,0 | 5 | **10** | 8 | 8 | **10** | 9 | 4 |
| **Ecosistema/madurez** ×1,0 | 2 | **10** | 8 | 9 | 8 | 9 | 7 |
| **Portabilidad/DX** (instalar, 0 deps, superficies) ×1,0 | 7 | 8 | 8 | 8 | 7 | 7 | 8 |
| **Media simple** | **5,9** | 8,2 | 8,0 | 6,6 | 6,8 | 7,4 | 5,0 |
| **Media ponderada** | **6,1** | 8,2 | 7,9 | 6,5 | 6,7 | 7,4 | 5,0 |

Lectura: **el podio del mercado está en ~8**, no en 10. El único que se acerca al 10 en un eje somos
nosotros, y por partida doble (gobernanza y coste). Nuestro arrastre es un solo número: **ecosistema = 2**.

### Quién es mejor en qué (respuesta directa)

| pregunta | ganador | por qué |
|---|---|---|
| ¿Mejor en **código**? | **Claude Code / Codex** (empate técnico) | LSP + edición por diff + 40 herramientas tipadas; OpenCode cerca por su tool de diagnóstico LSP. |
| ¿Mejor en **tareas** (resolver de punta a punta)? | **Claude Code**, luego Codex / DeepSeek | mayor inventario de herramientas y mejor gestión de contexto multi-estrategia. |
| ¿Mejor **agéntico** (loop, subagentes, paralelismo, streaming)? | **Claude Code** | batching de herramientas por seguridad de concurrencia, subagentes recursivos con worktree, fork sin contaminar contexto. |
| ¿Más **autónomo** (sin humano)? | **Hermes**, con Nexus y Claude Code detrás | daemon residente, triggers, presupuestos; nosotros añadimos cola + spec sintetizada + consult bidireccional. |
| ¿Mejor **gobernanza/evidencia**? | **Nexus-Harness** — único | `exit` por criterio como artefacto, juez distinto obligado, fail-closed, libro por turno. |
| ¿Mejor en **contexto/coste**? | **Claude Code**, con Nexus al lado | ellos tienen prompt-cache de primera; nosotros **medimos** el ahorro por request con baseline. |
| ¿Mejor en **seguridad**? | **Codex CLI** | único con sandbox de SO multiplataforma y red off por defecto. |
| ¿Mejor **extensibilidad**? | **DeepSeek `dsh` / Claude Code** | «todo es plugin» vs hooks/plugins/MCP profundos. |
| ¿Mejor para **modelo libre / local**? | **OpenCode** | 75+ proveedores, ruta local limpia; nosotros 6 y locales primero. |

---

## 4. Dónde ganamos (nuestro foso, dicho sin marketing)

1. **Cierre determinista con recibo.** El gate corre **antes** del juez, devuelve `0/10/20`, y su veredicto
   queda escrito. Un turno que «hizo algo» sin `exit` no puede decir que terminó.
2. **Dos inteligencias que no se creen la una a la otra.** El juez es un modelo distinto del obrero, por
   diseño y por configuración; ve el contenido tocado, no solo la promesa.
3. **Fail-closed de verdad.** Sin backup no se edita; rojo no se promociona; «no puedo probar» es **20**, no
   verde. (El falso verde está tipado como el fallo más caro y atacado explícitamente.)
4. **Contabilidad de ahorro por request.** Baseline, poda con recibo reconstruible, skills dormidas
   (180 → 3.561 tokens de índice en vez de 451.606 de cuerpos), caché medida. **−57,9 %** medido en A/B.
5. **Autonomía que pregunta en vez de inventar.** Cola (`task add`), spec sintetizada a criterios
   ejecutables, parada **por criterios y no por reloj**, y un canal de consulta bidireccional real
   (Telegram/Discord) con **default declarado** al expirar el plazo.
6. **0 dependencias y 400 líneas.** Portabilidad extrema y auditabilidad total (la ley de tamaño se cumple
   sola: 0 infracciones en 224 ficheros).

## 5. Dónde perdemos (honestidad, sin adornos)

1. **Aislamiento del proceso — el agujero nº1.** Aislamos el *árbol* (git worktree); el *proceso* corre en
   el host. Dentro de una política abierta, un comando hostil es el riesgo más grande. Codex lo tiene a
   nivel de kernel; nosotros, una lista de denegaciones.
2. **Sin streaming ni cancelación parcial.** `stream: False` en los transportes. Un turno largo con modelo
   local es una espera opaca; solo se corta entre pasos.
3. **Sin LSP.** El modelo descubre el código con `grep` + mapa AST. OpenCode y Claude Code preguntan al
   servidor de lenguaje (definición, referencias, diagnósticos). Es la diferencia entre «explorar» y «saber».
4. **Ecosistema = 2.** Un autor, un ordenador, **sin remoto git publicado, sin CI, sin CHANGELOG**. En un
   sector donde OpenCode tiene 220K estrellas y `dsh` 264K, «open-code no es open-source» hasta que otro
   pueda clonar en verde.
5. **Sin plugins/hooks.** Terceros no pueden extender sin tocar el core. Es lo que convierte una herramienta
   en plataforma.
6. **Eval de capacidad corto.** 7 tareas golden es un instrumento, no un benchmark. La propia auditoría dice:
   hacen falta ~20 con dificultad graduada para comparar modelos con rigor.
7. **Techo arquitectónico a la vista.** Cuatro módulos a 395–399/400 líneas. La ley funciona, pero la
   próxima feature obliga a dividir *antes* de añadir.

---

## 6. ¿Se puede abordar un «10 de 10»?

Distingamos tres «10» distintos, porque confundirlos es lo que hace mentir al marketing.

### 6a. 10/10 absoluto (mejor en los siete subsistemas): **no, no hoy.**
Nadie lo tiene: Claude Code no tiene sandbox de SO; Codex no tiene la extensibilidad de Claude; OpenCode
no tiene aislamiento; `dsh` es *developer preview* con breaking changes. **El techo real del mercado es ~8.**
Perseguir un 10 absoluto desde un autor único es vender una promesa que el propio mercado no cumple.

### 6b. 10/10 en nuestros dos ejes (gobernanza y coste): **sí, y es cerrable en ~2 meses.**
- Gobernanza 9→10: autodetección obligatoria de runner (el gate **nunca** 0 sin comportamiento ejecutado),
  test de humo generado, matriz de transición rojo→verde, y `mutation smoke` (mutar 3 líneas y exigir que
  algún test se ponga rojo — si no, el verde no vale nada).
- Coste 8→10: tokenizer real por familia de modelo (hoy cae a `chars/4` como *fallback declarado*), y el
  A/B reproducido contra un modelo en la nube con clave, no solo local.

### 6c. 10/10 global: **no por esfuerzo, pero 8/10 sí — y es lo que debería venderse.**
Para pasar de 6,0/7,0 a ~8 hay que cerrar cuatro agujeros, todos de ingeniería, ninguno de talento:

| palanca | eje que sube | de → a | coste | ¿cerrable? |
|---|---|---|---|---|
| **LSP** (definition/references/diagnostics como 3 tools) | Código | 6 → 8 | P1.4, ~2 semanas | **sí** |
| **Streaming + cancelación** por paso | Agéntico | 5 → 7 | ~1 semana | **sí** |
| **Sandbox de proceso** (Job Object/AppContainer en Windows, bwrap en Linux) | Seguridad | 4 → 7 | ~3–4 semanas | **sí**, con trabajo |
| **Plugins/hooks** (`nexus_harness.toml` + puntos `before_turn`/`after_tool`/`before_commit`) | Extensibilidad | 5 → 8 | ~2 semanas | **sí** |
| **CI + CHANGELOG + remote + releases etiquetadas** | Ecosistema | 2 → 5 | ~1 semana | **sí, y es lo primero** |
| **Eval a ~20 tareas golden en 3 lenguajes** | Tareas (credibilidad) | 6 → 8 | ~2 semanas | **sí** |
| **Flota paralela con best-of-N** (worktree por rama, gate por rama) | Agéntico | — | ~3 semanas | **sí** |

### 6d. Lo que **no** se cierra programando (y hay que decir en el release)
- **Ecosistema/comunidad 2 → 10:** depende de adopción, no de código. Ni con diez años de desarrollo
  solitario se compra una comunidad de 220K. Lo realista: 2 → 5–6 con un release público honesto + CI verde
  + un proyecto de ejemplo que se rompe y se arregla delante del usuario.
- **Calidad del modelo:** no es nuestra; un harness es el multiplicador, el modelo es el motor. Nuestro
  argumento es que **medimos** cuál multiplica, no que tengamos el mejor motor.
- **Sandbox multiplataforma a la altura de Codex:** alcanzable en Windows (Job Objects) pero Linux/macOS a
  nivel kernel es un proyecto en sí.

**Conclusión del apartado:** el «10/10» honesto es **«10/10 en lo que nos diferencia, 8/10 global, y
declaramos por escrito los tres ejes donde no lo somos»**. Eso vende más que un 10/10 falso, en un sector
donde el propio paper demuestra que **nadie** tiene los siete subsistemas llenos.

---

## 7. Simulación de release (cómo lo sacaría, si fuera hoy)

**Nivel:** `1.2.0 · developer preview` (no 2.0). Alineado con `dsh`, que se autodeclara igual.

**Mensaje principal (una frase):**
> *Nexus-Harness no te promete el mejor agente. Te promete el único que te enseña el recibo: código de
> salida por criterio, juez distinto del obrero, y cuánto contexto y dinero costó cada turno.*

**Los cuatro argumentos del release (todos medibles, todos reproducibles):**
1. `verify: GREEN` — 63 suites, 0 hallazgos, 0 ficheros > 400 líneas, **0 dependencias**.
2. **−57,9 %** de tokens vs harness tradicional (A/B, misma tarea, mismo modelo).
3. **El recibo**: cada turno con su `exit`, su juez y su coste, archivado.
4. **Autonomía que pregunta**: deja tareas, el daemon las convierte en criterios, trabaja, verifica y te
   consulta por Telegram/Discord cuando duda — con default declarado.

**Sección obligatoria de honestidad (la que da credibilidad, no la que la quita):**
- Sandbox de proceso: **pendiente** (hoy aislamos el árbol, no el proceso).
- Sin LSP, sin streaming, sin plugins/hooks: **en el roadmap P1/P2**, con nombres y módulos.
- Ecosistema: **proyecto de un autor**, sin comunidad todavía. El release busca los primeros usuarios, no
  fingir masa crítica.
- Cloud: probado en construcción y parsers; **llamada en vivo, no verificada** (no hay clave en la máquina
  de medición).

**Qué NO decir en el release (anti-features de marketing):**
- «IA que programa sola y tú te vas». No: es IA que trabaja **y rinde cuentas**; tú decides el encargo.
- «Mejor que Claude Code / Codex». Falso en código y orquestación. Lo honesto: *complementario y
  especializado en verificación y coste*.
- «Open-source» sin remoto, CI ni changelog. Arreglar esos tres **antes** de decir la palabra.

---

## 8. Veredicto final (el que pondría en la portada del dossier interno)

**El motor está terminado y es, en su especialidad, mejor que cualquier harness del estado del arte. Lo que
falta no es motor: es producto alrededor y — sobre todo — cerrar el agujero de aislamiento.** Hoy somos un
**6,0/10 simple, 7,0/10 ponderado**: excelente en dos ejes, flojo en ecosistema, con un agujero de
seguridad claro. Un **8/10 global es realista** con la fase P1 y una semana más de CI/changelog/release.
Un **10/10 absoluto no lo tiene nadie** —y decir lo contrario sería, precisamente, el tipo de mentira que
este harness existe para no tolerar.

> Próximos tres pasos, en orden, sin negociar el orden:
> **1.** Publicar (remoto + CI + CHANGELOG + LICENSE) → deja de ser «open-code».
> **2.** Sandbox de proceso → cierra el agujero nº1.
> **3.** LSP + streaming → sube Código y Agéntico a competitivo.

---
*Dossier generado el 2026-10-29. Cifras propias reproducibles con `python tools/verify.py`, `docs/EVAL.md`,
`docs/BENCHMARK_AB.md` y `docs/VERIFICATION.md`. Notas de terceros: fuentes públicas citadas en §2 y en
`docs/COMPETITIVE.md`.*
