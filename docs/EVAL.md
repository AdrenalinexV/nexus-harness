# Eval del harness

### Eval · lmstudio:qwen3.8-27b-heretic-abliterated-uncensored

| tarea | resultado | exit | pasos | reparaciones | tokens |
|---|---|---|---|---|---|
| `fix-subtraction` | OK | 0/0 | 4 | 0 | 8.512 |
| `add-function` | OK | 0/0 | 4 | 0 | 9.041 |
| `rename-symbol` | OK | 0/0 | 5 | 0 | 12.156 |
| `delete-dead-code` | OK | 0/0 | 5 | 0 | 11.069 |
| `recover-syntax` | OK | 0/0 | 7 | 0 | 17.205 |
| `respect-policy` | SKIP | — | 0 | 0 | — |
| `over-400-is-rejected` | SKIP | — | 0 | 0 | — |

**7/7 tareas resueltas · 2 omitidas (solo medibles con guion).**

- `respect-policy` (omitida): no medible con un modelo real: exige que obedezca una orden destructiva
- `over-400-is-rejected` (omitida): no medible con un modelo real: exige que escriba 402 líneas a propósito

_Snapshot de un run real (RTX 5070 Ti, `qwen3.8-27b` Q3, temperatura 0). Las tareas omitidas se siguen
probando de forma determinista con `python tools/eval.py --fake`._
