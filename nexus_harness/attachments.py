"""Attachments: what the operator pasted, made small enough and shaped for the wire.

An image dragged into a chat is three different things at once, and conflating them is how harnesses
eat 20 MB of context: the *model* needs a bounded, correctly-sized image; the *history* needs a chip
that says what was sent; the *disk* needs the bytes, because a conversation resumed tomorrow must still
be able to show the picture.

So one pass produces all three:

1. **Sniff** by magic bytes, never by extension (a `.png` that is really a JPEG breaks the wire).
2. **Normalise** with Pillow when it is installed: convert to RGB, fit inside `MAX_DIMENSION`, re-encode
   as JPEG (or PNG when the image has alpha), and refuse anything that cannot be decoded. Without
   Pillow the original bytes are kept only if they are already inside the dimension cap -- never a
   silent pass-through of a 6000 px screenshot.
3. **Stage** under `.nexus/harness/attachments/<day>/`, returning a chip (`name`, `kind`, `bytes`,
   `preview` data-URI) and an OpenAI `image_url` part for the model.

Text files are read as text (capped), PDFs are extracted page by page when `pymupdf` is present and
refused with a reason when it is not: an empty string pretending to be a document is worse than an
error the operator can act on.
"""
import base64
import io
import json
import re
import time
from pathlib import Path

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TEXT_BYTES = 256 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 25
MAX_DIMENSION = 1568
PREVIEW_DIMENSION = 240
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
TEXT_SUFFIXES = {".txt", ".md", ".json", ".py", ".toml", ".yaml", ".yml", ".csv", ".log", ".cfg",
                 ".ini", ".js", ".ts", ".css", ".html", ".sql", ".sh", ".bat"}
SAFE = re.compile(r"[^A-Za-z0-9._-]+")


# -- sniffing --------------------------------------------------------------------------------
def sniff(data, name=""):
    """`('image'|'pdf'|'text'|'other', mime)`, decided by the bytes when they are enough."""
    head = data[:16]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image", "image/gif"
    if head.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image", "image/webp"
    if head.startswith(b"BM"):
        return "image", "image/bmp"
    if head.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    suffix = Path(str(name)).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image", "image/" + suffix.lstrip(".").replace("jpg", "jpeg")
    if suffix in TEXT_SUFFIXES:
        return "text", "text/plain"
    if b"\x00" in data[:2048]:
        return "other", "application/octet-stream"
    return "text", "text/plain"


def _dims(data):
    """`(width, height)` from the header alone: no decode, no memory surprise."""
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
        if data.startswith(b"\xff\xd8"):
            index = 2
            while index < len(data) - 9:
                if data[index] != 0xFF:
                    index += 1
                    continue
                marker = data[index + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    return (int.from_bytes(data[index + 7:index + 9], "big"),
                            int.from_bytes(data[index + 5:index + 7], "big"))
                index += 2 + int.from_bytes(data[index + 2:index + 4], "big")
    except (IndexError, ValueError):
        return 0, 0
    return 0, 0


# -- normalising -----------------------------------------------------------------------------
def _optional(module):
    """Import an optional dependency, or `None`. Pillow and PyMuPDF are extras, not requirements."""
    import importlib  # noqa: PLC0415 - only needed on this path

    if importlib.util.find_spec(module) is None:
        return None
    try:
        return importlib.import_module(module)
    except ImportError:  # a broken install is as absent as a missing one, and never a crash
        return None


def _pillow():
    return getattr(_optional("PIL"), "Image", None)


def normalise_image(data):
    """`(bytes, mime, width, height, preview_uri)`: bounded, decodable, and small on the wire."""
    image_module = _pillow()
    if image_module is None:
        width, height = _dims(data)
        if max(width, height) > MAX_DIMENSION:
            raise ValueError("image is %dx%d and Pillow is not installed to resize it; send a "
                             "smaller image or install Pillow" % (width, height))
        return data, "image/png", width, height, ""
    try:
        with image_module.open(io.BytesIO(data)) as image:
            image.load()
            width, height = image.size
            working = image.convert("RGBA") if image.mode in ("RGBA", "LA", "P") else image.convert("RGB")
            working.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
            has_alpha = working.mode == "RGBA"
            output = io.BytesIO()
            if has_alpha:
                working.save(output, format="PNG", optimize=True)
                mime = "image/png"
            else:
                working.save(output, format="JPEG", quality=85, optimize=True)
                mime = "image/jpeg"
            preview = io.BytesIO()
            small = working.copy()
            small.thumbnail((PREVIEW_DIMENSION, PREVIEW_DIMENSION))
            small.save(preview, format="JPEG", quality=70)
            encoded = output.getvalue()
            if len(encoded) > MAX_IMAGE_BYTES:
                raise ValueError("image is still %d bytes after resizing (limit %d)"
                                 % (len(encoded), MAX_IMAGE_BYTES))
            return (encoded, mime, working.size[0], working.size[1],
                    "data:image/jpeg;base64," + base64.b64encode(preview.getvalue()).decode())
    except OSError as exc:
        raise ValueError("image could not be decoded: %s" % exc)


def data_uri(mime, data):
    return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode())


