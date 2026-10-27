# Turno de noche — evidencia

Generado por `tools/nightshift.py report` (no se escribe a mano).

- fecha: 2026-10-27T21:36:39Z
- HEAD: `6302cb0`
- iteracion: 153
- criterios: **24/24**

## Rubrica

| criterio | area | que se exige | estado | exit |
|---|---|---|---|---|
| `gate-lint` | gobernanza | La ley de 400 lineas pasa en el propio repositorio | OK | 0 |
| `hook-contract` | multi-harness | Contrato generico `nexus gate --hook` (JSON por stdin, exit 0/10/20/30) | OK | 0 |
| `judge-context` | motor | Juez sensible al contexto y pista con lineas reales al segundo fallo | OK | 0 |
| `relay-auto` | contexto | Relevo automatico: poda al 55% (path/lineas/sha256) y estado verificado al 70% | OK | 0 |
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

### gate-lint (exit 0, 2026-10-27T21:32:05Z)

```
$ python tools/lint_harness.py
files=126 findings=0 max_lines=400 ignored_runtime=0
```

### hook-contract (exit 0, 2026-10-27T21:35:31Z)

```
$ python C:/Proyectos/NexusProtocol/nexus/cli.py gate --hook --selftest --json
{
  "action": "selftest",
  "failures": [],
  "ok": true
}
```

### judge-context (exit 0, 2026-10-27T21:35:47Z)

```
$ python tools/proofs.py judge
failures=0
```

### relay-auto (exit 0, 2026-10-27T21:35:44Z)

```
$ python tools/proofs.py relay
failures=0
```

### savings-engines (exit 0, 2026-10-27T21:35:49Z)

```
$ python tools/proofs.py savings
failures=0
```

### skills-autonomous (exit 0, 2026-10-27T21:35:44Z)

```
$ python tools/proofs.py skills
failures=0
```

### spec-priority (exit 0, 2026-10-27T21:35:48Z)

```
$ python tools/proofs.py priority
failures=0
```

### suites-source (exit 0, 2026-10-27T21:32:26Z)

```
$ python -m nexus_harness selftest
ightshift-058diydj\.nexus\harness\nightshift.lock
TOCA: b — falla
  prueba: python -c "raise SystemExit(10)"
  estado: blocked (intentos 1)
a -> exit 0 (VERDE)
findings=0
nightshift       OK    0.31s
context_router   OK    0.07s
triad_loop       OK    2.15s
session_relay    OK    1.16s
relay_state      OK    0.24s
savings          OK    0.65s
skills           OK    0.09s
worktree         OK    2.44s
deploy           OK    0.03s
judge_repair     OK    0.01s
compaction       OK    0.18s
chat             OK    0.60s
memory           OK    0.36s
ui               OK    0.96s
bridge           OK    0.06s
budget           OK    0.35s
charts           OK    0.00s
activity         OK    0.00s
projects         OK    0.56s
autonomy         OK    0.25s
ux               OK    1.85s
suites=34 failures=0
```

### vps-deploy (exit 0, 2026-10-27T21:35:47Z)

```
$ python tools/proofs.py deploy
failures=0
```

### worktree-isolation (exit 0, 2026-10-27T21:35:47Z)

```
$ python tools/proofs.py worktree
failures=0
```

### adapter-aider (exit 0, 2026-10-27T21:35:31Z)

```
$ python -m nexus.harness.adapters --check aider --root .
ok: aider -- lint-cmd and test-cmd written to .aider.conf.yml, and the lint entry point answered: files=126 findings=0
```

### cost-budget (exit 0, 2026-10-27T21:35:35Z)

```
$ python -m nexus_harness selftest budget
budget           OK    0.36s
suites=1 failures=0
```

### evidence-export (exit 0, 2026-10-27T21:35:35Z)

```
$ python tools/nightshift.py report --check
escrito docs\NIGHT_REPORT.md (24/24 en verde)
ok: el informe cubre los 24 criterios
```

### frozen-engine (exit 0, 2026-10-27T21:33:07Z)

```
$ python tools/verify.py --frozen
lint      exit 0   files=126 findings=0 max_lines=400 ignored_runtime=0
selftest  exit 0   suites=34 failures=0
frozen    exit 0   suites=34 failures=0 (same as the source)
verify: GREEN
actualizado docs\VERIFICATION.md
```

### no-orphans (exit 0, 2026-10-27T21:35:40Z)

```
$ python -m nexus_harness selftest sidecar
sidecar          OK    5.15s
suites=1 failures=0
```

### protocol-lint (exit 0, 2026-10-27T21:33:08Z)

```
$ python -c "import sys; sys.path.insert(0, r'C:/Proyectos/NexusProtocol'); from nexus.checks import rules_lint; r=rules_lint.lint_repo(r'C:/Proyectos/NexusProtocol'); print('findings=%d' % len(r['findings'])); raise SystemExit(0 if not r['findings'] else 1)"
findings=0
```

### providers-retry (exit 0, 2026-10-27T21:35:32Z)

```
$ python -m nexus_harness selftest retry
retry            OK    0.00s
suites=1 failures=0
```

### shell-policy (exit 0, 2026-10-27T21:35:33Z)

```
$ python -m nexus_harness selftest shell_policy
shell_policy     OK    0.13s
suites=1 failures=0
```

### turn-checkpoint (exit 0, 2026-10-27T21:35:34Z)

```
$ python -m nexus_harness selftest checkpoint
checkpoint       OK    0.36s
suites=1 failures=0
```

### adapter-claude (exit 0, 2026-10-27T21:35:31Z)

```
$ python -m nexus.harness.adapters --check claude --root .
ok: claude -- .claude/settings.json carries a Stop handler that ran twice: it lets an inert turn close and it blocks a frozen one with the gate's own message
```

### context-compaction (exit 0, 2026-10-27T21:35:33Z)

```
$ python -m nexus_harness selftest compaction
compaction       OK    0.23s
suites=1 failures=0
```

### protocol-doctor (exit 0, 2026-10-27T21:35:30Z)

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

### tool-arg-repair (exit 0, 2026-10-27T21:35:32Z)

```
$ python -m nexus_harness selftest repair
repair           OK    0.33s
suites=1 failures=0
```

### installer (exit 0, 2026-10-27T21:35:43Z)

```
$ python tools/nightshift.py install --check
sala       : C:\Users\Vexus\AppData\Local\NexusHarnessVerify (no existia)
instalador : NexusHarness-Setup-1.0.0.exe -> exit 0
ventana    : nexus-harness-desktop.exe subsystem=2 (2 = interfaz)
motor      : repo     sha256=29fa25d9e612
           : instalado sha256=29fa25d9e612
desinstalar: exit 0
sala       : eliminada, sin fichero bloqueado
registro   : devuelto como estaba
ok: el instalador deja el motor del repositorio y una ventana de interfaz, y se desinstala limpio
```

