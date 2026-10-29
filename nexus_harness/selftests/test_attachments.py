"""Attachments: bounded, sniffed by bytes, staged on disk, shaped for the wire.

What is measured here is what would otherwise bite in production: a 2000 px screenshot reaching the
model untouched, a `.png` that is really text, a document that silently becomes an empty string, and a
preview that leaks the full image into the transcript.
"""
import base64
import importlib
import importlib.util
import io

from .fakes import TempProject
from ..tools import attachments

# The module, not the class: `PIL.Image.new` is a module-level function.
Image = importlib.import_module("PIL.Image") if importlib.util.find_spec("PIL") else None


def check(name, got, expect, failures=None):
    if got != expect:
        message = "%s: %r, esperaba %r" % (name, got, expect)
        if failures is None:
            raise AssertionError(message)
        failures.append(message)


def png_bytes_raw(width, height):
    """A real PNG header by hand, so the no-Pillow path is tested without Pillow."""
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes([30, 120, 200] * width) for _ in range(height))
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def png_bytes(width, height, colour=(30, 120, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_is_resized_and_staged(failures, root):
    if Image is None:
        # No Pillow: the documented contract is a refusal, never a silent pass-through of 2400 px.
        raw = png_bytes_raw(2400, 1800)
        blocks, notes = attachments.ingest(root, [{"name": "grande.png",
                                                   "data": base64.b64encode(raw).decode()}])
        check("without Pillow a large image is refused", blocks, [], failures)
        check("and the note names Pillow", "Pillow" in notes[0], True, failures)
        return
    raw = png_bytes(2400, 1800)
    payload = base64.b64encode(raw).decode()
    blocks, notes = attachments.ingest(root, [{"name": "captura.png", "data": payload}])
    check("the image is accepted", notes, [], failures)
    check("one attachment came back", len(blocks), 1, failures)
    item = blocks[0]
    check("it is an image", item["kind"], "image")
    check("it was re-encoded as JPEG", item["mime"], "image/jpeg")
    check("it fits the dimension cap", max(item["width"], item["height"]) <= attachments.MAX_DIMENSION,
          True, failures)
    check("it shrank", item["bytes"] < len(raw), True, failures)
    check("it carries an image_url data URI", item["uri"].startswith("data:image/"), True, failures)
    check("the file is on disk", __import__("os").path.isfile(item["path"]), True, failures)
    check("the preview is smaller than the payload", len(item["preview"]) < len(item["uri"]), True,
          failures)


def test_text_and_pdf_rules(failures, root):
    payload = base64.b64encode("# notas\n- una regla\n".encode()).decode()
    blocks, notes = attachments.ingest(root, [{"name": "notas.md", "data": payload}])
    check("markdown is a document", blocks[0]["kind"], "document", failures)
    check("and its text travels", "una regla" in blocks[0]["text"], True, failures)
    huge = base64.b64encode(b"x" * (attachments.MAX_TEXT_BYTES + 10)).decode()
    blocks, notes = attachments.ingest(root, [{"name": "huge.txt", "data": huge}])
    check("an oversized text file is refused", blocks, [], failures)
    check("with a reason", "larger" in notes[0], True, failures)
    blocks, notes = attachments.ingest(root, [{"name": "scan.pdf",
                                               "data": base64.b64encode(b"%PDF-1.4 fake").decode()}])
    check("a fake PDF is refused, never faked into a document", blocks, [], failures)
    check("and the note says why", bool(notes and notes[0]), True, failures)
    blocks, notes = attachments.ingest(root, [{"name": "x.exe",
                                               "data": base64.b64encode(b"MZ\x00\x00").decode()}])
    check("a binary is refused", blocks, [], failures)


def test_content_shape(failures, root):
    if Image is None:
        # Sin Pillow no hay re-codificacion: el contrato es "cabe, luego viaja tal cual; no cabe, se
        # niega con motivo", y la preview queda VACIA en vez de fingir un recorte que nadie hizo.
        payload = base64.b64encode(png_bytes_raw(40, 40)).decode()
        blocks, _notes = attachments.ingest(root, [{"name": "small.png", "data": payload}])
        check("without Pillow a small image travels untouched", len(blocks), 1, failures)
        check("kept as its own mime, not re-encoded", blocks[0]["mime"], "image/png", failures)
        check("and the preview is honestly empty", blocks[0]["preview"], "", failures)
        content = attachments.as_content(blocks, "¿qué ves aquí?")
        check("the turn is still multimodal", [part["type"] for part in content],
              ["text", "image_url"], failures)
        check("the chip carries no base64", "uri" in attachments.chips(blocks)[0], False, failures)
        check("a plain turn stays a string", attachments.as_content([], "hola"), "hola", failures)
        return
    payload = base64.b64encode(png_bytes(40, 40)).decode()
    blocks, _notes = attachments.ingest(root, [{"name": "small.png", "data": payload}])
    content = attachments.as_content(blocks, "¿qué ves aquí?")
    check("the turn is multimodal", isinstance(content, list), True, failures)
    check("the text comes first", content[0]["type"], "text", failures)
    check("then the image", content[1]["type"], "image_url", failures)
    check("a plain turn stays a string", attachments.as_content([], "hola"), "hola", failures)
    chips = attachments.chips(blocks)
    check("the chip has no base64", "uri" in chips[0], False, failures)
    check("but it has the preview", chips[0]["preview"].startswith("data:image/"), True, failures)


def run():
    failures = []
    with TempProject() as root:
        test_image_is_resized_and_staged(failures, root)
        test_text_and_pdf_rules(failures, root)
        test_content_shape(failures, root)
    return failures
