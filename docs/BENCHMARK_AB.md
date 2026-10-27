# Benchmark A/B del ahorro de contexto

- fecha: 2026-10-27T21:18:53Z
- modelo: no hay clave DEEPSEEK_API_KEY/OPENROUTER_API_KEY en el entorno ni en la boveda: se mide con el modelo local (ponla en la boveda para el A/B en la nube)
- tarea: Lee los modulos del proyecto, encuentra el defecto de calc.py (add devuelve mal) y arreglalo. El test del proyecto tiene que pasar.
- pasos: 8 · proyecto: `BenchAB` (calc.py con un defecto real)

| medida | A (tradicional) | B (Nexus) | diferencia |
|---|---|---|---|
| tokens de prompt enviados | 36673 | 15451 | **57.9%** |
| prompt maximo alcanzado | 6544 | 3589 | **45.2%** |
| vida de la ventana | x1 | x1.82 | — |
| pasos | 6 | 5 | — |
| tokens por paso | 6112.2 | 3090.2 | **ver abajo** |
| gate verde | True | True | — |

## Ahorro del modo B por motor

```json
{
  "requests": 6,
  "sent": 15451,
  "baseline": 32474,
  "peak_sent": 3589,
  "last_sent": 3589,
  "saved": 17023,
  "savings_pct": 52.4,
  "context_multiplier": 2.1,
  "skills_installed": 173,
  "index_tokens": 3369,
  "dormant_tokens": 17055,
  "pruned_tokens": 0,
  "isolated_tokens": 0,
  "repomap_tokens": 32,
  "unmeasured_requests": 0
}
```

## Coste extrapolado

| modelo | A (USD) | B (USD) |
|---|---|---|
| DeepSeek V4.1 Flash (declarado) | 0.0 | 0.0 |
| Claude Sonnet 4 (declarado) | 0.0 | 0.0 |
| OpenAI GPT-5 / o3 (declarado) | 0.0 | 0.0 |
| LM Studio / Ollama en la RTX 5070 Ti | 0.0 | 0.0 |

Precios DECLARADOS en `stats_savings.py` (USD por 1M tokens), no una cotizacion: cambian y esta tabla se lee como proyeccion de ORDEN DE MAGNITUD sobre los tokens medidos.

Modo A: `nexus_engines=False` (indice completo de skills, sin poda, sin mapa, reparacion en el hilo). Modo B: los cuatro motores. El mismo modelo y la misma tarea en los dos.

**Limite declarado:** A y B no dan necesariamente el mismo numero de pasos, porque el modelo decide cuando parar y su contexto cambia entre modos. Por eso la tabla lleva los tokens POR PASO ademas del total: comparar solo el total premiaria al modo que se dio por vencido antes.

no hay clave DEEPSEEK_API_KEY/OPENROUTER_API_KEY en el entorno ni en la boveda: se mide con el modelo local (ponla en la boveda para el A/B en la nube)