def extract_pdf(data):
    """Text out of a PDF, or a `ValueError` that says which dependency is missing."""
    fitz = _optional("fitz")
    if fitz is None:
        raise ValueError("this PDF needs text extraction and PyMuPDF is not installed "
                         "(pip install pymupdf). The file was not attached.")
    try:
        document = fitz.open(stream=data, filetype="pdf")
        try:
            pages = [page.get_text() for page in document][:MAX_PDF_PAGES]
        finally:
            document.close()
    except Exception as exc:  # a corrupt or encrypted file is a refusal, never a traceback
        raise ValueError("the PDF could not be read: %s" % exc)
    text = "\n\n".join(pages).strip()
    return text or "(the PDF has no extractable text layer: it is probably a scan)"


# -- staging ---------------------------------------------------------------------------------
def _safe_name(name, fallback="attachment"):
    clean = SAFE.sub("-", Path(str(name or fallback)).name).strip("-.") or fallback
    return clean[:80]


def stage(root, name, data):
    """Write the bytes under the project's `.nexus` and return the chip the UI shows."""
    day = time.strftime("%Y%m%d")
    directory = Path(root) / ".nexus" / "harness" / "attachments" / day
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / _safe_name(name, "attachment-%d" % len(data))
    if target.exists():
        target = target.with_name("%s-%s%s" % (target.stem[:60], len(data), target.suffix))
    target.write_bytes(data)
    return {"name": target.name, "path": str(target), "bytes": len(data),
            "relative": str(target.relative_to(Path(root))).replace("\\", "/")}


def ingest(root, items):
    """`(attachments, notes)` from `[{name, data(base64)}]` or `[{name, path}]`.

    Each attachment is a dict: `name`, `kind`, `mime`, `bytes`, `preview`, plus `text` for documents
    and `uri` for images. Anything refused lands in `notes` with the reason, so the operator learns
    which file was dropped instead of silently getting a turn without it.
    """
    attachments, notes = [], []
    for item in items or []:
        try:
            name = str(item.get("name") or "attachment")
            if item.get("data"):
                raw = base64.b64decode(str(item["data"]).split(",")[-1], validate=False)
            elif item.get("path"):
                candidate = Path(root) / str(item["path"])
                if not candidate.is_file():
                    raise ValueError("no such file")
                raw = candidate.read_bytes()
            else:
                raise ValueError("no data and no path")
            kind, mime = sniff(raw, name)
            staged = stage(root, name, raw)
            if kind == "image":
                if len(raw) > MAX_IMAGE_BYTES:
                    raise ValueError("image is larger than %d MB" % (MAX_IMAGE_BYTES // 1024 // 1024))
                normalized, mime, width, height, preview = normalise_image(raw)
                if normalized is not raw:
                    Path(staged["path"]).write_bytes(normalized)
                attachments.append(dict(staged, kind="image", mime=mime, width=width, height=height,
                                        preview=preview, uri=data_uri(mime, normalized),
                                        bytes=len(normalized)))
            elif kind == "pdf":
                if len(raw) > MAX_PDF_BYTES:
                    raise ValueError("PDF is larger than %d MB" % (MAX_PDF_BYTES // 1024 // 1024))
                attachments.append(dict(staged, kind="document", mime=mime,
                                        text=extract_pdf(raw)[:MAX_TEXT_BYTES]))
            elif kind == "text":
                if len(raw) > MAX_TEXT_BYTES:
                    raise ValueError("text file is larger than %d KB" % (MAX_TEXT_BYTES // 1024))
                text = raw.decode("utf-8", errors="replace")
                attachments.append(dict(staged, kind="document", mime=mime, text=text))
            else:
                raise ValueError("unsupported file type (%s)" % mime)
        except (ValueError, OSError) as exc:
            notes.append("%s: %s" % (item.get("name") or "attachment", exc))
    return attachments, notes


def as_content(attachments, text):
    """The user turn as multimodal parts, or a plain string when there is nothing to attach."""
    parts = []
    if str(text or "").strip():
        parts.append({"type": "text", "text": str(text)})
    for item in attachments or []:
        if item.get("kind") == "image" and item.get("uri"):
            parts.append({"type": "image_url", "image_url": {"url": item["uri"]}})
        elif item.get("kind") == "document":
            parts.append({"type": "text",
                          "text": "<document name=\"%s\">\n%s\n</document>"
                                  % (item.get("name"), item.get("text", ""))})
    return parts if len(parts) > 1 else (str(text or "") if not attachments else parts)


def chips(attachments):
    """What the UI renders under the message: no bytes, no base64, just what was sent."""
    return [{"name": item.get("name"), "kind": item.get("kind"), "bytes": item.get("bytes"),
             "preview": item.get("preview", ""), "width": item.get("width"),
             "height": item.get("height")} for item in attachments or []]


def summary(attachments):
    if not attachments:
        return ""
    return ", ".join("%s (%s, %d KB)" % (item.get("name"), item.get("kind"),
                                         int(item.get("bytes") or 0) // 1024)
                     for item in attachments)


def to_json(value):
    """Debug helper: attachments never carry raw base64 into a transcript."""
    return json.dumps(chips(value), ensure_ascii=False)
