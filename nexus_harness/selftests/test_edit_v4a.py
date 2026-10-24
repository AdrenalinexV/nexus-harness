"""Edits: the drift a model actually produces, and the refusals that keep it honest.

Four properties, each one a bug that has bitten a real harness:

* a block re-typed with two spaces where the file has four still lands (indentation rung);
* the same edit sent twice does not rewrite the file (idempotent, `already_applied`);
* an edit that would leave a `.py` unparseable is refused and the file is untouched (fail-closed);
* a V4A patch touching several files applies whole, or rolls every file back.
"""
from .fakes import TempProject
from ..toolbox import edit, file_ops, patch_v4a

CALC = """def add(a, b):
    result = a - b
    return result
"""


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_indentation_drift(failures, root):
    """The model sends the block with the wrong indentation; the file is the truth, not the model."""
    registry_root = root
    shifted = "def add(a, b):\n  result = a - b\n  return result"
    text, meta = edit.patch_replace(registry_root, "calc.py", shifted,
                                    "def add(a, b):\n    result = a + b\n    return result")
    check("the shifted block was located", meta.get("match") in ("indentation_flexible",
                                                                 "line_trimmed"), True, failures)
    check("and the edit landed", "a + b" in file_ops.read_text(root / "calc.py"), True, failures)
    check("and the file still parses", file_ops.syntax_check(root / "calc.py",
                                                             file_ops.read_text(root / "calc.py")),
          "", failures)


def test_already_applied(failures, root):
    (root / "memo.py").write_text("VALUE = 1\n", encoding="utf-8")
    first, meta = edit.patch_replace(root, "memo.py", "VALUE = 1", "VALUE = 2")
    check("the first edit applies", meta.get("match"), "exact", failures)
    before = file_ops.read_text(root / "memo.py")
    second, meta2 = edit.patch_replace(root, "memo.py", "VALUE = 1", "VALUE = 2")
    check("the second is idempotent", meta2.get("match"), "already_applied", failures)
    check("and says so", "already contains" in second, True, failures)
    check("without touching the bytes", file_ops.read_text(root / "memo.py"), before, failures)


def test_syntax_gate_fail_closed(failures, root):
    (root / "keep.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    try:
        edit.patch_replace(root, "keep.py", "    return 1", "    return (")
        failures.append("a patch that breaks the parser was accepted")
    except ValueError as exc:
        check("the refusal names the parser", "would not parse" in str(exc), True, failures)
    check("and the file keeps its old bytes",
          file_ops.read_text(root / "keep.py").replace("\r\n", "\n"), "def ok():\n    return 1\n",
          failures)
    (root / "cfg.json").write_text('{"a": 1}\n', encoding="utf-8")
    try:
        edit.patch_replace(root, "cfg.json", '"a": 1', '"a": ,')
        failures.append("invalid JSON was accepted")
    except ValueError:
        check("invalid JSON is refused too", True, True, failures)


def test_v4a_multi_file(failures, root):
    (root / "one.py").write_text("A = 1\n", encoding="utf-8")
    (root / "gone.py").write_text("B = 2\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: one.py
@@ A = 1 @@
-A = 1
+A = 10
*** Add File: two.py
+C = 3
*** Delete File: gone.py
*** End Patch"""
    result = patch_v4a.apply(root, patch)
    check("the patch is accepted", result.ok, True, failures)
    check("the update landed", "A = 10" in file_ops.read_text(root / "one.py"), True, failures)
    check("the file was created", (root / "two.py").is_file(), True, failures)
    check("the file was deleted", (root / "gone.py").exists(), False, failures)
    check("and it reports three files",
          sorted(result.as_meta()["files"]), ["gone.py", "one.py", "two.py"], failures)


def test_v4a_rollback(failures, root):
    """A patch whose second operation is impossible must leave the first one unapplied."""
    (root / "only.py").write_text("X = 1\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: only.py
-X = 1
+X = 2
*** Update File: missing.py
-Y = 1
+Y = 2
*** End Patch"""
    result = patch_v4a.apply(root, patch)
    check("the patch is refused", result.ok, False, failures)
    check("the reason names the missing file", "missing.py" in result.text, True, failures)
    check("and the valid operation was not written",
          file_ops.read_text(root / "only.py").replace("\r\n", "\n"), "X = 1\n", failures)


def test_v4a_hint_and_move(failures, root):
    (root / "app.py").write_text("import os\n\nprint(os.getcwd())\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: app.py
@@ import os @@
+import sys
*** Move File: app.py -> moved.py
*** End Patch"""
    result = patch_v4a.apply(root, patch)
    check("hinted insert plus move apply", result.ok, True, failures)
    check("the addition landed", "import sys" in file_ops.read_text(root / "moved.py"), True,
          failures)
    check("and the source is gone", (root / "app.py").exists(), False, failures)


def run():
    failures = []
    with TempProject({"calc.py": CALC}) as root:
        test_indentation_drift(failures, root)
    with TempProject({"calc.py": CALC}) as root:
        test_already_applied(failures, root)
        test_syntax_gate_fail_closed(failures, root)
    with TempProject() as root:
        test_v4a_multi_file(failures, root)
        test_v4a_rollback(failures, root)
        test_v4a_hint_and_move(failures, root)
    return failures
