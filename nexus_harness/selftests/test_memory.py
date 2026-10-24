"""Memory: a file you can `cat`, a block that travels, and two limits that are actually enforced."""
import tempfile
from pathlib import Path

from ..memory import MAX_CHARS, MAX_ENTRIES, Memory


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def run():
    failures = []
    with tempfile.TemporaryDirectory(prefix="nexus-memory-") as folder:
        memory = Memory(Path(folder) / "memory.md")
        check("an empty memory sends nothing", memory.block(), "", failures)
        first = memory.add("El operador prefiere respuestas cortas")
        check("an entry lands", first.get("ok"), True, failures)
        check("and reads back", memory.entries(), ["El operador prefiere respuestas cortas"],
              failures)
        check("a duplicate is not stored twice", memory.add(
            "El operador prefiere respuestas cortas").get("duplicate"), True, failures)
        check("still one entry", len(memory.entries()), 1, failures)
        check("an empty entry is refused", memory.add("   ").get("ok"), False, failures)
        memory.add("El proyecto vive en C:\\Proyectos\\Nexus-Harness")
        block = memory.block()
        check("the block carries both", ("respuestas cortas" in block, "Nexus-Harness" in block),
              (True, True), failures)
        check("the header is not an entry", any("# Nexus-Harness memory" in entry
                                                for entry in memory.entries()), False, failures)
        removed = memory.remove("Nexus-Harness")
        check("removal by substring", (removed.get("ok"), removed.get("removed")), (True, 1),
              failures)
        check("a removal that matches nothing says so", memory.remove("inexistente").get("ok"),
              False, failures)
        huge = memory.add("x" * (MAX_CHARS + 10))
        check("an entry that cannot fit is refused", huge.get("ok"), False, failures)
        check("and the refusal explains the limit", "corract" in huge.get("reason", "")
              or "consolidate" in huge.get("reason", ""), True, failures)
        for index in range(MAX_ENTRIES + 2):
            memory.add("hecho %d" % index)
        check("the entry limit holds", len(memory.entries()) <= MAX_ENTRIES, True, failures)
        state = memory.as_dict()
        check("state reports the cap", (state["limit_chars"], state["limit_entries"]),
              (MAX_CHARS, MAX_ENTRIES), failures)
        check("the file exists on disk", Path(state["path"]).is_file(), True, failures)
    return failures
