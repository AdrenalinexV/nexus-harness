"""Onboarding: what it probes, what it writes, and what it refuses to write.

The suites point the module's two stores at a temporary directory, so nothing here touches the
operator's real `~/.nexus/harness.json` or vault -- and the governance call is the real one, against a
throwaway project, because that is the part most likely to drift.
"""
from pathlib import Path

from .fakes import TempProject
from ..platform import vault
from .. import onboarding


def check(name, got, expect, failures=None):
    if got != expect:
        message = "%s: %r, esperaba %r" % (name, got, expect)
        if failures is None:
            raise AssertionError(message)
        failures.append(message)


def test_probe_shape(failures):
    found = onboarding.probe_local(timeout=0.05)
    check("both local vendors are probed", sorted(found), ["lmstudio", "ollama"])
    for vendor, row in found.items():
        check("%s reports a url" % vendor, bool(row["url"]), True)
        check("%s reports readiness as a boolean" % vendor, isinstance(row["ready"], bool), True)


def test_apply_writes_roles_and_keys(failures):
    import tempfile

    with tempfile.TemporaryDirectory(prefix="nexus-onboarding-") as workspace, TempProject() as root:
        base = Path(workspace)
        config_file = base / "harness.json"
        secrets_file = base / "secrets.json"
        onboarding.CONFIG_FILE = config_file
        vault.SECRETS = secrets_file
        config = onboarding.HarnessConfig.load(path=config_file, root=root)
        result = onboarding.apply(config, {
            "roles": {"director": "lmstudio:qwen-test", "worker": "openai:gpt-4o-mini"},
            "project": str(root), "test_command": "python -m pytest -q", "probe": False,
            "keys": {"OPENAI_API_KEY": "sk-test-123", "notakey": "nope"}})
        check("the apply is accepted", result["ok"], True)
        written = config_file.read_text(encoding="utf-8")
        check("roles landed in the config", "qwen-test" in written and "gpt-4o-mini" in written, True)
        check("the project landed", str(root).replace("\\", "\\\\") in written or str(root) in written,
              True)
        check("the test command landed", "pytest" in written, True)
        check("the key is reported, not echoed", result["saved"]["keys"], ["OPENAI_API_KEY"])
        check("a non-key name is refused", any("ignored key names" in note for note in result["notes"]),
              True)
        check("the key can be read back by the engine", vault.load(secrets_file)["OPENAI_API_KEY"],
              "sk-test-123")
        check("the status has no secret value in it", "sk-test-123" in str(result["status"]), False)


def test_apply_refuses_a_bad_spec(failures):
    import tempfile

    with tempfile.TemporaryDirectory(prefix="nexus-onboarding-") as workspace, TempProject() as root:
        base = Path(workspace)
        onboarding.CONFIG_FILE = base / "harness.json"
        vault.SECRETS = base / "secrets.json"
        config = onboarding.HarnessConfig.load(path=base / "harness.json", root=root)
        result = onboarding.apply(config, {"roles": {"director": "nope:model"}, "probe": False})
        check("nothing is saved", result["ok"], False)
        check("and the reason is a provider error",
              any("unknown provider" in note for note in result["notes"]), True)
        check("no config file is invented", (base / "harness.json").exists(), False)


def test_governance_is_real(failures):
    import tempfile

    with tempfile.TemporaryDirectory(prefix="nexus-onboarding-") as workspace, TempProject() as root:
        base = Path(workspace)
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        onboarding.CONFIG_FILE = base / "harness.json"
        vault.SECRETS = base / "secrets.json"
        config = onboarding.HarnessConfig.load(path=base / "harness.json", root=root)
        result = onboarding.apply(config, {"project": str(root), "governance": True, "probe": False})
        governance = result["saved"].get("governance") or {}
        if not governance.get("ok"):
            # Sin gobernador no hay auto-spec, y lo que se mide aqui es que lo DIGA con su motivo y no
            # invente una spec vacia: una spec sin criterios es un contrato que no existe.
            check("without the governor it says why it could not govern",
                  "NexusProtocol" in str(governance.get("reason")), True, failures)
            check("and no spec is invented on disk",
                  (root / ".ai" / "CURRENT_SPEC.json").is_file(), False, failures)
            return
        check("the auto-spec ran", governance.get("ok"), True)
        check("and wrote the spec", (root / ".ai" / "CURRENT_SPEC.json").is_file(), True)
        check("with its language detected", governance.get("language"), "python")
        check("and a hash", len(str(governance.get("sha256") or "")), 64)


def run():
    failures = []
    test_probe_shape(failures)
    test_apply_writes_roles_and_keys(failures)
    test_apply_refuses_a_bad_spec(failures)
    test_governance_is_real(failures)
    return failures
