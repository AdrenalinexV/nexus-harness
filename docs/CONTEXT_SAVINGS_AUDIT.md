# Auditoría del ahorro de contexto y activación de los 4 motores

Fecha: 2026-10-27 · Base: `e652097` (v1.0.0) · Todo lo de este documento está **medido hoy** con
`tools/audit_context.py`, `python -m nexus_harness selftest` y `tools/benchmark_ab_savings.py`.
Ninguna cifra viene de la interfaz ni de una estimación: cada una tiene su comando detrás.

---

## PASO 1 · Auditoría: qué hacía el motor en cada turno

### 1. Por qué `Nexus-Harness` tenía 411.886 consumidos y **0** evitados

**Porque el libro de turnos no tenía ni un campo de ahorro.** Medido:

```
$ python tools/audit_context.py
P1) El libro de turnos guarda: at, completion_tokens, exit, gate, judge, project, prompt_tokens,
    repairs, session, source, steps, tokens, touched
    Campos de ahorro/baseline en el libro: NINGUNO
```

`ledger.py` calculaba `prompt_tokens`/`completion_tokens` de cada turno y nada más. La tarjeta «tokens
evitados» no leía el motor: leía **el ledger de dinero del gobernador**, que cuenta otra cosa (bloqueos
de sus gates, no bytes podados por el arnés). El arnés contribuía 0 porque nunca escribía esa métrica.

### 2. Por qué la tarjeta decía 3.653.208 y las barras verdes sumaban 1.091.148

**Porque eran dos fuentes distintas y ninguna declaraba la diferencia.** Medido:

```
P2) Tarjeta (ledger del gobernador): 3653208 tokens evitados
    Suma de barras verdes (impact panels): 1091148 -> desvio declarado
    Nexus-Harness en barras: 0
```

La tarjeta salía de `money.avoided_tokens` (contabilidad de dinero del gobernador, todos sus turnos) y
las barras de `impact.panels[].tokens_blocked` (por proyecto, otra definición). Desvío: 2.562.060
tokens. Dos números distintos en la misma pantalla, sin nota que los reconcilie.

### 3. ¿El historial viajaba entero en cada paso (O(N²))?

**Sí, y se puede medir sin llamar a ningún modelo.** Turno sintético de 8 pasos con lecturas realistas
y el mismo contador que usa el motor (`compaction.estimate`):

```
P3) A sin poda: [862, 1617, 2372, 3128, 3883, 4638, 5393, 6149]  (total 28042)
    B con poda: [862, 1617, 1667, 1717, 1767, 1817, 1867, 1917]  (total 13231) -> ahorro 52.8%
```

La serie A crece +755 tokens por paso (cada paso reenvía TODO lo anterior); la B se aplana. La poda
existía desde la noche anterior (`relay_state.prune_tool_outputs`) pero **no medía nada** y en el chat
no se aplicaba al nivel de paso: ahora es `context_pruner.prune`, corre en cada paso del chat y del
Obrero, y devuelve los bytes ahorrados.

### 4. Por qué los turnos medidos salieron bloqueados

Tres corridas del bucle autónomo (6 filas porque cada una estaba escrita **dos veces**):

```
Nexus-Harness  turnos=6  tokens=411886  verdes=0  bloqueados=6
```

- **Doble contabilidad**: `Triad._record` y `autonomy._cycle` escribían la misma corrida. 411.886 =
  2 × 205.943. Arreglado: una fila por corrida (`recorded`) + `ledger.dedupe()` para el historial ya
  escrito.
- **`session_10` y `session_13`**: gate verde, **Juez en contra** por «JSON malformado» — el modelo
  razonaba y devolvía dos bloques `{...}`; la regex `\{.*\}` los unía y `json.loads` fallaba. Arreglado
  `parse_verdict`: escaneo de llaves, comas finales, comillas curvas y veredicto explícito.
- **`session_11`**: gate rojo real — el Obrero escribió un caso de test con un supuesto equivocado
  (`keep_last`). Ese rojo era correcto y así se reportó.
