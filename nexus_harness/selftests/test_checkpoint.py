"""Deshacer el turno: el diario guarda los bytes de antes y `undo` deja el arbol como estaba.

Cinco propiedades, cada una con una falsificacion posible:

* lo que el turno **creo** desaparece, y lo que **modifico** vuelve byte a byte (BOM y CRLF incluidos);
* dos escrituras al mismo fichero en un turno vuelven al **original**, no al estado intermedio;
* el gancho esta en el suelo comun (`file_ops`), asi que tambien quedan anotadas las ediciones que
  entran por `edit.patch_replace` -- la herramienta que el modelo usa de verdad;
* **sin diario armado no se anota nada**: lo que mide el diario es el turno, no el proceso;
* una instantanea **ausente** se declara (`ok=False` con la ruta en `skipped`) y no se cuenta como
  media restauracion exitosa.
"""
import hashlib
import os

from .fakes import TempProject
from ..verify import checkpoint
from ..tools.toolbox import edit, file_ops


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def blob_of(journal, relative):
    entry = next((item for item in journal.entries if item["path"] == relative), None)
    return journal.directory / entry["blob"] if entry else None


def test_created_files_disappear(failures, root):
    journal = checkpoint.begin(root, "crear")
    checkpoint.set_active(journal)
    try:
        file_ops.write(root, "nuevo.py", "x = 1\n")
    finally:
        checkpoint.set_active(None)
    check("el turno anota lo que creo", [entry["path"] for entry in journal.entries], ["nuevo.py"],
          failures)
    check("y el fichero existe antes de deshacer", os.path.isfile(str(root / "nuevo.py")), True,
          failures)
    report = journal.undo()
    check("undo borra lo que el turno creo", os.path.exists(str(root / "nuevo.py")), False, failures)
    check("y lo cuenta como borrado", report["deleted"], 1, failures)
    check("sin saltos", report["ok"], True, failures)


def test_modified_files_return_byte_for_byte(failures, root):
    original = "\ufefflinea 1\r\nlinea 2\r\n"
    (root / "vista.py").write_bytes(original.encode("utf-8"))
    journal = checkpoint.begin(root, "editar")
    checkpoint.set_active(journal)
    try:
        file_ops.write(root, "vista.py", "def f():\n    return 1\n")
    finally:
        checkpoint.set_active(None)
    check("el turno cambio el fichero", (root / "vista.py").read_bytes() != original.encode("utf-8"),
          True, failures)
    report = journal.undo()
    check("undo devuelve los bytes exactos", (root / "vista.py").read_bytes(), original.encode("utf-8"),
          failures)
    check("con su BOM y su CRLF", (root / "vista.py").read_bytes().decode("utf-8"), original, failures)
    check("y lo cuenta como restaurado", report["restored"], 1, failures)


def test_the_edit_tool_is_journaled(failures, root):
    before = (root / "calc.py").read_text(encoding="utf-8")
    journal = checkpoint.begin(root, "patch")
    checkpoint.set_active(journal)
    try:
        edit.patch_replace(root, "calc.py", "return a - b", "return a + b")
    finally:
        checkpoint.set_active(None)
    check("el patch quedo aplicado", "return a + b" in (root / "calc.py").read_text(encoding="utf-8"),
          True, failures)
    check("y quedo anotado en el diario", [entry["path"] for entry in journal.entries], ["calc.py"],
          failures)
    journal.undo()
    check("undo lo revierte al texto original", (root / "calc.py").read_text(encoding="utf-8"), before,
          failures)


def test_two_writes_in_one_turn_go_back_to_the_start(failures, root):
    original = (root / "calc.py").read_text(encoding="utf-8")
    journal = checkpoint.begin(root, "dos-veces")
    checkpoint.set_active(journal)
    try:
        edit.patch_replace(root, "calc.py", "return a - b", "return a * b")
        edit.patch_replace(root, "calc.py", "return a * b", "return a / b")
    finally:
        checkpoint.set_active(None)
    check("el turno anoto la ruta una sola vez", len(journal.entries), 1, failures)
    check("y el fichero quedo en el ultimo estado", "return a / b" in
          (root / "calc.py").read_text(encoding="utf-8"), True, failures)
    journal.undo()
    check("undo vuelve al original, no al estado intermedio",
          (root / "calc.py").read_text(encoding="utf-8"), original, failures)


def test_without_a_journal_nothing_is_recorded(failures, root):
    checkpoint.set_active(None)
    turns = len(checkpoint.history(root))
    file_ops.write(root, "suelto.py", "y = 2\n")
    check("un turno sin diario no crea turno", len(checkpoint.history(root)), turns, failures)
    check("y el fichero se escribe igual", os.path.isfile(str(root / "suelto.py")), True, failures)


