"""Context router: the arithmetic of the protocol, driven from the harness.

Asserted here:
* the two level-1 rules always travel;
* a test file calls the TDD specialist first;
* the same file list gives the same answer twice (a brief that changes between runs is not a brief);
* an unrelated file wakes nobody;
* an unavailable engine is reported, not silently treated as "no specialists".
"""
from ..context_router import ContextRouter


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def run():
    failures = []
    router = ContextRouter(lang="es")
    check("the engine is importable", router.available, True, failures)
    always = router.select([])
    check("level 1 travels even with no files",
          ("nexus-verification" in always.names, "nexus-clean-code" in always.names),
          (True, True), failures)
    tests = router.select(["src/test_login.py"])
    check("a test file calls the TDD specialist first",
          tests.names[2] if len(tests.names) > 2 else "", "nexus-tdd", failures)
    check("and the brief carries its rules", "Red, green, refactor" in tests.brief, True, failures)
    check("the injection is priced", tests.tokens > 0, True, failures)
    first = router.select(["src/app.py", "src/test_login.py", "styles.css"]).names
    second = router.select(["src/app.py", "src/test_login.py", "styles.css"]).names
    check("two identical calls agree", first, second, failures)
    check("at most two specialists travel", len(router.select(
        ["a.py", "b.ts", "c.css", "Dockerfile", "test_x.py"]).names), 4, failures)
    nothing = router.select(["assets/logo.png"])
    check("an irrelevant file wakes nobody", nothing.names,
          ["nexus-verification", "nexus-clean-code"], failures)
    disabled = ContextRouter(enabled=False).select(["src/test_login.py"])
    check("disabled routing travels with nothing", disabled.names, [], failures)
    return failures