- **«0 runs verdes»**: con las tres corridas fallando por lo anterior, el anillo no podía pintar otro
  color. Hoy hay una corrida **verde** medida (modo B del benchmark) además de las suites.

---

## PASO 2 · Los 4 motores, conectados y medidos

| Motor | Dónde vive | Qué recorta de verdad |
|---|---|---|
| 1 · Skills dormidas | `savings.skill_index` + `skill_router` (techo 10) | el índice de **173 skills ≈ 3.369 tokens por request** que un harness tradicional manda; en su lugar viaja el brief de las ≤10 que aplican |
| 2 · Poda deslizante | `context_pruner.prune` (últimos 2 pasos intactos) | cada salida vieja → `[Compactado por Nexus: read_file 'x.py' L1-180 (4.210 chars -> 133 chars) \| sha256:… \| Re-lee si necesitas lineas exactas]` |
| 3 · Repo-Map AST | `repo_map.py` inyectado en `chat._system` y `triad._system` | el modelo pide `read_file(offset, limit)` en vez de leer ficheros enteros para buscar una función |
| 4 · Obrero aislado | `repair_guard.isolated_repair` | la reparación corre sobre una **copia** del transcript en su worktree: al hilo principal solo vuelve una línea |

El motor 3 se cuenta como **coste** (declarado) y no como ahorro: no se puede medir lo que el modelo
no leyó, y atribuirse lecturas hipotéticas sería inflar la cifra.

---

## PASO 3 · Contabilidad por request

Cada llamada al modelo se cierra en `savings.SavingsLedger`:

```
baseline = sent − repo_map + skills_dormidas + podado + aislado
tokens_saved = baseline − sent        context_multiplier = baseline / sent
```

y viaja al libro de turnos con nombre propio: `tokens_sent`, `tokens_baseline`, `tokens_saved`,
`savings_pct`, `context_multiplier`, `dormant_tokens`, `pruned_tokens`, `isolated_tokens`,
`repomap_tokens`, `requests`. El agregado suma por proyecto y ahora **una sola fuente alimenta la
tarjeta y el gráfico**; lo del gobernador se enseña aparte, etiquetado como suyo.

La tabla de extrapolación vive en `stats_savings.cost_table` con precios **declarados** (DeepSeek
V4.1 Flash 0,25/1,00 · Claude Sonnet 4 3,00/15,00 · GPT-5 / o3 2,50/10,00 USD por 1M entrada/salida) y
una fila local que no es dinero: KV-cache (`0,25 MB/token` de 27B) y segundos de prefill
(`3.000 tok/s` declarados para la RTX 5070 Ti).

---

## PASO 4 · Calibración del Gate/Juez

1. `parse_verdict` ya no pierde un veredicto por formato (su suite cubre: dos objetos, coma final,
   comillas curvas, JSON truncado y «sin declaración → reject»). Prueba en producción: el turno real de
   chat de este informe quedó en `judge: approve` con la nota «veredicto leido de una respuesta con JSON
   roto» — antes eso era un rechazo.
2. Una corrida ya no se cuenta dos veces (regresión en `test_savings`).
3. El bucle distingue «gate rojo» de «Juez en contra» al reportar.
4. **El Obrero ahora sabe con qué se le mide**: `triad_brief.proof_block` inyecta el comando de test del
   proyecto en su system prompt («Deja ESA comprobacion en verde»). Medido antes y después con el mismo
   escenario: el modelo que sólo arreglaba lo que decía el enunciado (`add`) dejaba el test en rojo por
   la segunda función; con el comando delante, `qwen3.8-27b` arregló las dos y el turno salió **verde a
   la primera** (gate exit 0, 55,5 % de ahorro, ×2,25 de contexto).
