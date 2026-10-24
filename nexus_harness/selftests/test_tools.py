"""Tools: bounds, refusals, and the two properties everything else depends on.

The two that matter: a path outside the root is refused, and a patch that would break the 400-line law
does not land. Both are asserted here because both are easy to lose in a refactor and impossible to
notice until a model has already written outside the project.
"""
from .fakes import TempProject
from ..tools import default_registry


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_registry(failures, root):
    registry = default_registry(root)
    check("nine tools", len(registry.names()), 9, failures)
    check("schemas match handlers", len(registry.schemas()), len(registry.names()), failures)
    unknown = registry.call("rm_rf", {})
    check("an unknown tool is an observation", unknown.ok, False, failures)
    check("and it names what it has", "read_file" in unknown.text, True, failures)


def test_files(failures, root):
    registry = default_registry(root)
    read = registry.call("read_file", {"path": "calc.py"})
    check("read is ok", read.ok, True, failures)
    check("read is numbered", read.text.splitlines()[0].strip().startswith("1|"), True, failures)
    check("read names the file it touched", read.files, ["calc.py"], failures)
    write = registry.call("write_file", {"path": "nested/new.py", "content": "x = 1\n"})
    check("write creates parents", write.ok, True, failures)
    too_long = registry.call("write_file", {"path": "big.py", "content": "x = 1\n" * 401})
    check("401 lines is refused at the tool", too_long.ok, False, failures)
    check("and the refusal says the law", "400" in too_long.text, True, failures)
    escape = registry.call("read_file", {"path": "../../secrets.txt"})
    check("a path outside the root is refused", escape.ok, False, failures)
    search = registry.call("search", {"pattern": "return a - b"})
    check("search finds the line", "calc.py:2" in search.text, True, failures)
    listing = registry.call("list_dir", {"path": "."})
    check("list_dir shows the tree", "calc.py" in listing.text, True, failures)


def test_patch(failures, root):
    registry = default_registry(root)
    ok = registry.call("patch", {"path": "calc.py", "search": "return a - b",
                                 "replace": "return a + b"})
    check("exact patch applies", ok.ok, True, failures)
    check("and the file changed", "a + b" in (root / "calc.py").read_text(encoding="utf-8"),
          True, failures)
    again = registry.call("patch", {"path": "calc.py", "search": "return a - b",
                                    "replace": "return a * b"})
    check("a search that no longer exists is refused", again.ok, False, failures)
    (root / "dup.py").write_text("value = 1\nvalue = 1\n", encoding="utf-8")
    ambiguous = registry.call("patch", {"path": "dup.py", "search": "value = 1",
                                        "replace": "value = 2"})
    check("two candidates is an error, not a guess", ambiguous.ok, False, failures)
    check("and it says how many", "appears 2 times" in ambiguous.text, True, failures)
    (root / "long.py").write_text("\n".join("x%d = %d" % (i, i) for i in range(398)) + "\n",
                                  encoding="utf-8")
    breaker = registry.call("patch", {"path": "long.py", "search": "x0 = 0",
                                      "replace": "x0 = 0\ny0 = 0\ny1 = 1\ny2 = 2"})
    check("a patch that breaks the line law is refused", breaker.ok, False, failures)
    check("and the file is untouched", (root / "long.py").read_text(encoding="utf-8").count("\n"),
          398, failures)


def test_blocks(failures, root):
    registry = default_registry(root)
    blocks = """<<<<<<< SEARCH
def add(a, b):
=======
def add(a, b):
>>>>>>> REPLACE
<<<<<<< SEARCH
    return a - b
=======
    return a + b
>>>>>>> REPLACE"""
    applied = registry.call("apply_blocks", {"path": "calc.py", "blocks": blocks})
    check("both blocks apply", applied.ok, True, failures)
    check("and both landed", "a + b" in (root / "calc.py").read_text(encoding="utf-8"),
          True, failures)
    before = (root / "calc.py").read_text(encoding="utf-8")
    atomic = registry.call("apply_blocks", {"path": "calc.py", "blocks": blocks})
    check("re-applying is refused (search is gone)", atomic.ok, False, failures)
    check("and nothing was written", (root / "calc.py").read_text(encoding="utf-8"), before,
          failures)


def test_crlf(failures, root):
    """A Windows repository keeps its CRLF, and the normalised rung must not double the `\\r`."""
    registry = default_registry(root)
    (root / "crlf.py").write_bytes(b"def f():\r\n    return 1\r\n")
    registry.call("patch", {"path": "crlf.py", "search": "    return 1",
                            "replace": "    return 2"})
    raw = (root / "crlf.py").read_bytes()
    check("an exact patch keeps CRLF", raw, b"def f():\r\n    return 2\r\n", failures)
    (root / "crlf2.py").write_bytes(b"def g():\r\n    return 1   \r\n")
    normalised = registry.call("patch", {"path": "crlf2.py", "search": "    return 1\n",
                                         "replace": "    return 9\n"})
    check("the normalised rung applies", normalised.ok, True, failures)
    raw = (root / "crlf2.py").read_bytes()
    check("with no doubled carriage return", b"\r\r\n" in raw, False, failures)
    check("and the newline style intact", b"    return 9\r\n" in raw, True, failures)


def test_shell(failures, root):
    registry = default_registry(root)
    ok = registry.call("shell", {"command": "echo hola"})
    check("shell runs", ok.ok, True, failures)
    check("and reports its exit", ok.meta.get("exit"), 0, failures)
    bad = registry.call("shell", {"command": "exit 3"})
    check("a non-zero exit is still an observation", bad.ok, True, failures)
    check("with the code intact", bad.meta.get("exit"), 3, failures)
    refused = registry.call("shell", {"command": "shutdown /s /t 0"})
    check("destructive shapes are refused", refused.ok, False, failures)


def run():
    failures = []
    with TempProject() as root:
        test_registry(failures, root)
        test_files(failures, root)
        test_shell(failures, root)
    with TempProject() as root:
        test_patch(failures, root)
        test_crlf(failures, root)
    with TempProject() as root:
        test_blocks(failures, root)
    return failures
