# Auditoría comparada profunda vs el estado del arte

> Nexus-Harness v1.1.0 (`f8a2491`) contra los harnesses de referencia, 2026-10-29.
> Fuentes de terceros: estudio a nivel de fuente de **11 sistemas** (arXiv **2609.00006**) + estado público
> Oct-2026 de cada producto. Fuentes propias: `verify.py`, `docs/BENCHMARK_AB.md`,
> `docs/CONTEXT_SAVINGS_AUDIT.md`, `docs/EVAL.md`, `docs/VERIFICATION.md`.
> Este documento **no** repite el dossier de marketing: profundiza en los tres ejes que importan al
> proyecto — **ahorro de tokens, longitud de contexto efectiva, calidad de resultado** — más **autonomía**,
> **skills** y **MCP**, y termina con un **prompt de traspaso**.

---

## 0. Método

- **Ejes propios medidos:** A/B de ahorro (mismo modelo, misma tarea, 2 modos), eval de capacidad (7
  tareas golden), `verify` (62 suites).
- **Rivales:** no medidos en esta máquina; se comparan por **diseño público documentado** (lo que dicen sus
  papers, docs y repos). Se declara siempre cuándo un número es de ellos y cuándo es nuestro.
- **Regla:** una ventaja solo cuenta si hay un comando detrás. Lo que no se puede reproducir, se etiqueta
  como **afirmación de tercero**, no como hecho medido.

---

## 1. Los siete subsistemas, cara a cara

| subsistema | Nexus (medido) | Claude Code | Codex CLI | OpenCode | DeepSeek `dsh` | Hermes |
|---|---|---|---|---|---|---|
| **Bucle** | `while` con presupuesto, gate antes de juez, parada por criterios | streaming + batching por seguridad de concurrencia | SM async Tokio, FuturesOrdered | log-as-queue `while(true)`, resumible | plugin loop | while con stop-guards + verify-on-stop |
| **LLM** | 3 wires, 6 vendors, **sin streaming**, caché medida | 1 vendor, prompt-cache con forks | 1 vendor, Responses API | 9 prompts por familia | modelo-agnóstico | 5 transports, 29 perfiles |
| **Herramientas** | ~16 + MCP + delegate; fuzzy 8 peldaños, patch V4A atómico | 43 tipadas, LSP, deferred loading | 25–30, apply_patch unificado | 17, **LSP como tool** | plugin | 69 |
| **Contexto** | 4 motores + **baseline medido** | 4 estrategias de compaction | compact pre/mid/remote | SQLite + resumen | plugin | lineage compaction |
| **Seguridad** | worktree sí, **proceso no** | 5 modos de permiso, sandbox opt-in | **sandbox de SO 3 plataformas** | permisos por defecto laxos | sandbox plugin | 6 backends |
| **Orquestación** | `delegate_task` depth 1, 3 hijos | subagentes recursivos + worktrees + teams | agentes + guardián | subagentes task | plugin | orquestador por config |
| **Extensibilidad** | MCP sí; **plugins/hooks no** | hooks+plugins+MCP+skills (el más profundo) | profiles+hooks+MCP+subagentes | MCP+temas | **todo es plugin** | 6 backends + skills |

**Lectura:** en **cinco** de siete subsistemas vamos por detrás en *funcionalidad*; en **uno** (contexto)
empatamos o ganamos por medición; en **uno** (gobernanza, que aquí no es fila propia porque el paper no lo
contempla) somos únicos.

---

## 2. Eje A — Ahorro de tokens y longitud de contexto (la intención original)

**Lo que hacemos, medido:**

```
A/B (mismo modelo, misma tarea, calc.py con defecto real):
  tokens de prompt enviados   A=36.673   B=15.451   →  −57,9 %
  prompt máximo alcanzado     A=6.544    B=3.589    →  −45,2 %
  vida de la ventana          ×1         ×1,82      →  ventana 60k efectiva ≈ 109k
  tokens por paso             A=6.112    B=3.090    →  −49,4 %
  por request (modo B):       52,4 % de ahorro, ×2,1 de contexto
```

