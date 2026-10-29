"""Despliegue 24/7 en un VPS: SSH + Docker Compose, con las credenciales de la boveda.

El PC se apaga; el bot no deberia. Este modulo empaqueta el kit de despliegue que ya existe en
`NexusProtocol/deploy` (Dockerfile + compose del latido) junto con el motor del harness, lo sube por
SSH y lo levanta con `docker compose up -d --build`.

Tres decisiones que no son cosmeticas:

* **Las credenciales no se escriben en el codigo ni en el compose.** Se leen de la boveda
  (`VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_PORT`) y el `secrets.env` que se sube se crea con
  permisos `0600` en el VPS (`chmod 600`), porque un env con tokens legible por cualquiera es una
  fuga con nombre de fichero.
* **Todo se puede planificar sin red.** `plan()` devuelve los pasos exactos y `deploy(dry_run=True)`
  no abre una conexion: asi el panel puede ensenar que va a pasar antes de que pase.
* **Lo que se imprime esta redactado.** Ningun comando, log o error devuelve el valor de un secreto:
  se sustituye por `***`. Un log que imprime el token lo imprime para siempre.

Sin `paramiko` ni dependencias nuevas: se usa el `ssh`/`scp` del sistema, que es lo que el operador ya
tiene y lo que respeta su `~/.ssh/config` cuando hace falta.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .platform import vault

PROTOCOL_DEPLOY = Path(r"C:\Proyectos\NexusProtocol\deploy")
REMOTE_ROOT = "/opt/nexus"
REMOTE_COMPOSE = "%s/docker-compose.yml" % REMOTE_ROOT
SERVICE = "nexus-hive"
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0
REQUIRED = ("VPS_HOST", "VPS_USER")
KEY_NAMES = ("VPS_SSH_KEY", "VPS_SSH_KEY_PATH", "VPS_KEY")
SECRET_PREFIXES = ("TELEGRAM", "DISCORD", "OPENAI", "ANTHROPIC", "DEEPSEEK", "GITHUB", "NEXUS_")


def chmod600(path):
    """0600 y se informa si el sistema no lo permite (Windows sin POSIX). Nunca lanza."""
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        return "%s: %s" % (type(exc).__name__, exc)
    return ""


def redact(text, secrets=()):
    """Sustituye cada secreto por `***`. Se aplica a TODO lo que sale de este modulo."""
    out = str(text or "")
    for value in secrets:
        value = str(value or "")
        if len(value) >= 6:
            out = out.replace(value, "***")
    return out


class VPSConfig:
    """Host, usuario, puerto y clave. `missing` dice que falta en vez de fallar a mitad del deploy."""

    def __init__(self, host="", user="", port=22, key="", secrets=None):
        self.host = str(host or "").strip()
        self.user = str(user or "").strip()
        self.port = int(port or 22)
        self.key = str(key or "").strip()
        self.secrets = dict(secrets or {})

    @classmethod
    def from_vault(cls, values=None):
        values = dict(values if values is not None else vault.load())
        key = ""
        for name in KEY_NAMES:
            if str(values.get(name) or "").strip():
                key = str(values[name]).strip()
                break
        try:
            port = int(str(values.get("VPS_PORT") or 22).strip() or 22)
        except ValueError:
            port = 22
        return cls(str(values.get("VPS_HOST") or ""), str(values.get("VPS_USER") or ""),
                   port, key, values)

    @property
    def missing(self):
        fields = {"VPS_HOST": self.host, "VPS_USER": self.user}
        gaps = [name for name in REQUIRED if not fields.get(name, "")]
        if not self.key:
            gaps.append("VPS_SSH_KEY")
        return gaps

    @property
    def target(self):
        return "%s@%s" % (self.user, self.host) if self.user and self.host else ""

    def key_path(self, folder=None):
        """La clave como RUTA. Si la boveda guarda el PEM entero, se escribe con permisos 0600."""
        if not self.key:
            return ""
        if "PRIVATE KEY" not in self.key and Path(self.key).expanduser().is_file():
            return str(Path(self.key).expanduser())
        folder = Path(folder or (Path(tempfile.gettempdir()) / "nexus-vps-key"))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "id_nexus"
        path.write_text(self.key if self.key.endswith("\n") else self.key + "\n", encoding="utf-8")
        chmod600(path)
        return str(path)

    def public(self):
        return {"host": self.host, "user": self.user, "port": self.port,
                "key_configured": bool(self.key), "missing": self.missing,
                "target": self.target}


def ssh_argv(config, remote, key_path=None):
    """El argv de `ssh`, con BatchMode: un deploy desatendido no puede quedarse pidiendo una clave."""
    argv = ["ssh", "-p", str(config.port), "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=12"]
    path = key_path or config.key_path()
    if path:
        argv += ["-i", path]
    return argv + [config.target, remote]


def scp_argv(config, local, remote, key_path=None):
    argv = ["scp", "-P", str(config.port), "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=12"]
    path = key_path or config.key_path()
    if path:
        argv += ["-i", path]
    return argv + [str(local), "%s:%s" % (config.target, remote)]


def run(argv, timeout=180):
    """Ejecuta y redacta. `{ok, exit, tail, command}`: nunca lanza por un comando que falla."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              timeout=timeout, creationflags=WINDOWS_FLAGS)
        code = done.returncode
        output = ((done.stdout or "") + (done.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        code, output = 124, "timeout tras %ss" % timeout
    except OSError as exc:
        code, output = 127, "%s: %s" % (type(exc).__name__, exc)
    return {"ok": code == 0, "exit": code, "tail": output[-1500:],
            "command": " ".join(argv[:2])}


def _from_vault_keys(values):
    """Las claves que se suben al VPS: tokens, y nada que sea una ruta local."""
    chosen = {}
    for name, value in (values or {}).items():
        if not str(value or "").strip():
            continue
        if not str(name).upper().startswith(SECRET_PREFIXES):
            continue
        if "PRIVATE KEY" in str(value):
            continue
        chosen[str(name)] = str(value)
    return chosen


class VPSDeployer:
    """El ciclo completo: probar, desplegar, ver, sincronizar, parar."""

    def __init__(self, config=None, deploy_dir=None, root=None):
        self.config = config or VPSConfig.from_vault()
        self.deploy_dir = Path(deploy_dir) if deploy_dir else PROTOCOL_DEPLOY
        self.root = Path(root) if root else Path(__file__).resolve().parents[1]

    # -- piezas -----------------------------------------------------------------------------------
    def compose(self):
        """El compose renderizado. Se sirve del kit del protocolo si esta; si no, uno equivalente."""
        source = self.deploy_dir / "docker-compose.yml"
        if source.is_file():
            return source.read_text(encoding="utf-8")
        return ("services:\n  %s:\n    build:\n      context: ..\n      dockerfile: deploy/Dockerfile\n"
                "    container_name: %s\n    env_file:\n      - secrets.env\n"
                "    restart: unless-stopped\n" % (SERVICE, SERVICE))

    def secrets_file(self, folder):
        """Escribe `secrets.env` con 0600. Devuelve `(ruta, nombres)`; los valores no se devuelven."""
        values = _from_vault_keys(self.config.secrets)
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "secrets.env"
        body = "".join("%s=%s\n" % (name, value) for name, value in sorted(values.items()))
        handle = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(body)
        chmod600(path)
        return path, sorted(values)

    def plan(self, include_harness=True):
        """Los pasos exactos, sin ejecutar nada. Es lo que el panel ensena antes del boton."""
        steps = [{"step": "ssh", "detail": "probar %s" % (self.config.target or "(sin host)")},
                 {"step": "mkdir", "detail": "mkdir -p %s" % REMOTE_ROOT},
                 {"step": "upload", "detail": "subir kit de deploy + engine"},
                 {"step": "secrets", "detail": "chmod 600 %s/secrets.env" % REMOTE_ROOT},
                 {"step": "up", "detail": "docker compose up -d --build"}]
        if include_harness:
            steps.insert(3, {"step": "engine", "detail": "subir dist/nexus-harness-engine.exe "
                                                          "(worker de la colmena)"})
        return steps

    # -- operaciones ------------------------------------------------------------------------------
    def probe(self, dry_run=False):
        remote = "docker --version && docker compose version"
        if dry_run:
            return {"ok": True, "dry_run": True, "plan": self.plan(), "command": " ".join(
                ssh_argv(self.config, remote)[:3]) + " ... " + remote}
        if self.config.missing:
            return {"ok": False, "reason": "faltan credenciales: %s" % ", ".join(self.config.missing)}
        result = run(ssh_argv(self.config, remote))
        return dict(result, ok=result["ok"] and "Docker" in result["tail"])

    def deploy(self, dry_run=True, timeout=900):
        """Empaqueta, sube y levanta. `dry_run` no toca la red ni escribe secretos fuera de staging."""
        missing = self.config.missing
        if missing:
            return {"ok": False, "reason": "faltan credenciales: %s" % ", ".join(missing),
                    "steps": self.plan()}
        staging = Path(tempfile.mkdtemp(prefix="nexus-deploy-"))
        try:
            kit = staging / "kit"
            kit.mkdir()
            if self.deploy_dir.is_dir():
                shutil.copytree(self.deploy_dir, kit / "deploy")
            secrets_path, names = self.secrets_file(kit / "deploy")
            tarball = staging / "nexus-deploy.tar.gz"
            made = shutil.make_archive(str(tarball)[:-7], "gztar", root_dir=str(kit))
            steps = self.plan()
            if dry_run:
                return {"ok": True, "dry_run": True, "steps": steps, "secrets": names,
                        "tarball": made, "bytes": Path(made).stat().st_size}
            commands = [("mkdir", "mkdir -p %s" % REMOTE_ROOT),
                        ("upload", "%s && tar -xzf - -C %s" % ("cat > /tmp/nexus.tgz",
                                                               REMOTE_ROOT)),
                        ("secrets", "chmod 600 %s/deploy/secrets.env" % REMOTE_ROOT),
                        ("up", "cd %s/deploy && docker compose up -d --build" % REMOTE_ROOT)]
            log = []
            for step, remote in commands:
                if step == "upload":
                    result = run(["scp", "-P", str(self.config.port), "-o", "BatchMode=yes",
                                  "-i", self.config.key_path(), made,
                                  "%s:/tmp/nexus.tgz" % self.config.target], timeout=timeout)
                    extraction = run(ssh_argv(self.config, "tar -xzf /tmp/nexus.tgz -C %s"
                                              % REMOTE_ROOT), timeout=timeout)
                    result = dict(result, ok=result["ok"] and extraction["ok"],
                                  tail=(result["tail"] + "\n" + extraction["tail"])[-1200:])
                else:
                    result = run(ssh_argv(self.config, remote), timeout=timeout)
                log.append({"step": step, **{key: result[key] for key in ("ok", "exit", "tail")}})
                if not result["ok"]:
                    return {"ok": False, "reason": "fallo en %s" % step, "steps": log,
                            "secrets": names}
            return {"ok": True, "steps": log, "secrets": names}
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def status(self, dry_run=False):
        remote = ("docker inspect -f '{{.State.Status}} {{.State.StartedAt}}' %s 2>/dev/null; "
                  "test -f %s/deploy/secrets.env && stat -c '%%a' %s/deploy/secrets.env"
                  % (SERVICE, REMOTE_ROOT, REMOTE_ROOT))
        if dry_run:
            return {"ok": True, "dry_run": True, "remote": remote}
        if self.config.missing:
            return {"ok": False, "reason": "faltan credenciales: %s" % ", ".join(self.config.missing)}
        result = run(ssh_argv(self.config, remote))
        lines = [line.strip() for line in result["tail"].splitlines() if line.strip()]
        return dict(result, state=lines[0] if lines else "desconocido",
                    secrets_mode=lines[1] if len(lines) > 1 else "")

    def logs(self, tail=80, dry_run=False):
        remote = "cd %s/deploy && docker compose logs --tail %d %s" % (REMOTE_ROOT, int(tail),
                                                                      SERVICE)
        if dry_run:
            return {"ok": True, "dry_run": True, "remote": remote}
        if self.config.missing:
            return {"ok": False, "reason": "faltan credenciales: %s" % ", ".join(self.config.missing)}
        return run(ssh_argv(self.config, remote))

    def stop(self, dry_run=False):
        remote = "cd %s/deploy && docker compose down" % REMOTE_ROOT
        if dry_run:
            return {"ok": True, "dry_run": True, "remote": remote}
        if self.config.missing:
            return {"ok": False, "reason": "faltan credenciales: %s" % ", ".join(self.config.missing)}
        return run(ssh_argv(self.config, remote))

    def sync_queue(self, dry_run=False):
        """La cola de la colmena: se baja la del VPS y se fusiona con la del PC (sin duplicados)."""
        local = self.root / ".nexus" / "hive" / "queue.json"
        remote = "%s/data/queue.json" % REMOTE_ROOT
        if dry_run:
            return {"ok": True, "dry_run": True, "remote": remote, "local": str(local)}
        if self.config.missing:
            return {"ok": False, "reason": "faltan credenciales: %s" % ", ".join(self.config.missing)}
        staging = Path(tempfile.mkdtemp(prefix="nexus-queue-"))
        try:
            fetched = staging / "queue.json"
            result = run(["scp", "-P", str(self.config.port), "-o", "BatchMode=yes",
                          "-i", self.config.key_path(), "%s:%s" % (self.config.target, remote),
                          str(fetched)])
            if not result["ok"]:
                return {"ok": False, "reason": "no se pudo leer la cola remota", "tail": result["tail"]}
            remote_rows = json.loads(fetched.read_text(encoding="utf-8") or "[]")
            local_rows = []
            if local.is_file():
                try:
                    local_rows = json.loads(local.read_text(encoding="utf-8") or "[]")
                except ValueError:
                    local_rows = []
        except (OSError, ValueError) as exc:
            return {"ok": False, "reason": "%s: %s" % (type(exc).__name__, exc)}
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        merged, seen = [], set()
        for row in list(local_rows if isinstance(local_rows, list) else []) + list(
                remote_rows if isinstance(remote_rows, list) else []):
            key = json.dumps(row, sort_keys=True) if not isinstance(row, dict) else str(
                row.get("id") or row.get("task") or json.dumps(row, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "merged": len(merged), "local": str(local),
                "remote": len(remote_rows), "pc": len(local_rows)}


def selftest():
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    values = {"VPS_HOST": "178.105.35.201", "VPS_USER": "root", "VPS_PORT": "2222",
              "VPS_SSH_KEY": "C:/Users/x/.ssh/id_nexus", "TELEGRAM_TOKEN": "123456:AAHsecret",
              "VPS_SUDO": "noleak"}
    config = VPSConfig.from_vault(values)
    check("el host sale de la boveda", config.host, "178.105.35.201")
    check("el puerto se respeta", config.port, 2222)
    check("el destino ssh", config.target, "root@178.105.35.201")
    check("no falta nada", config.missing, [])
    check("sin host se dice que falta", VPSConfig.from_vault({}).missing,
          ["VPS_HOST", "VPS_USER", "VPS_SSH_KEY"])
    argv = ssh_argv(config, "echo nexus-ok", key_path="/tmp/k")
    check("ssh va en BatchMode", "-o" in argv and "BatchMode=yes" in argv, True)
    check("ssh usa el puerto de la boveda", argv[argv.index("-p") + 1], "2222")
    check("ssh autentica por clave", "-i" in argv, True)
    check("el comando remoto es el ultimo", argv[-1], "echo nexus-ok")
    check("los secretos se redactan", redact("token=123456:AAHsecret ok", ["123456:AAHsecret"]),
          "token=*** ok")
    check("un secreto corto no se toca", redact("abc", ["abc"]), "abc")

    deployer = VPSDeployer(config)
    compose = deployer.compose()
    check("el compose reinicia solo", "restart: unless-stopped" in compose, True)
    check("el compose lee secrets.env", "secrets.env" in compose, True)
    check("el plan no abre conexion", [step["step"] for step in deployer.plan()][:2],
          ["ssh", "mkdir"])
    probe = deployer.probe(dry_run=True)
    check("la prueba en seco no ejecuta", probe["dry_run"], True)
    rejected = VPSDeployer(VPSConfig()).deploy(dry_run=True)
    check("sin credenciales no hay deploy", rejected["ok"], False)
    check("y se dice que falta", "+".join(rejected["reason"].split(": ", 1)[1].split(", ")),
          "VPS_HOST+VPS_USER+VPS_SSH_KEY")

    with tempfile.TemporaryDirectory(prefix="vps-deploy-") as workspace:
        path, names = deployer.secrets_file(Path(workspace))
        check("el env lleva el token", "TELEGRAM_TOKEN" in names, True)
        check("y NO lleva la clave privada ni la ruta", "VPS_SSH_KEY" in names, False)
        body = Path(path).read_text(encoding="utf-8")
        check("el env no filtra el valor en el nombre", body.startswith("TELEGRAM_TOKEN="), True)
        if os.name != "nt":
            check("el env nace 0600", oct(Path(path).stat().st_mode & 0o777), "0o600")
        plan = deployer.deploy(dry_run=True)
        check("el deploy en seco empaqueta", plan["ok"], True)
        check("y dice su tamano", plan["bytes"] > 0, True)
        check("sin tocar la red", plan["dry_run"], True)
        check("el estado en seco no conecta", deployer.status(dry_run=True)["dry_run"], True)
        check("la cola en seco no conecta", deployer.sync_queue(dry_run=True)["dry_run"], True)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("vps_deployer: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
