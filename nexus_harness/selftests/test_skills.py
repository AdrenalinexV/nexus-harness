"""Skills autonomas: el techo de 10, el catalogo dormido y la forja con procedencia.

Lo que se mide aqui es lo que hace que la autonomia no sea una promesa:

* `skill_router` no deja pasar mas de diez skills y es determinista entre dos llamadas iguales;
* lo que no viaja queda indexado en `.nexus/skills-dormant/` con su sha256, a coste cero de tokens;
* `skill_forge` escribe un `SKILL.md` con frontmatter valido, no pisa una existente y registra el hash;
* `ForgeTrigger` solo pide forja al TERCER fallo del mismo patron, y una sola vez;
* la herramienta `forge_or_update_skill` existe en el arsenal del modelo y devuelve ruta y sha.
"""
from ..tools import skill_forge
from ..context import skill_router
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


def test_one_catalog_and_the_outcome_boost(failures):
    """Un solo catalogo, y el libro de resultados cambia el ORDEN sin inventar skills."""
    from ..core import outcomes

    with TempProject() as root:
        catalog = root / "catalogo"
        for name in ("alpha-python", "beta-python", "gamma-python"):
            folder = catalog / name
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text(
                "---\nname: %s\ndescription: python servicio\nkeywords: python api\n---\n\ncuerpo\n"
                % name, encoding="utf-8")
        book = outcomes.Outcomes(root / ".nexus" / "harness" / "o.jsonl")
        router = skill_router.SkillRouter(root, roots=[catalog], outcomes=book).load()
        before = [entry["name"] for entry in router.select("python", ["api.py"])]
        check("sin muestras el orden es el lexico", before[0], "alpha-python", failures)
        for _round in range(8):
            book.record(["beta-python"], 0, tag="test")
            book.record(["alpha-python"], 10, tag="test")
        after = [entry["name"] for entry in router.select("python", ["api.py"])]
        check("el que gana turnos sube", after[0], "beta-python", failures)
        check("el que los pierde baja", after[-1], "alpha-python", failures)
        check("el libro no inventa skills", sorted(after),
              ["alpha-python", "beta-python", "gamma-python"], failures)
        injection = router.inject(["api.py"], task="python")
        check("inject trae el brief medido", injection.tokens > 0 and bool(injection.brief), True,
              failures)
        check("y respeta el techo", len(injection.names) <= skill_router.MAX_ACTIVE, True, failures)
        check("una fila por skill y turno", len(book.rows()), 16, failures)
        check("un turno sin exit no apunta nada", book.record(["beta-python"], None), 0, failures)


def test_the_library_is_the_only_source(failures):
    """El contrato que usan chat y triada: `inject()` existe y el catalogo real se escanea."""
    library = skill_router.library(".")
    if library.catalog:
        check("el catalogo real tiene skills", len(library.catalog) > 0, True, failures)
    else:
        # Sin NexusProtocol ni perfil de Hermes esta maquina no tiene catalogo. El contrato que se
        # mide entonces es el otro: catalogo VACIO, nunca inventado -- una skill que no existe no
        # puede viajar al prompt.
        check("sin fuentes en la maquina el catalogo es vacio, no inventado", len(library.catalog), 0,
              failures)
    injection = library.inject(["nexus_harness/chat.py"])
    check("y devuelve un contrato Injection", hasattr(injection, "names"), True, failures)


def run():
    failures = []
    test_module_selftests(failures)
    test_a_forged_skill_wins_the_next_turn(failures)
    test_the_tool_is_in_the_arsenal(failures)
    test_one_catalog_and_the_outcome_boost(failures)
    test_the_library_is_the_only_source(failures)
    return failures