Cuatro motores, cada uno con su recibo:
1. **Skills dormidas** — 180 skills indexadas: 3.561 tokens de índice vs 451.606 de cuerpos.
2. **Poda deslizante** — cada salida vieja → recibo `read_file 'x.py' L1-180 (4.210→133 chars) | sha256`.
3. **Repo-Map AST** — contado como **coste** declarado, no como ahorro (honestidad: no se atribuye lo que
   el modelo no leyó).
4. **Obrero aislado** — la reparación ocurre en su worktree; al hilo principal vuelve una línea.

**Lo que hace la competencia:**
- **Claude Code / Codex:** *prompt caching* de prefijo (descuento real de dinero) + compaction
  multi-estrategia + truncación de salidas. Es una palanca **distinta y fuerte**: pagan menos por lo mismo
  repetido.
- **Nosotros:** además del prefijo estable, **medimos cuánto habría viajado sin el arnés**. Eso es lo que
  nadie publica.

**Veredicto honesto (eje A):** estamos **a la par en el efecto** (ambos reducen el coste real) y **por
delante en la evidencia** (nadie da `savings_pct`/`context_multiplier` con baseline). **Pero** nuestro
número está medido **en local**, sin clave de nube: falta el A/B en la nube para que sea incontestable.

**Para superarles en este eje:** (a) A/B con clave en la nube y caché contada como dinero; (b) tokenizer
real por familia (hoy `chars/4` es fallback declarado, ±20–30 % de error); (c) publicar el recibo como
página legible — que el ahorro se vea, no solo se mida.

---

## 3. Eje B — Calidad de resultado (¿termina bien la tarea?)

**Lo que hacemos, medido:** `gate` determinista (exit 0/10/20) **antes** del juez; juez **distinto** del
obrero obligado a un veredicto corto; fail-closed (sin backup no se edita, rojo no se promociona). Eval:
**7/7 tareas golden** con modelo local a temperatura 0. Ciclo rojo→reparado→verde probado
(`prove_repair_cycle.py --fake` → `cycle: true`).

**Lo que hace la competencia:**
- **Claude Code / Codex:** el fin del turno es `end_turn` — el modelo declara que terminó. Hay hooks y
  reviews, pero **no un gate determinista que devuelva un exit code por criterio como artefacto**.
- **Eval:** nadie del panel publica un set golden reproducible por rol. **Pero eso no nos da la ventaja**:
  7 tareas es un instrumento, no un benchmark.

**Veredicto honesto (eje B):** en **calidad bruta de resultado** vamos por detrás — ellos tienen más
herramientas, LSP y mejor gestión de contexto, así que resuelven más tipos de tarea. En **confianza en el
resultado** vamos por delante — sabemos *cuándo* terminó bien, con prueba. **La ventaja es de confianza, no
de capacidad**; y hay que decirlo así.

**Para superarles en este eje:** subir el eval a **~20 tareas golden en 3 lenguajes** con **una tarea
negativa** (debe terminar roja), y publicar la tabla por modelo/rol. Sin eso, «mejor calidad» es una
opinión; con eso, es un dato.

---

## 4. Eje C — Autonomía (lo último que habéis implementado)

**Lo que hacemos:** daemon por cola (`task add` → `daemon`), spec sintetizada a **criterios ejecutables
validados antes de congelar**, plan en **DAG** (≤7 nodos, ciclos rechazados), **parada por criterios y no
por reloj**, y **consulta bidireccional real** (Telegram con offset persistido / Discord / endpoint HTTP)
con **default declarado** al expirar — `parar` por defecto: un bucle desatendido no inventa consentimiento.

**Lo que hace la competencia:**
- **Hermes:** daemon residente maduro, triggers, presupuesto, verify-on-stop. **Más rodado que el nuestro.**
- **Claude Code:** «scheduled routines» y CI — autonomía **gestionada**, no un daemon propio.
- **OpenCode:** **sin autonomía de fondo** real. **Aider:** mono-agente, sin daemon.
- **DeepSeek `dsh`:** background tasks por plugin; el scheduling es un plugin más.

