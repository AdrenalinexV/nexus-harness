# Turno de noche — evidencia

Generado por `tools/nightshift.py report` (no se escribe a mano).

- fecha: 2026-10-27T22:08:35Z
- HEAD: `8c338fe`
- iteracion: 179
- criterios: **25/25**

## Rubrica

| criterio | area | que se exige | estado | exit |
|---|---|---|---|---|
| `gate-lint` | gobernanza | La ley de 400 lineas pasa en el propio repositorio | OK | 0 |
| `hook-contract` | multi-harness | Contrato generico `nexus gate --hook` (JSON por stdin, exit 0/10/20/30) | OK | 0 |
| `judge-context` | motor | Juez sensible al contexto y pista con lineas reales al segundo fallo | OK | 0 |
| `relay-auto` | contexto | Relevo automatico: poda al 55% (path/lineas/sha256) y estado verificado al 70% | OK | 0 |
| `repair-cycle` | gobernanza | Un turno que empieza en rojo se repara en el worktree y termina en verde | OK | 0 |
| `savings-engines` | ahorro | Los cuatro motores de ahorro miden tokens reales por request y el libro los guarda | OK | 0 |
| `skills-autonomous` | skills | Skills: techo de 10 en RAM, catalogo dormido y forja con procedencia sha256 | OK | 0 |
| `spec-priority` | gobernanza | Nexus-Harness es el #1 de la cola y su spec congelada esta activa | OK | 0 |
| `suites-source` | gobernanza | Toda la suite determinista pasa desde el codigo fuente | OK | 0 |
| `vps-deploy` | operacion | Deploy VPS por SSH+Compose desde la boveda, secrets.env 0600 y plan en seco | OK | 0 |
| `worktree-isolation` | gobernanza | El Obrero repara en un git worktree y solo promueve con el gate verde | OK | 0 |
| `adapter-aider` | multi-harness | Adaptador Aider: lint/test del gate escritos en su config, verificable | OK | 0 |
| `cost-budget` | operacion | Presupuesto de coste en USD con parada dura antes de cada llamada | OK | 0 |
| `evidence-export` | evidencia | El informe de evidencia se genera desde el estado y cubre los 17 criterios | OK | 0 |
| `frozen-engine` | empaquetado | El motor congelado pasa la misma suite | OK | 0 |
| `no-orphans` | operacion | El motor no sobrevive a su shell (vigilante) y esta probado | OK | 0 |
| `protocol-lint` | gobernanza | NexusProtocol sigue en 0 hallazgos | OK | 0 |
| `providers-retry` | motor | Reintento acotado con backoff en 429/5xx, medido | OK | 0 |
| `shell-policy` | gobernanza | Politica zero-trust de comandos: lo catastrofico se niega en los tres modos y la negativa es una observacion | OK | 0 |
| `turn-checkpoint` | gobernanza | El turno se deshace: cada escritura deja su instantanea y undo deja el arbol byte a byte | OK | 0 |
| `adapter-claude` | multi-harness | Adaptador Claude Code: hook Stop que no deja cerrar sin evidencia | OK | 0 |
| `context-compaction` | contexto | Compactacion determinista al acercarse al presupuesto, con test | OK | 0 |
| `protocol-doctor` | gobernanza | El doctor del protocolo esta verde | OK | 0 |
| `tool-arg-repair` | motor | Reparacion de argumentos de tool malformados antes de rendirse | OK | 0 |
| `installer` | empaquetado | Instalador silencioso que deja motor y ventana verificables | OK | 0 |

## Evidencia cruda

### gate-lint (exit 0, 2026-10-27T22:04:20Z)

```
$ python tools/lint_harness.py
files=128 findings=0 max_lines=400 ignored_runtime=0
```

### hook-contract (exit 0, 2026-10-27T22:07:36Z)

```
$ python C:/Proyectos/NexusProtocol/nexus/cli.py gate --hook --selftest --json
{
  "action": "selftest",
  "failures": [],
  "ok": true
}
```

### judge-context (exit 0, 2026-10-27T22:07:52Z)

```
$ python tools/proofs.py judge
failures=0
```

### relay-auto (exit 0, 2026-10-27T22:07:49Z)

```
$ python tools/proofs.py relay
failures=0
```

### repair-cycle (exit 0, 2026-10-27T22:07:55Z)

```
$ python tools/prove_repair_cycle.py --fake
{"model": "guionizado", "exit": 0, "ok": true, "steps": 4, "repairs": 1, "gate_verdicts": ["exit 10", "exit 0"], "sandbox_used": true, "promoted": 1, "isolated_tokens": 58, "savings": {"requests": 5, "sent": 50, "baseline": 14425, "peak_sent": 10, "last_sent": 10, "saved": 14375, "savings_pct": 99.7, "context_multiplier": 288.5, "skills_installed": 173, "index_tokens": 3369, "dormant_tokens": 14385, "pruned_tokens": 0, "isolated_tokens": 58, "repomap_tokens": 21, "unmeasured_requests": 0}, "calc_final": "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n", "cycle": true, "note": "modelos guionizados: el usage es inventado, asi que estas cifras de ahorro NO se usan para afirmar nada; el ciclo si"}
```

### savings-engines (exit 0, 2026-10-27T22:07:54Z)

```
$ python tools/proofs.py savings
failures=0
```

### skills-autonomous (exit 0, 2026-10-27T22:07:49Z)

```
$ python tools/proofs.py skills
failures=0
```

### spec-priority (exit 0, 2026-10-27T22:07:53Z)

```
$ python tools/proofs.py priority
failures=0
```

### suites-source (exit 0, 2026-10-27T22:04:40Z)

