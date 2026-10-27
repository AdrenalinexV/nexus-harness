"""Una prueba por criterio, sin frases: corre la suite pedida e imprime `failures=N`.

    python tools/proofs.py relay | skills | worktree | deploy | judge | savings
                          | context | learning | oracle | tokenizer | priority

Existe para que la rubrica del turno de noche pueda exigir un criterio con un comando corto y un
`contains: failures=0`, en vez de meter una linea de Python con comillas dentro de un JSON. La suite
se importa del codigo fuente (no del motor congelado): lo que se gobierna es el repositorio.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUITES = {
    "relay": "test_relay_state",
    "skills": "test_skills",
    "worktree": "test_worktree",
    "deploy": "test_deploy",
    "judge": "test_judge_repair",
    "savings": "test_savings",
    "context": "test_context",
    "learning": "test_learning",
    "oracle": "test_oracle",
    "tokenizer": "test_tokenizer",
}


def run_suite(name):
    import importlib
    module = importlib.import_module("nexus_harness.selftests.%s" % SUITES[name])
    problems = list(module.run())
    for problem in problems:
        print("  - %s" % problem)
    return problems


def priority():
    """La cola tiene a Nexus-Harness #1 y su spec congelada esta presente y legible."""
    from nexus_harness import projects
    from nexus_harness.config import HarnessConfig
    config = HarnessConfig.load()
    order = projects.order(config)
    spec = projects.spec_of(ROOT)
    problems = []
    if not order or order[0] != "Nexus-Harness":
        problems.append("Nexus-Harness no es el #1 de la cola: %r" % (order[:4],))
    if not spec.get("present"):
        problems.append("Nexus-Harness no tiene .ai/CURRENT_SPEC.json")
    elif int(spec.get("criteria") or 0) < 1:
        problems.append("la spec no declara criterios")
    for problem in problems:
        print("  - %s" % problem)
    return problems


def main(argv):
    name = (argv or [""])[0]
    if name == "priority":
        problems = priority()
    elif name in SUITES:
        problems = run_suite(name)
    else:
        print("prueba desconocida: %r (usa %s, priority)" % (name, ", ".join(sorted(SUITES))))
        return 20
    print("failures=%d" % len(problems))
    return 0 if not problems else 10


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
