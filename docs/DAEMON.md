# Daemon: trabajo autónomo sin ventana abierta

El daemon es el bucle que hace que el harness trabaje cuando nadie mira. No inventa objetivos: toma los
criterios congelados del proyecto, los ejecuta y encola mejoras medidas cuando ya está verde.

## Arranque

```bash
python -m nexus_harness daemon --once                  # un tick (ideal para cron / Task Scheduler)
python -m nexus_harness daemon --interval 300          # en bucle, cada 5 min, hasta Ctrl-C
python -m nexus_harness daemon --interval 60 --rounds 12 --iterations 2
```

`--once` devuelve `0` si hizo algo o no había nada que hacer, `10` si el trabajo cerró en rojo y `20` si
no pudo arrancar (por ejemplo, otro daemon vivo).

## Qué hace en cada tick (y en qué orden)

1. **Bandeja primero.** `python -m nexus_harness task add "arregla el test de calc" --project Alpha`.
   Lo que pidió una persona (o un bot) manda sobre lo que el daemon cree que toca.
2. **Spec.** Si el proyecto no tiene `.ai/CURRENT_SPEC.json`, intenta congelar los criterios que el
   propio repo ya sabe probar (pytest/npm/cargo/go/phpunit/make). Si no hay ninguno, no se inventa nada:
   encola «declara cómo se prueba este proyecto».
3. **Criterios.** Ejecuta los CAs congelados. Si **todos pasan**, el proyecto no se toca: se encolan
   mejoras (`improve.py`) y se sigue.
4. **Trabajo.** Un ciclo de `Autopilot`: backup → plan (Director real) → worktree → gate → juez →
   commit. El progreso queda en `.nexus/harness/progress.json`, así que un reinicio **reanuda**.

Un daemon en reposo no gasta un solo token: si no hay tarea ni criterio rojo, no llama a ningún modelo.

## Estado y cerrojo

- `.nexus/harness/daemon.json` (en `NEXUS_HOME`): pid, ronda, último tick, último resultado y avisos.
- `.nexus/harness/daemon.lock`: un segundo daemon se niega a arrancar mientras el pid siga vivo.
- La bandeja vive en el workspace: `<workspace>/.nexus/harness/inbox.jsonl`.

## Avisos (Discord / Telegram / ntfy)

En `~/.nexus/harness.json`:

```json
{"notify": {"discord_webhook": "$NEXUS_DISCORD_WEBHOOK",
            "telegram": {"token": "$TELEGRAM_TOKEN", "chat_id": "$TELEGRAM_CHAT"},
            "ntfy": "nexus-tu-usuario"}}
```

Un valor que empieza por `$` se resuelve de la bóveda (`~/.nexus/secrets.json`) o del entorno: una URL
de webhook es un secreto y no se escribe en el repositorio.

```bash
python -m nexus_harness notify "prueba de canal"
```

Un canal caído devuelve `{ok: false, reason}` y **no** detiene el daemon.

## Contrato para bots (Discord/Telegram/webhook)

Cualquier integración solo necesita **añadir una línea** a `<workspace>/.nexus/harness/inbox.jsonl`:

```json
{"id": "a1b2c3d4e5f6", "at": "2026-10-28T01:00:00Z", "state": "queued",
 "project": "Alpha", "goal": "arregla el test que falla en calc.py",
 "source": "discord", "priority": 3, "evidence": "mensaje de #dev", "signature": "discord:123"}
```

- `id`: único (el bot puede usar el id del mensaje).
- `project`: nombre de carpeta bajo el workspace, o ruta absoluta.
- `signature`: opcional; si ya hay una tarea abierta con la misma firma, se descarta (anti-duplicados).
- El daemon la reclama (`claimed`), la ejecuta y la cierra con el `exit` real (`done`/`failed`).

Así el bot no habla con el motor: escribe una línea y consulta el estado. El mismo contrato sirve para
un formulario, un cron o un webhook de GitHub.

## En el VPS (systemd)

```ini
# /etc/systemd/system/nexus-daemon.service
[Unit]
Description=Nexus Harness daemon
After=network-online.target

[Service]
Type=simple
User=vexus
WorkingDirectory=/opt/nexus-harness
Environment=NEXUS_HOME=/home/vexus/.nexus
Environment=NEXUS_WORKSPACE=/srv/proyectos
ExecStart=/usr/bin/python3 -m nexus_harness daemon --interval 300
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now nexus-daemon
journalctl -u nexus-daemon -f
```

El daemon no necesita puerto abierto: habla hacia fuera (API del modelo, webhook de avisos). Para
recibir tareas desde Discord/Telegram, el bot corre aparte y escribe en la bandeja; el daemon solo lee.

## Reglas que no se relajan

- Sin backup no se edita (lo impone `Autopilot`, no el daemon).
- Una tarea se reclama una vez; dos daemons no pueden trabajar el mismo proyecto.
- Un tick que falla se registra y el bucle sigue: el daemon no muere por un proyecto rojo.
- El aviso es cortesía: si Discord está caído, el trabajo ya está hecho y el estado en disco lo dice.
