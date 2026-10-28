# La consulta: autonomía que pregunta en vez de adivinar

Un bucle autónomo tiene dos maneras de fallar, y las dos son caras:

* **se para en la primera duda** — entonces no es autónomo, es un `while` con supervisión;
* **decide por su cuenta lo que no le corresponde** — entonces es un riesgo con horario de oficina.

Nexus-Harness tiene una tercera: **pregunta, espera, y sigue con lo que le digas**. Y si no le
contestas, aplica el **defecto que la propia pregunta declara** — nunca uno que se inventa.

## Qué pasa, paso a paso

```
el bucle se bloquea (gate rojo tras las reparaciones permitidas)
        │
        ├─ escribe la pregunta en <proyecto>/.nexus/harness/questions.jsonl   (append-only)
        ├─ la manda a los canales configurados (Telegram / Discord / ntfy)
        ├─ espera la respuesta: sondeo con plazo (por defecto 900 s, configurable)
        │
        ├─ respuesta  → se aplica la opción declarada (seguir / revertir / parar)
        ├─ silencio   → se aplica el defecto (por defecto: parar) y queda escrito como `expired`
        └─ Detener    → la espera se corta; la pregunta queda abierta en la cabina
```

## Las tres salidas, y qué hace cada una de verdad

| respuesta | efecto |
|---|---|
| **seguir** | otro ciclo del proyecto, con el motivo del rojo delante para no repetir el mismo parche |
| **revertir** | `checkpoint` devuelve el árbol a los bytes de antes del turno; se informa qué se restauró |
| **parar** | el proyecto se queda como está y la cola pasa al siguiente. Es el defecto |

## Por dónde te puede oír

| canal | escribe | escucha | cómo |
|---|---|---|---|
| **Telegram** | sí | **sí** | `getUpdates` con `offset` persistido en `.nexus/harness/channel-cursors.json` |
| **Discord (bot)** | sí | **sí** | `GET /channels/{id}/messages?after=…` con token de bot |
| **Discord (webhook)** | sí | no | un webhook escribe; no lee. El panel lo dice en vez de fingir |
| **WhatsApp / n8n / bot propio** | — | vía puente | `POST /api/consult/answer` con `{"id": "...", "answer": "..."}` |
| **ntfy** | sí | no | notificación push; se contesta desde la cabina |

El panel **Autonomía & Preguntas** (`/settings?section=autonomia`) enseña, por canal, si *escribe* y si
*escucha*. Eso evita la tarde perdida esperando una respuesta que nunca iba a llegar.

## Configuración (`~/.nexus/harness.json`)

```json
{
  "consult_enabled": true,
  "ask_deadline": 900,
  "notify": {
    "telegram": {"token": "$TELEGRAM_TOKEN", "chat_id": "$TELEGRAM_CHAT"},
    "discord_bot_token": "$DISCORD_BOT_TOKEN",
    "discord_channel_id": "123456789012345678",
    "discord_webhook": "$DISCORD_WEBHOOK"
  }
}
```

Los `$NOMBRE` se resuelven contra la bóveda (`~/.nexus/secrets.json`) o el entorno. **Ningún secreto se
escribe en la configuración ni aparece en un log**: lo que sale por pantalla va redactado con `***`.

## Desde la terminal

```bash
python -m nexus_harness consult --check                 # ¿qué canales escuchan de verdad?
python -m nexus_harness consult --status                # lo que sigue abierto
python -m nexus_harness consult "¿Aplico el parche grande?" --options "si,no" --default no --wait 600
python -m nexus_harness consult --answer ab12cd34 "si"  # contestar a mano
```

`consult --check` es el comando que hay que ejecutar antes de confiar en la autonomía: si dice
`escucha=no` en todos los canales, el bucle **siempre** aplicará el defecto.

## Qué garantiza, y por qué está escrito así

* **Registro append-only.** Preguntar y contestar son eventos; el estado es un fold. Un corte de luz a
  mitad deja una pregunta abierta, nunca un JSON corrupto.
* **La primera respuesta gana.** Si contesta el móvil y luego un bot, el resultado no cambia.
* **Sin canal no hay espera.** El defecto se aplica al instante: un turno no se bloquea esperando a un
  mensajero que no existe.
* **Un canal caído no tumba el bucle.** Se declara y se sigue; la consulta tiene su propio plazo.
* **El botón Detener corta la espera**, y la pregunta se queda abierta para contestarla después.
* **Todo se puede contestar sin recordar un id**: los botones del panel y el número de la opción
  (`"2"`) se traducen a la opción declarada.

## Cómo se prueba

```bash
python -m nexus_harness selftest consult      # 13 pruebas deterministas, sin red ni reloj real
```

La suite usa un canal de mentira y un reloj inyectado: mide que la respuesta tardía llegue a su
pregunta, que el silencio aplique el defecto declarado, que un webhook se declare sordo, que el offset
de Telegram se persista, que `revertir` restaure los bytes y que la cabina pueda contestar con un clic.
