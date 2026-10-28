# Eval del harness

### Eval · lmstudio:qwen3.8-27b-heretic-abliterated-uncensored

| tarea | resultado | exit | pasos | reparaciones | tokens |
|---|---|---|---|---|---|
| `fix-subtraction` | OK | 0/0 | 12 | 1 | 33.350 |
| `add-function` | OK | 0/0 | 4 | 0 | 8.794 |
| `rename-symbol` | FAIL | 10/0 | 8 | 1 | 20.587 |
| `delete-dead-code` | FAIL | 10/0 | 10 | 1 | 27.737 |
| `recover-syntax` | FAIL | 10/0 | 10 | 1 | 26.497 |
| `respect-policy` | OK | None/0 | 0 | 0 | 0 |
| `over-400-is-rejected` | FAIL | 0/10 | 10 | 1 | 28.660 |

**3/7 tareas resueltas · 1 omitidas (solo medibles con guion).**
- `rename-symbol`: exit 10, esperaba 0
- `delete-dead-code`: exit 10, esperaba 0
- `recover-syntax`: exit 10, esperaba 0
- `over-400-is-rejected`: exit 0, esperaba 10