**Veredicto honesto (eje C):** aquí **competimos de verdad**. La «autonomía que pregunta con default
declarado» es un diseño que no he visto formulado igual en el panel: convierte el bloqueo en una decisión
con plazo en vez de un cuelgue o una invención. **Ventaja real, y recién nacida** (hay que endurecerla:
sin CI, sin replays, con un solo worker).

**Para superarles en este eje:** hacer la autonomía **demostrable** — un `demo` que corre un ciclo completo
(objetivo → spec → DAG → trabajo → gate → consulta → respuesta) y graba el transcript con exits. Hoy la
autonomía se puede ejecutar pero no se puede *mostrar* en 90 segundos.

---

## 5. Skills y MCP: ¿foso o commodity?

- **Skills** (SKILL.md con divulgación progresiva): **9/11** harnesses del estudio las tienen. Nuestra
  implementación (índice dormido, techo, catálogo en disco) es correcta pero **no única**. **El matiz que
  sí es único:** somos el único que **cuantifica los tokens que las skills ahorran** (180 → 3.561 vs
  451.606). La feature es commodity; la *medición* de la feature es nuestra.
- **MCP** (cliente nativo, `mcp__<server>__<tool>`, con `nexus_status/lint/relay` de serie): **8/11** lo
  tienen. **Tampoco es foso.** Nuestra diferencia es que el servidor MCP por defecto es **el propio
  gobernador del protocolo**, no un conector genérico.

**Conclusión:** skills y MCP **no diferencian** en 2026 — son mesa de entrada. Venderlos como foso nos
pondría en ridículo ante cualquiera que haya usado Claude Code. Lo que diferencia es **medirlos**.

---

## 6. Tabla de veredicto por eje (dónde estamos y por qué)

| eje | estado | evidencia | ¿copiable? |
|---|---|---|---|
| Ahorro de tokens | **líder en evidencia**, a la par en efecto | −57,9 %, baseline por request | contaminación: ellos tienen caché; nosotros el recibo |
| Longitud de contexto | **a la par**, medido | ventana ×1,82 | sí (compaction), menos el baseline |
| Calidad de resultado | **por detrás en capacidad, por delante en confianza** | gate+juez+exit; eval 7/7 | la confianza sí es copiable, cuesta |
| Autonomía | **competitivo, recién nacido** | daemon + spec + consult con default | sí, pero el diseño «pregunta con plazo» es raro |
| Skills | **commodity**, medición única | 180 skills indexadas | sí |
| MCP | **commodity** | cliente nativo | sí |
| Gobernanza/verificación | **único** | exit por criterio como artefacto | copiable solo copiando la filosofía |

**Nota global:** 6,0/10 simple · **7,0/10 ponderado**. Podio del mercado ≈ 8,0. Nos separan **dos cosas de
ingeniería** (sandbox, LSP+streaming) y **una que no se programa** (ecosistema/adopción).

---

## 7. Qué haría falta para superarles (no solo acercarse)

1. **Ser el único demostrable.** Sandbox de proceso + mutation smoke + eval de 20 tareas publicada. Nadie
   reúne las tres; quien lo haga define el estándar de confianza del sector.
2. **Convertir el ahorro en espectáculo.** El recibo como página: «este turno costó X, sin el arnés habría
   costado Y». El eje A es la intención original del proyecto y **hoy se mide pero no se enseña**.
3. **Paridad funcional mínima** (LSP + streaming) para que la ventaja de confianza no se lea como excusa de
   falta de capacidad.
4. **Publicar y dejar que la comunidad muerda** (remoto + CI + CHANGELOG). Sin esto, todo lo anterior es un
   secreto entre tú y tu PC.

---

## 8. Prompt de traspaso (pegar en una conversación nueva)

