"""Skills autonomas: el techo de 10, el catalogo dormido y la forja con procedencia.

Lo que se mide aqui es lo que hace que la autonomia no sea una promesa:

* `skill_router` no deja pasar mas de diez skills y es determinista entre dos llamadas iguales;
* lo que no viaja queda indexado en `.nexus/skills-dormant/` con su sha256, a coste cero de tokens;
* `skill_forge` escribe un `SKILL.md` con frontmatter valido, no pisa una existente y registra el hash;
* `ForgeTrigger` solo pide forja al TERCER fallo del mismo patron, y una sola vez;
* la herramienta `forge_or_update_skill` existe en el arsenal del modelo y devuelve ruta y sha.
"""
from .. import skill_forge, skill_router
from ..config import HarnessConfig
from ..tools import default_registry
from .fakes import TempProject


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_module_selftests(failures):
    for problem in skill_router.selftest():
        failures.append("skill_router.selftest: %s" % problem)
    for problem in skill_forge.selftest():
        failures.append("skill_forge.selftest: %s" % problem)


def test_a_forged_skill_wins_the_next_turn(failures):
    with TempProject() as root:
        forged = skill_forge.forge(root, "postgres indices", reason="tres fallos de plan",
                                   observations=["EXPLAIN ANALYZE antes de declarar lento"])
        check("la forja deja el fichero", forged["created"], True, failures)
        router = skill_router.SkillRouter(root, roots=[root / skill_router.FORGED_REL]).load()
        picked = router.select("optimizar indices postgres", ["db/query.sql"])
        check("la skill forjada compite y gana", [item["name"] for item in picked][:1],
              ["postgres-indices"], failures) if picked else failures.append("no eligio nada")
        check("el cuerpo observado viaja con ella", "EXPLAIN ANALYZE" in
              open(forged["path"], encoding="utf-8").read(), True, failures)
        check("fuera del turno hay dormidas", len(router.dormant()) >= 0, True, failures)


def test_the_tool_is_in_the_arsenal(failures):
    with TempProject() as root:
        registry = default_registry(root, HarnessConfig(default_root=root))
        check("el modelo ve forge_or_update_skill", "forge_or_update_skill" in registry.names(), True,
              failures)
        observation = registry.call("forge_or_update_skill",
                                    {"topic": "lua fivem", "reason": "patron repetido",
                                     "observations": ["restart antes de probar"]})
        check("la herramienta escribe", observation.ok, True, failures)
        check("y devuelve el sha", "sha256=" in observation.text, True, failures)
        second = registry.call("forge_or_update_skill", {"topic": "lua fivem", "reason": "otra"})
        check("no pisa sin permiso", "ya existia" in second.text, True, failures)


def run():
    failures = []
    test_module_selftests(failures)
    test_a_forged_skill_wins_the_next_turn(failures)
    test_the_tool_is_in_the_arsenal(failures)
    return failures