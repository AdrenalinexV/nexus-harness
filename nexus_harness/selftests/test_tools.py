"""Tools: bounds, refusals, and the two properties everything else depends on.

The two that matter: a path outside the root is refused, and a patch that would break the 400-line law
does not land. Both are asserted here because both are easy to lose in a refactor and impossible to
notice until a model has already written outside the project.
"""
from .fakes import TempProject
from ..tools import default_registry

EXPECTED_TOOLS = 16


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_registry(failures, root):
    registry = default_registry(root)
    check("el arsenal entero", len(registry.names()), EXPECTED_TOOLS, failures)
    check("y browser esta entre ellas", "browser" in registry.names(), True, failures)
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
    search = registry.call("search_files", {"pattern": "return a - b"})
    check("search finds the line", "calc.py:2" in search.text, True, failures)
    listing = registry.call("list_dir", {"path": "."})
    check("list_dir shows the tree", "calc.py" in listing.text, True, failures)


def test_syntax_gate(failures, root):
    """Fail-closed: a .py that does not parse never reaches the disk, at any entry point."""
    registry = default_registry(root)
    bad = registry.call("write_file", {"path": "broken.py", "content": "def f(:\n    pass\n"})
    check("a file that does not parse is refused", bad.ok, False, failures)
    check("and it says so", "would not parse" in bad.text, True, failures)
    check("nothing was written", (root / "broken.py").exists(), False, failures)
    broken_json = registry.call("write_file", {"path": "data.json", "content": "{'a': 1}"})
    check("JSON with single quotes is refused", broken_json.ok, False, failures)
    nan = registry.call("write_file", {"path": "nan.json", "content": '{"a": NaN}'})
    check("NaN is not JSON", nan.ok, False, failures)
    good = registry.call("write_file", {"path": "ok.json", "content": '{"a": 1}'})
    check("valid JSON lands", good.ok, True, failures)


def test_patch(failures, root):
    registry = default_registry(root)
    ok = registry.call("patch_replace", {"path": "calc.py", "old_string": "return a - b",
                                         "new_string": "return a + b"})
    check("exact patch applies", ok.ok, True, failures)
    check("and the file changed", "a + b" in (root / "calc.py").read_text(encoding="utf-8"),
          True, failures)
    again = registry.call("patch_replace", {"path": "calc.py", "old_string": "return result",
                                            "new_string": "return a * b"})
    check("a search that no longer exists is refused", again.ok, False, failures)
    check("and the refusal suggests the closest block", "closest existing block" in again.text,
          True, failures)
    (root / "dup.py").write_text("value = 1\nvalue = 1\n", encoding="utf-8")
    ambiguous = registry.call("patch_replace", {"path": "dup.py", "old_string": "value = 1",
                                                "new_string": "value = 2"})
    check("two candidates is an error, not a guess", ambiguous.ok, False, failures)
    check("and it counts them", "found 2 matches" in ambiguous.text, True, failures)
    (root / "long.py").write_text("\n".join("x%d = %d" % (i, i) for i in range(398)) + "\n",
                                  encoding="utf-8")
    breaker = registry.call("patch_replace", {"path": "long.py", "old_string": "x0 = 0",
                                              "new_string": "x0 = 0\ny0 = 0\ny1 = 1\ny2 = 2"})
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
    check("re-applying is idempotent, not destructive", atomic.ok, True, failures)
    check("and nothing was rewritten", (root / "calc.py").read_text(encoding="utf-8"), before,
          failures)


def test_crlf(failures, root):
    """A Windows repository keeps its CRLF, and the normalised rung must not double the `\\r`."""
    registry = default_registry(root)
    (root / "crlf.py").write_bytes(b"def f():\r\n    return 1\r\n")
    registry.call("patch_replace", {"path": "crlf.py", "old_string": "    return 1",
                                    "new_string": "    return 2"})
    raw = (root / "crlf.py").read_bytes()
    check("an exact patch keeps CRLF", raw, b"def f():\r\n    return 2\r\n", failures)
    (root / "bom.py").write_bytes(b"\xef\xbb\xbfdef g():\r\n    return 1\r\n")
    registry.call("patch_replace", {"path": "bom.py", "old_string": "    return 1",
                                    "new_string": "    return 3"})
    raw = (root / "bom.py").read_bytes()
    check("a BOM survives the edit", raw.startswith(b"\xef\xbb\xbf"), True, failures)
    check("with no doubled carriage return", b"\r\r\n" in raw, False, failures)


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
        test_syntax_gate(failures, root)
        test_shell(failures, root)
    with TempProject() as root:
        test_patch(failures, root)
        test_crlf(failures, root)
    with TempProject() as root:
        test_blocks(failures, root)
    return failures
