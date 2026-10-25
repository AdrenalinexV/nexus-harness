# Turno de noche — evidencia

Generado por `tools/nightshift.py report` (no se escribe a mano).

- fecha: 2026-10-25T01:04:07Z
- HEAD: `146071d`
- iteracion: 12
- criterios: **10/14**

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
| `context-compaction` | contexto | Compactacion determinista al acercarse al presupuesto, con test | unmet | — |
| `protocol-doctor` | gobernanza | El doctor del protocolo esta verde | unmet | — |
| `tool-arg-repair` | motor | Reparacion de argumentos de tool malformados antes de rendirse | unmet | — |
| `installer` | empaquetado | Instalador silencioso que deja motor y ventana verificables | unmet | — |

## Evidencia cruda

### gate-lint (exit 0, 2026-10-25T00:00:51Z)

```
$ python tools/lint_harness.py
files=67 findings=0 max_lines=400
```

### hook-contract (exit 0, 2026-10-25T00:44:36Z)

```
$ python C:/Proyectos/NexusProtocol/nexus/cli.py gate --hook --selftest --json
{
  "action": "selftest",
  "failures": [],
  "ok": true
}
```

### suites-source (exit 0, 2026-10-25T00:01:03Z)

```
$ python -m nexus_harness selftest
providers        OK    0.00s
tools            OK    0.16s
edit_v4a         OK    0.03s
shell_session    OK    1.36s
subagents        OK    0.01s
warning: The `fitz` API is deprecated and will be removed in future. Use `import pymupdf` instead.
attachments      OK    0.22s
onboarding       OK    0.13s
mcp_client       OK    0.32s
sidecar          OK    5.11s
estado listo: 2 criterios (2 pendientes)
a -> exit 0 (VERDE)
findings=0
b -> exit 10 (ROJO)

b marcado blocked
criterio desconocido: zzz
nightshift       OK    0.19s
context_router   OK    0.01s
triad_loop       OK    1.65s
session_relay    OK    0.92s
chat             OK    0.10s
memory           OK    0.49s
ui               OK    0.89s
bridge           OK    0.06s
suites=17 failures=0
```

### adapter-aider (exit 0, 2026-10-25T00:51:19Z)

```
$ python -m nexus.harness.adapters --check aider --root .
ok: aider -- lint-cmd and test-cmd written to .aider.conf.yml, and the lint entry point answered: files=68 findings=0
```

### evidence-export (exit 0, 2026-10-25T00:01:09Z)

```
$ python tools/nightshift.py report --check
escrito docs\NIGHT_REPORT.md (4/14 en verde)
ok: el informe cubre los 14 criterios
```

### frozen-engine (exit 0, 2026-10-25T00:59:33Z)

```
$ python tools/verify.py --frozen
lint      exit 0   files=69 findings=0 max_lines=400
selftest  exit 0   suites=18 failures=0
frozen    exit 0   suites=18 failures=0 (same as the source)
verify: GREEN
```

### no-orphans (exit 0, 2026-10-25T00:01:09Z)

```
$ python -m nexus_harness selftest sidecar
sidecar          OK    5.11s
suites=1 failures=0
```

### protocol-lint (exit 0, 2026-10-25T00:01:04Z)

```
$ python -c "import sys; sys.path.insert(0, r'C:/Proyectos/NexusProtocol'); from nexus.checks import rules_lint; r=rules_lint.lint_repo(r'C:/Proyectos/NexusProtocol'); print('findings=%d' % len(r['findings'])); raise SystemExit(0 if not r['findings'] else 1)"
findings=0
```

### providers-retry (exit 0, 2026-10-25T00:59:10Z)

```
$ python -m nexus_harness selftest retry
retry            OK    0.00s
suites=1 failures=0
```

### adapter-claude (exit 0, 2026-10-25T01:01:52Z)

```
$ python -m nexus.harness.adapters --check claude --root .
ok: claude -- .claude/settings.json carries a Stop handler that ran twice: it lets an inert turn close and it blocks a frozen one with the gate's own message
```

