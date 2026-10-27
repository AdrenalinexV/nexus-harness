"""El bloque de deploy en `/settings`: los dos modos de tener la colmena encendida.

Modo 1 es el demonio de este PC (ya existia). Modo 2 es el VPS 24/7 por SSH + Docker. El panel no
finge ninguna de las dos cosas:

* si faltan `VPS_HOST`, `VPS_USER` o `VPS_SSH_KEY` en la boveda, lo dice con el nombre de la clave que
  falta y no ofrece un boton que fallaria;
* **toda accion destructiva exige `confirm`**. Sin la casilla, el boton ejecuta el plan en seco y
  ensena exactamente que comandos habria lanzado: un deploy accidental es un `docker compose down`
  sobre produccion con una sonrisa;
* el resultado de cada accion se pinta redactado (`***`), porque un log con el token es una fuga.
"""
from . import settings_kit as kit
from .vps_deployer import VPSConfig, VPSDeployer, redact

LAST = {}


def _deployer():
    config = VPSConfig.from_vault()
    return config, VPSDeployer(config)


def block(cockpit=None):
    """El HTML del bloque. Sin cockpit es puro: solo lee la boveda y el plan."""
    config, deployer = _deployer()
    missing = config.missing
    status = "configurado" if not missing else "faltan: %s" % ", ".join(missing)
    rows = "".join(
        "<li><strong>%s</strong> <span class=\"dim\">%s</span></li>" % (kit.esc(step["step"]),
                                                                      kit.esc(step["detail"]))
        for step in deployer.plan())
    note = LAST.get("vps") or ""
    form = ('<form class="sform" method="post" action="/api/settings/do">'
            + kit.hidden("section", "puente")
            + '<div class="sgrow"><input name="host" placeholder="VPS_HOST (p. ej. 178.105.35.201)"'
              ' value="%s" class="wide">'
              '<input name="user" placeholder="VPS_USER" value="%s"></div>'
              '<div class="sgrow"><input name="port" placeholder="puerto SSH" value="%s">'
              '<input name="key" placeholder="ruta de la clave SSH (o vacio si usas ssh-agent)"'
              ' value="" class="wide"></div>'
            '<label class="check"><input type="checkbox" name="confirm" value="on"> '
            'Ejecutar de verdad (sin esto solo se muestra el plan)</label>'
            '<div class="sactions">'
            '<button class="ghost" name="what" value="vps_probe">Probar conexion SSH</button>'
            '<button class="primary" name="what" value="vps_sync">Sincronizar cola Colmena</button>'
            '<button class="primary" name="what" value="vps_deploy">🚀 Desplegar Colmena y Harness</button>'
            '<button class="ghost" name="what" value="vps_status">Ver estado</button>'
            '<button class="ghost" name="what" value="vps_logs">Ver logs</button>'
            '<button class="ghost" name="what" value="vps_stop">Parar nodo</button>'
            '</div></form>'
            % (kit.esc(config.host), kit.esc(config.user), kit.esc(config.port)))
    return ('<section class="vps">'
            '<h3 class="ssub">📱 Puente Móvil &amp; Deploy VPS (Hive 24/7)</h3>'
            '<p><span class="chip %s">%s</span> <span class="dim">destino: %s · puerto %s</span></p>'
            '<p class="dim">Modo 1: el demonio de este PC (arriba). Modo 2: el nodo 24/7 en tu VPS, '
            'levantado con Docker Compose por SSH. Los tokens viajan en un <code>secrets.env</code> '
            'con permisos 0600.</p>'
            '<details class="plan"><summary>Qué hará el botón de despliegue (5 pasos)</summary>'
            '<ol>%s</ol></details>%s%s</section>'
            % ("ok" if not missing else "warn", kit.esc(status), kit.esc(config.target or "-"),
               kit.esc(config.port), rows,
               ('<pre class="sout">%s</pre>' % kit.esc(redact(note))) if note else "", form))


def _save_keys(body):
    """Guarda host/usuario/puerto/clave en la boveda. Devuelve las notas (nunca los valores)."""
    from . import vault
    updates = {}
    for field, name in (("host", "VPS_HOST"), ("user", "VPS_USER"), ("port", "VPS_PORT"),
                        ("key", "VPS_SSH_KEY")):
        value = str(body.get(field) or "").strip()
        if value:
            updates[name] = value
    if not updates:
        return []
    answer = vault.save(updates)
    return ["bóveda: %s" % ", ".join(sorted(answer.get("changed") or updates))]


def action(cockpit, body):
    """Ejecuta una accion `vps_*`. Devuelve `(nota, ok, seccion)`."""
    what = str(body.get("what") or "")
    confirmed = str(body.get("confirm") or "") == "on"
    notes = _save_keys(body)
    config, deployer = _deployer()
    if config.missing:
        note = "faltan credenciales en la bóveda: %s" % ", ".join(config.missing)
        LAST["vps"] = note
        return (" · ".join(notes + [note]), False, "puente")
    dry = not confirmed
    try:
        if what == "vps_probe":
            result = deployer.probe(dry_run=dry)
        elif what == "vps_deploy":
            result = deployer.deploy(dry_run=dry)
        elif what == "vps_status":
            result = deployer.status(dry_run=dry)
        elif what == "vps_logs":
            result = deployer.logs(dry_run=dry)
        elif what == "vps_stop":
            result = deployer.stop(dry_run=dry)
        elif what == "vps_sync":
            result = deployer.sync_queue(dry_run=dry)
        else:
            return ("acción VPS desconocida: %s" % what, False, "puente")
    except Exception as exc:  # noqa: BLE001 -- el panel informa, no se cae
        note = "%s: %s" % (type(exc).__name__, exc)
        LAST["vps"] = note
        return (" · ".join(notes + [note]), False, "puente")
    detail = result.get("reason") or result.get("tail") or result.get("state") or ""
    if dry:
        detail = "plan en seco (marca la casilla para ejecutar): %s" % ", ".join(
            step["step"] for step in result.get("steps") or result.get("plan") or [])
    note = "%s%s · %s" % (what.replace("vps_", "vps "), "" if not dry else " [SECO]",
                          redact(detail, (config.secrets or {}).values()))
    LAST["vps"] = note
    return (" · ".join(notes + [note]), bool(result.get("ok")), "puente")
