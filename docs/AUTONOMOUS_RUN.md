# Parte del turno autónomo (2026-10-28)

> Congelado en `5e83a9a`: las cifras de este documento retratan ese árbol, no el de hoy.

Trabajo hecho sin intervención, con verificación real al final de cada pieza. Estado del árbol:
`verify.py --frozen` → **GREEN** (lint 0 hallazgos, 158 ficheros, 45 suites en fuente **y** en el motor
congelado).

## Lo que se construyó

| pieza | módulo | prueba |
|---|---|---|
| Daemon autónomo (bandeja → spec → criterios → trabajo) | `daemon.py`, `tasks.py`, `improve.py` | `python tools/proofs.py daemon` |
| Avisos Discord / Telegram / ntfy | `notify.py` | `python tools/proofs.py notify` |
| Navegador nativo (Edge/Chrome en worker, DOM→texto, muros) | `toolbox/browser.py` | `python tools/proofs.py browser` |
| Memoria por capas (SQLite+FTS5: core, episodios, hechos, procedimientos) | `recall.py`, `toolbox/memory_tools.py` | `python tools/proofs.py recall` |
| Libertad de proveedor (cualquier endpoint OpenAI/Anthropic/Ollama) | `providers.py`, `config.py` | `python -m nexus_harness selftest providers` |

Suites 41 → 45. Herramientas del modelo 12 → 15 (`browser`, `recall`, `remember`).

## Cómo se usa

```bash
python -m nexus_harness daemon --once                 # un tick (cron / Task Scheduler)
python -m nexus_harness daemon --interval 300         # en bucle
python -m nexus_harness task add "arregla X" --project Alpha
python -m nexus_harness notify "prueba"
python tools/eval.py --fake                           # 7/7 determinista
python tools/eval.py --model lmstudio:qwen3.8-27b     # 5/5 medibles (0 reparaciones)
```

Contrato para bots y unidad de systemd: `docs/DAEMON.md`. Estado de la competencia y qué se adopta:
`docs/COMPETITIVE.md`.

## Decisiones que se tomaron (y por qué)

- **La bandeja manda sobre el proyecto.** Lo que pidió una persona o un bot se ejecuta antes de que el
  daemon decida por su cuenta.
- **Un proyecto sin spec no se toca a ciegas**: se intentan congelar los criterios que el repo ya sabe
  probar; sin runner, se encola «declara cómo se prueba esto».
- **Verde = cero llamadas.** Si los criterios pasan, el daemon no gasta un token: encola mejoras
  medidas (TODO acumulados, ficheros al borde de la ley, último turno rojo, falta de runner).
- **La memoria no se paga en cada prompt**: `core` acotado (~700 caracteres) y el resto por consulta
  FTS5 con presupuesto. Un `fact` sin evidencia no se escribe.
- **El navegador vive en su hilo**: Playwright síncrono no arranca dentro de asyncio, y el arnés corre
  dentro de uno.
- **El binario declara lo que no lleva**: el motor congelado no empaqueta Playwright y lo dice; no finge.

## Lo que queda abierto (declarado, no escondido)

1. **Despliegue real en el VPS**: la unidad de systemd y el contrato están escritos, pero **no se ha
   ejecutado nada** en el servidor. Es un cambio en producción y necesita tu «adelante» (y las claves de
   avisos en la bóveda).
2. **Sandbox de proceso**: el worktree aísla el árbol, no el proceso. Sigue siendo el agujero más grande
   para trabajo autónomo de verdad.
3. **LSP** (definición/referencias/diagnósticos) y **cartera medida por hardware** (P1.6): pendientes.
4. **El planificador real del daemon** no se ejercitó contra un modelo en las pruebas (sí el de reserva,
   determinista). Primera noche real: mirar `daemon.json` y el libro de turnos.
5. **Eval**: 5 tareas medibles es un instrumento, no un benchmark. Para comparar modelos hacen falta ~20.