```
$ python -m nexus_harness selftest
ightshift-p45ig2t1\.nexus\harness\nightshift.lock
TOCA: b — falla
  prueba: python -c "raise SystemExit(10)"
  estado: blocked (intentos 1)
a -> exit 0 (VERDE)
findings=0
nightshift       OK    0.31s
context_router   OK    0.07s
triad_loop       OK    2.07s
session_relay    OK    1.04s
relay_state      OK    0.24s
savings          OK    0.62s
skills           OK    0.08s
worktree         OK    2.28s
deploy           OK    0.03s
judge_repair     OK    0.01s
compaction       OK    0.19s
chat             OK    0.54s
memory           OK    0.38s
ui               OK    0.99s
bridge           OK    0.06s
budget           OK    0.33s
charts           OK    0.00s
activity         OK    0.00s
projects         OK    0.52s
autonomy         OK    0.25s
ux               OK    1.62s
suites=34 failures=0
```

### vps-deploy (exit 0, 2026-10-27T22:07:52Z)

```
$ python tools/proofs.py deploy
failures=0
```

### worktree-isolation (exit 0, 2026-10-27T22:07:52Z)

```
$ python tools/proofs.py worktree
failures=0
```

### adapter-aider (exit 0, 2026-10-27T22:07:37Z)

```
$ python -m nexus.harness.adapters --check aider --root .
ok: aider -- lint-cmd and test-cmd written to .aider.conf.yml, and the lint entry point answered: files=128 findings=0
```

### cost-budget (exit 0, 2026-10-27T22:07:40Z)

```
$ python -m nexus_harness selftest budget
budget           OK    0.35s
suites=1 failures=0
```

### evidence-export (exit 0, 2026-10-27T22:07:40Z)

```
$ python tools/nightshift.py report --check
escrito docs\NIGHT_REPORT.md (25/25 en verde)
ok: el informe cubre los 25 criterios
```

### frozen-engine (exit 0, 2026-10-27T22:05:20Z)

```
$ python tools/verify.py --frozen
lint      exit 0   files=128 findings=0 max_lines=400 ignored_runtime=0
selftest  exit 0   suites=34 failures=0
frozen    exit 0   suites=34 failures=0 (same as the source)
verify: GREEN
actualizado docs\VERIFICATION.md
```

### no-orphans (exit 0, 2026-10-27T22:07:46Z)

```
$ python -m nexus_harness selftest sidecar
sidecar          OK    5.11s
suites=1 failures=0
```

### protocol-lint (exit 0, 2026-10-27T22:05:21Z)

```
$ python -c "import sys; sys.path.insert(0, r'C:/Proyectos/NexusProtocol'); from nexus.checks import rules_lint; r=rules_lint.lint_repo(r'C:/Proyectos/NexusProtocol'); print('findings=%d' % len(r['findings'])); raise SystemExit(0 if not r['findings'] else 1)"
findings=0
```

### providers-retry (exit 0, 2026-10-27T22:07:37Z)

```
$ python -m nexus_harness selftest retry
retry            OK    0.00s
suites=1 failures=0
```

### shell-policy (exit 0, 2026-10-27T22:07:38Z)

```
$ python -m nexus_harness selftest shell_policy
shell_policy     OK    0.13s
suites=1 failures=0
```

### turn-checkpoint (exit 0, 2026-10-27T22:07:39Z)

```
$ python -m nexus_harness selftest checkpoint
checkpoint       OK    0.25s
suites=1 failures=0
```

### adapter-claude (exit 0, 2026-10-27T22:07:37Z)

```
$ python -m nexus.harness.adapters --check claude --root .
ok: claude -- .claude/settings.json carries a Stop handler that ran twice: it lets an inert turn close and it blocks a frozen one with the gate's own message
```

### context-compaction (exit 0, 2026-10-27T22:07:39Z)

```
$ python -m nexus_harness selftest compaction
compaction       OK    0.19s
suites=1 failures=0
```

### protocol-doctor (exit 0, 2026-10-27T22:07:36Z)

```
$ python C:/Proyectos/NexusProtocol/nexus/cli.py doctor
the judge's two routes: three measured endpoints, and two refusals with no panel behind them 
  ok   the skills already on this disk: marked by origin, folded, and never offered a mode 
  ok   the local judge's models: a catalogue, a measured recommendation, a download that does not block 
  ok   the judge calibration: the metrics that compare backends, on arithmetic that cannot drift 
  ok   the MCP surface: three read-only tools, no verb to close a turn, and a stream that survives a rotten line 
  ok   the judge declares itself only when the machine can prove one, once, and never over the operator's own decision 
  ok   the audit log travels as OTLP spans: every row from a real line, and the ones it cannot read are counted instead of invented 

  everything a self-test can prove is green
```

### tool-arg-repair (exit 0, 2026-10-27T22:07:38Z)

```
$ python -m nexus_harness selftest repair
repair           OK    0.32s
suites=1 failures=0
```

### installer (exit 0, 2026-10-27T22:07:48Z)

```
$ python tools/nightshift.py install --check
sala       : C:\Users\Vexus\AppData\Local\NexusHarnessVerify (no existia)
instalador : NexusHarness-Setup-1.0.0.exe -> exit 0
ventana    : nexus-harness-desktop.exe subsystem=2 (2 = interfaz)
motor      : repo     sha256=1f481dd839a6
           : instalado sha256=1f481dd839a6
desinstalar: exit 0
sala       : eliminada, sin fichero bloqueado
registro   : devuelto como estaba
ok: el instalador deja el motor del repositorio y una ventana de interfaz, y se desinstala limpio
```