def test_a_journal_survives_the_process(failures, root):
    journal = checkpoint.begin(root, "reabrir")
    checkpoint.set_active(journal)
    try:
        file_ops.write(root, "persistido.py", "z = 3\n")
    finally:
        checkpoint.set_active(None)
    reopened = checkpoint.load(journal.directory)
    check("el manifiesto guarda la ruta", [entry["path"] for entry in reopened.entries],
          ["persistido.py"], failures)
    check("y el proyecto lo encuentra como el mas nuevo", checkpoint.latest(root).name, journal.name,
          failures)
    report = reopened.undo()
    check("deshacer desde otra instancia borra el fichero",
          os.path.exists(str(root / "persistido.py")), False, failures)
    check("y sale verde", report["ok"], True, failures)


def test_a_missing_snapshot_is_loud(failures, root):
    (root / "presente.py").write_bytes(b"uno\n")
    journal = checkpoint.begin(root, "roto")
    checkpoint.set_active(journal)
    try:
        file_ops.write(root, "presente.py", "dos\n")
    finally:
        checkpoint.set_active(None)
    blob = blob_of(journal, "presente.py")
    check("el diario guardo la instantanea antes de escribir", bool(blob and blob.is_file()), True,
          failures)
    if blob is not None and blob.is_file():
        blob.unlink()
    report = journal.undo()
    check("una instantanea que falta no es un exito", report["ok"], False, failures)
    check("y la ruta se declara", report["skipped"], ["presente.py"], failures)
    check("sin tocar el fichero a medias", (root / "presente.py").read_bytes(), b"dos\n", failures)
    check("el motivo se escribe", report["note"], "instantanea ausente o corrupta", failures)


def test_undo_twice_and_the_history(failures, root):
    journal = checkpoint.begin(root, "idempotente")
    checkpoint.set_active(journal)
    try:
        file_ops.write(root, "una.py", "a = 1\n")
    finally:
        checkpoint.set_active(None)
    check("el primer undo borra", journal.undo()["deleted"], 1, failures)
    second = journal.undo()
    check("el segundo no hace nada", second["deleted"], 0, failures)
    check("y lo dice", second["note"], "ya estaba deshecho", failures)
    names = [item.name for item in checkpoint.history(root)]
    check("el turno sigue en la historia, marcado", checkpoint.latest(root).undone, True, failures)
    check("y el historial esta ordenado de nuevo a viejo", names, sorted(names, reverse=True), failures)
    check("el manifiesto se puede releer", bool(checkpoint.load(journal.directory).undone), True,
          failures)
    check("el resumen del diario cuenta ficheros", checkpoint.load(journal.directory).as_dict()["files"],
          1, failures)


def test_prune_keeps_the_recent_turns(failures, root):
    before = len(checkpoint.history(root))
    for index in range(4):
        journal = checkpoint.begin(root, "turno-%d" % index)
        checkpoint.set_active(journal)
        try:
            file_ops.write(root, "t%d.py" % index, "v = %d\n" % index)
        finally:
            checkpoint.set_active(None)
    check("los cuatro turnos nuevos quedan", len(checkpoint.history(root)), before + 4, failures)
    removed = checkpoint.prune(root, keep=2)
    check("se podan todos menos los dos ultimos", len(removed), before + 2, failures)
    check("y quedan dos", len(checkpoint.history(root)), 2, failures)
    check("los que quedan son los recientes", checkpoint.history(root)[0].label, "turno-3", failures)


def test_the_digest_is_what_comes_back(failures, root):
    """La restauracion no se cree: el hash del fichero restaurado es el del blob guardado."""
    (root / "hash.py").write_bytes(b"print('antes')\n")
    journal = checkpoint.begin(root, "hash")
    checkpoint.set_active(journal)
    try:
        file_ops.write(root, "hash.py", "print('despues')\n")
    finally:
        checkpoint.set_active(None)
    check("el turno anota la ruta antes de deshacer", len(journal.entries), 1, failures)
    if not journal.entries:
        return
    entry = journal.entries[0]
    journal.undo()
    restored = hashlib.sha256((root / "hash.py").read_bytes()).hexdigest()
    check("el sha256 restaurado es el de la instantanea", restored, entry["sha256"], failures)


def run():
    failures = []
    with TempProject() as root:
        test_created_files_disappear(failures, root)
        test_modified_files_return_byte_for_byte(failures, root)
        test_the_edit_tool_is_journaled(failures, root)
        test_two_writes_in_one_turn_go_back_to_the_start(failures, root)
        test_without_a_journal_nothing_is_recorded(failures, root)
        test_a_journal_survives_the_process(failures, root)
        test_a_missing_snapshot_is_loud(failures, root)
        test_undo_twice_and_the_history(failures, root)
        test_prune_keeps_the_recent_turns(failures, root)
        test_the_digest_is_what_comes_back(failures, root)
    return failures