5. **Ciclo «rojo → reparado en el worktree → verde», probado**: `tools/prove_repair_cycle.py` construye
   un proyecto donde el primer intento tiene que fallar (el test exige dos funciones, el enunciado una).

   ```
   $ python tools/prove_repair_cycle.py --fake
   gate_verdicts: ["exit 10", "exit 0"] · sandbox_used: true · promoted: 1 · exit: 0 · cycle: true
   ```

   Con modelos reales: `kat-coder-35B` no reparó (su turno de sandbox no escribió nada: `promoted: 0`,
   tres gates rojos) y `qwen3.8-27b` no necesitó reparar (verde a la primera). Las dos cosas se dicen
   porque las dos ocurrieron; el mecanismo está probado, y si se usa depende del modelo.

## PASO 4-bis · Coherencia del panel (defecto encontrado al leerlo)

Al renderizar la pantalla sin navegador (`tools/render_stats.py`, nuevo) apareció lo mismo que en la
tarjeta: **la barra de «enviados» dibujaba 0** al lado de 4.859 evitados, porque el agregado guardaba el
bucket como `sent` y el gráfico leía `tokens_sent`. Arreglado con los mismos nombres en los dos sitios y
con regresión (`test_the_bars_and_the_card_read_the_same_number`). Y «Runs verdes del gate» leía sólo
los `impact panels` del gobernador, así que el turno verde medido hoy no salía: ahora sale del libro del
arnés cuando ese proyecto tiene turnos, y del gobernador cuando no.

---

## PASO 5 · Benchmark A/B en vivo

`python tools/benchmark_ab_savings.py --steps 8` · mismo modelo, misma tarea, mismo proyecto git
(`calc.py` con un defecto real), dos modos: A = `nexus_engines=False`, B = los 4 motores.

| medida | A (tradicional) | B (Nexus) | diferencia |
|---|---|---|---|
| tokens de prompt enviados | 36.673 | 15.451 | **−57,9 %** |
| prompt máximo alcanzado | 6.544 | 3.589 | **−45,2 %** |
| vida de la ventana | ×1 | ×1,82 | ventana 60k efectiva ≈ 109k |
| tokens por paso | 6.112 | 3.090 | **−49,4 %** |
| gate verde | sí | sí | los dos terminan la tarea |
| Juez | aprueba | aprueba | — |

Dentro del modo B, el baseline por request que él mismo calcula da **52,4 % de ahorro** y
**×2,1 de contexto efectivo** (6 requests). Informe crudo: `docs/BENCHMARK_AB.md` y
`.nexus/harness/benchmark_ab.json`.

**Límite declarado, y es importante:** corrió en el **modelo local** porque esta máquina no tiene clave
`DEEPSEEK_API_KEY` ni `OPENROUTER_API_KEY` (la bóveda tiene una sola clave, `TYPESAFE_API_KEY`). El
arnés ya sabe hacerlo en la nube: basta con meter la clave en la bóveda desde `⚙ Configuración →
Seguridad` y volver a lanzar el benchmark con `--vendor deepseek`; el modo de medida es el mismo y la
tabla de costes se recalcula sola. No se ha inventado ninguna llamada de nube.

---

## Qué cambió en el código (y su prueba)

| pieza nueva | fichero | prueba |
|---|---|---|
| poda con recibo medible | `nexus_harness/context_pruner.py` | `python tools/proofs.py savings` |
| contabilidad por request + baseline | `nexus_harness/savings.py` | idem |
| mapa AST + prompts extraídos | `nexus_harness/triad_brief.py` | idem |
| pantalla de ahorro + extrapolación | `nexus_harness/stats_savings.py` | idem |
| auditoría reproducible | `tools/audit_context.py` | `python tools/audit_context.py` |
| benchmark A/B | `tools/benchmark_ab_savings.py` | `python tools/benchmark_ab_savings.py --doc-only` |
| ciclo rojo→reparado→verde | `tools/prove_repair_cycle.py` | `python tools/prove_repair_cycle.py --fake` |
| panel legible sin navegador | `tools/render_stats.py` | `python tools/render_stats.py` |
| modo tradicional medible | `config.nexus_engines` | `python -m nexus_harness selftest savings` |

Criterios de rúbrica nuevos: `savings-engines` → `python tools/proofs.py savings` (`failures=0`) y
`repair-cycle` → `python tools/prove_repair_cycle.py --fake` (`"cycle": true`).
