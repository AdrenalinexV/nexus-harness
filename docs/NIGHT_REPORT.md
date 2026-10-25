# Turno de noche — evidencia

Generado por `tools/nightshift.py report` (no se escribe a mano).

- fecha: 2026-10-25T02:23:40Z
- HEAD: `90100ba`
- iteracion: 33
- criterios: **14/14**

## Rubrica

| criterio | area | que se exige | estado | exit |
|---|---|---|---|---|
| `gate-lint` | gobernanza | La ley de 400 lineas pasa en el propio repositorio | OK | 0 |
| `hook-contract` | multi-harness | Contrato generico `nexus gate --hook` (JSON por stdin, exit 0/10/20/30) | OK | 0 |
| `suites-source` | gobernanza | Toda la suite determinista pasa desde el codigo fuente | OK | 0 |
| `adapter-aider` | multi-harness | Adaptador Aider: lint/test del gate escritos en su config, verificable | OK | 0 |
| `evidence-export` | evidencia | El informe de evidencia se genera desde el estado y cubre los 14 criterios | OK | 0 |
| `frozen-engine` | empaquetado | El motor congelado pasa la misma suite | OK | 0 |
| `no-orphans` | operacion | El motor no sobrevive a su shell (vigilante) y esta probado | OK | 0 |
| `protocol-lint` | gobernanza | NexusProtocol sigue en 0 hallazgos | OK | 0 |
| `providers-retry` | motor | Reintento acotado con backoff en 429/5xx, medido | OK | 0 |
| `adapter-claude` | multi-harness | Adaptador Claude Code: hook Stop que no deja cerrar sin evidencia | OK | 0 |
| `context-compaction` | contexto | Compactacion determinista al acercarse al presupuesto, con test | OK | 0 |
| `protocol-doctor` | gobernanza | El doctor del protocolo esta verde | OK | 0 |
| `tool-arg-repair` | motor | Reparacion de argumentos de tool malformados antes de rendirse | OK | 0 |
| `installer` | empaquetado | Instalador silencioso que deja motor y ventana verificables | OK | 0 |

## Evidencia cruda

### gate-lint (exit 0, 2026-10-25T02:20:38Z)

```
$ python tools/lint_harness.py
files=73 findings=0 max_lines=400
```

### hook-contract (exit 0, 2026-10-25T02:23:27Z)

```
$ python C:/Proyectos/NexusProtocol/nexus/cli.py gate --hook --selftest --json
{
  "action": "selftest",
  "failures": [],
  "ok": true
}
```

### suites-source (exit 0, 2026-10-25T02:20:50Z)

```
$ python -m nexus_harness selftest
          OK    0.00s
repair           OK    0.15s
tools            OK    0.11s
edit_v4a         OK    0.03s
shell_session    OK    1.34s
subagents        OK    0.01s
warning: The `fitz` API is deprecated and will be removed in future. Use `import pymupdf` instead.
attachments      OK    0.13s
onboarding       OK    0.11s
mcp_client       OK    0.31s
sidecar          OK    5.14s
estado listo: 2 criterios (2 pendientes)
a -> exit 0 (VERDE)
findings=0
b -> exit 10 (ROJO)

b marcado blocked
criterio desconocido: zzz
nightshift       OK    0.19s
context_router   OK    0.00s
triad_loop       OK    1.55s
session_relay    OK    0.84s
compaction       OK    0.01s
chat             OK    0.08s
memory           OK    0.29s
ui               OK    0.87s
bridge           OK    0.05s
suites=20 failures=0
```

### adapter-aider (exit 0, 2026-10-25T02:23:27Z)

```
$ python -m nexus.harness.adapters --check aider --root .
ok: aider -- lint-cmd and test-cmd written to .aider.conf.yml, and the lint entry point answered: files=73 findings=0
```

### evidence-export (exit 0, 2026-10-25T02:23:29Z)

```
$ python tools/nightshift.py report --check
escrito docs\NIGHT_REPORT.md (14/14 en verde)
ok: el informe cubre los 14 criterios
```

### frozen-engine (exit 0, 2026-10-25T02:21:13Z)

```
$ python tools/verify.py --frozen
lint      exit 0   files=73 findings=0 max_lines=400
selftest  exit 0   suites=20 failures=0
frozen    exit 0   suites=20 failures=0 (same as the source)
verify: GREEN
```

### no-orphans (exit 0, 2026-10-25T02:23:34Z)

```
$ python -m nexus_harness selftest sidecar
sidecar          OK    5.14s
suites=1 failures=0
```

### protocol-lint (exit 0, 2026-10-25T02:21:13Z)

```
$ python -c "import sys; sys.path.insert(0, r'C:/Proyectos/NexusProtocol'); from nexus.checks import rules_lint; r=rules_lint.lint_repo(r'C:/Proyectos/NexusProtocol'); print('findings=%d' % len(r['findings'])); raise SystemExit(0 if not r['findings'] else 1)"
findings=0
```

### providers-retry (exit 0, 2026-10-25T02:23:28Z)

```
$ python -m nexus_harness selftest retry
retry            OK    0.00s
suites=1 failures=0
```

### adapter-claude (exit 0, 2026-10-25T02:23:28Z)

```
$ python -m nexus.harness.adapters --check claude --root .
ok: claude -- .claude/settings.json carries a Stop handler that ran twice: it lets an inert turn close and it blocks a frozen one with the gate's own message
```

### context-compaction (exit 0, 2026-10-25T02:23:29Z)

```
$ python -m nexus_harness selftest compaction
compaction       OK    0.01s
suites=1 failures=0
```

### protocol-doctor (exit 0, 2026-10-25T02:23:26Z)

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

### tool-arg-repair (exit 0, 2026-10-25T02:23:28Z)

```
$ python -m nexus_harness selftest repair
repair           OK    0.15s
suites=1 failures=0
```

### installer (exit 0, 2026-10-25T02:23:37Z)

```
$ python tools/nightshift.py install --check
sala       : C:\Users\Vexus\AppData\Local\NexusHarnessVerify (no existia)
instalador : NexusHarness-Setup-0.3.0.exe -> exit 0
ventana    : nexus-harness-desktop.exe subsystem=2 (2 = interfaz)
motor      : repo     sha256=17854d734d15
           : instalado sha256=17854d734d15
desinstalar: exit 0
sala       : eliminada, sin fichero bloqueado
registro   : devuelto como estaba
ok: el instalador deja el motor del repositorio y una ventana de interfaz, y se desinstala limpio
```