```
Eres el Arquitecto Principal de Nexus-Harness. Repo: C:\Proyectos\Nexus-Harness (Python, 0 deps,
v1.1.0, commit f8a2491). Suite verde: `python tools/verify.py` → lint 0 hallazgos / 62 suites / 0
ficheros >400 líneas. Perfil Hermes: nexus-harness.

LEYES: (1) ningún fichero >400 líneas; (2) nada se declara hecho sin un comando que lo pruebe (exit 0);
(3) ejecución continua, sin pedir permiso entre fases; (4) economía de contexto (scripts atómicos).

ESTADO (2026-10-29): el motor está terminado. Somos UNICOS en gobernanza/verificación (gate con exit
0/10/20 ANTES de un juez distinto, ledger por turno, ahorro de contexto con baseline: −57,9 % de tokens
medido, ventana ×1,82). Estamos a la par en skills y MCP (commodity en 2026: 9/11 y 8/11 harnesses los
tienen). Vamos POR DETRÁS en: sandbox de proceso (el agujero nº1), LSP, streaming, plugins/hooks y
ecosistema (sin remoto, sin CI, sin CHANGELOG). Autonomía (daemon + spec sintetizada + consult
bidireccional con default declarado) es competitiva y recién nacida.

MISIÓN: llevar el proyecto de 7,0/10 ponderado a 8/10 y hacerlo DEMOSTRABLE, en este orden estricto:
  1. Publicar: remoto git + CI (.github, Windows+Linux, repo recién clonado en verde) + CHANGELOG + LICENSE.
  2. Capas con invariante de dependencia (core/llm/tools/context/verify/autonomy/spec/learning/platform);
     un paquete por commit, gate verde entre cada uno. El techo de 400 líneas duele porque el árbol es plano.
  3. Streaming: el transporte devuelve un ITERADOR de eventos (delta/reasoning/tool_call/done) y Reply se
     construye plegándolos; un solo camino, dos modos. Cancelación real por el botón Detener.
  4. Sandbox de proceso como PUERTO fail-closed (Windows Job Object/AppContainer, Linux bwrap+Landlock,
     macOS Seatbelt). Si no hay sandbox, `unrestricted` se rechaza con razón explícita.
  5. Comando `release` que INYECTA las cifras medidas en los docs y falla si un doc contradice la medición.
  6. Gobernanza a 10: autodetección de runner + test de humo generado + mutation smoke (mutar 3 líneas y
     exigir que algún test se ponga rojo; si no, el verde no vale nada).
  7. Hooks/plugins reutilizando el contrato del hook que YA existe (JSON in, mensaje out, exit 0/10/20/30):
     before_turn / after_tool / before_commit / pre_verify vía nexus_harness.toml.
  8. Eval a ~20 tareas golden en 3 lenguajes, con UNA tarea negativa que debe terminar roja.

LEE PRIMERO: docs/ARCHITECTURE_V2_PROPOSAL.md, docs/COMPETITIVE_AUDIT_V2.md, docs/DOSSIER_RELEASE.md,
docs/FUTURE_AUDIT.md, docs/CONTEXT_SAVINGS_AUDIT.md. Método de referencia: skill agent-harness-engineering.

VECTORES DE RIESGO CONOCIDOS: dos escritores sobre el mismo estado en .nexus/harness/*.json (namespacear,
re-leer antes de escribir); bytecode cacheado hace que un fichero arreglado parezca roto (PYTHONPYCACHEPREFIX
fresco por gate); el prefijo del prompt debe ser idéntico en los N pasos de un turno o se pierde la caché.

EMPIEZA por el paso 1. Antes de cada cambio real, di qué vas a tocar; después, ejecuta el comando que lo
prueba y pega el exit. Sin ceremony.
```

---

*Auditoría generada el 2026-10-29. Cifras propias reproducibles con `verify.py`, `tools/benchmark_ab_savings.py`
y `tools/eval.py`. Comparativas de terceros: arXiv 2609.00006 + docs públicas de cada producto.*
