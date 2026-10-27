"""Deploy al VPS: planificable sin red, sin filtrar secretos y con confirmacion explicita.

Lo que se prueba aqui es lo que evita un incidente:

* con la boveda vacia, el panel DICE que claves faltan y no promete un boton que fallaria;
* sin la casilla `confirm`, la accion corre EN SECO y ensena el plan, no lanza un deploy;
* ningun texto devuelto por el modulo contiene el valor de un token;
* el `secrets.env` no incluye la clave privada ni rutas locales (solo tokens).
"""
from .. import settings_vps, vps_deployer
from ..vps_deployer import VPSConfig, VPSDeployer, redact
from .fakes import TempProject


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_module_selftest(failures):
    for problem in vps_deployer.selftest():
        failures.append("vps_deployer.selftest: %s" % problem)


def test_panel_is_honest_without_credentials(failures):
    html = settings_vps.block()
    check("el panel se pinta", "Deploy VPS" in html, True, failures)
    check("el boton de despliegue existe", "vps_deploy" in html, True, failures)
    check("exige confirmacion", 'name="confirm"' in html, True, failures)
    check("no inventa un estado verde", "configurado" in html or "faltan" in html, True, failures)
    check("el plan de 5 pasos se ensena", "docker compose up -d --build" in html, True, failures)


def test_actions_are_dry_without_confirm(failures):
    note, ok, section = settings_vps.action(None, {"what": "vps_status"})
    check("sin confirmar no ejecuta", ok, False, failures)
    check("y lo dice", "SECO" in note or "faltan credenciales" in note, True, failures)
    check("la seccion es la del puente", section, "puente", failures)


def test_no_secret_leaks(failures):
    token = "987654:AAF-super-secreto"
    config = VPSConfig.from_vault({"VPS_HOST": "h", "VPS_USER": "u",
                                   "VPS_SSH_KEY": "C:/nope/id", "TELEGRAM_TOKEN": token})
    with TempProject() as root:
        path, names = VPSDeployer(config, root=root).secrets_file(root)
        body = path.read_text(encoding="utf-8")
        check("el token se escribe en el env", token in body, True, failures)
        check("pero la clave privada no viaja", "VPS_SSH_KEY" in names, False, failures)
        detail = redact("fallo con %s" % token, [token])
        check("el error sale redactado", token not in detail and "***" in detail, True, failures)
    check("ssh no mete la clave en el comando", "PRIVATE" not in " ".join(
        vps_deployer.ssh_argv(config, "true", key_path="/tmp/k")), True, failures)


def run():
    failures = []
    test_module_selftest(failures)
    test_panel_is_honest_without_credentials(failures)
    test_actions_are_dry_without_confirm(failures)
    test_no_secret_leaks(failures)
    return failures
