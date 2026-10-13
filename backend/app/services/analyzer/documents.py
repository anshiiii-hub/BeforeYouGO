"""Safe text extraction from uploads (text, PDF, images). Uploads are untrusted."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from app.core.errors import Unprocessable

ALLOWED = {
    "text/plain": (".txt", ".md"),
    "application/pdf": (".pdf",),
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/webp": (".webp",),
}
MAX_PDF_PAGES = 15


@dataclass
class ExtractedDocument:
    text: str
    method: str  # plain_text / pdf_text / ocr
    sha256: str
    mime: str
    notes: list[str]


def sniff_mime(data: bytes, filename: str) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    name = filename.lower()
    if name.endswith((".txt", ".md")):
        try:
            data[:4096].decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass
    raise Unprocessable("Unsupported file. Upload a PDF, PNG, JPEG, WebP image, or a plain-text file.", code="unsupported_file_type")


def extract_text(data: bytes, filename: str, max_bytes: int) -> ExtractedDocument:
    if len(data) > max_bytes:
        raise Unprocessable(f"File is larger than the {max_bytes // (1024 * 1024)} MB limit.", code="file_too_large")
    if not data:
        raise Unprocessable("The uploaded file is empty.", code="empty_file")
    mime = sniff_mime(data, filename)
    sha = hashlib.sha256(data).hexdigest()
    notes: list[str] = []
    if mime == "text/plain":
        return ExtractedDocument(data.decode("utf-8", errors="replace"), "plain_text", sha, mime, notes)
    if mime == "application/pdf":
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError

        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise Unprocessable("Encrypted PDFs are not supported.", code="encrypted_pdf")
            pages = reader.pages[:MAX_PDF_PAGES]
            text = "\n".join((p.extract_text() or "") for p in pages)
            if len(reader.pages) > MAX_PDF_PAGES:
                notes.append(f"Only the first {MAX_PDF_PAGES} pages were read.")
        except (PyPdfError, ValueError, KeyError) as exc:
            raise Unprocessable("The PDF could not be parsed.", code="invalid_pdf") from exc
        if len(text.strip()) < 20:
            raise Unprocessable("The PDF has no extractable text layer (it may be a scan). Upload a page image instead.", code="no_text_layer")
        return ExtractedDocument(text, "pdf_text", sha, mime, notes)
    # image: verify it decodes, then OCR
    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > 40_000_000:
            raise Unprocessable("Image dimensions are too large.", code="image_too_large")
    except (UnidentifiedImageError, OSError) as exc:
        raise Unprocessable("The image could not be read.", code="invalid_image") from exc
    try:
        import pytesseract

        text = pytesseract.image_to_string(img.convert("L"))
    except Exception as exc:  # tesseract missing or failing
        raise Unprocessable("Text recognition (OCR) is unavailable on this server; paste the poster text instead.", code="ocr_unavailable") from exc
    if len(text.strip()) < 10:
        raise Unprocessable("No readable text was found in the image.", code="no_text_found")
    notes.append("Text was read with OCR and may contain recognition errors; verify excerpts against the poster.")
    return ExtractedDocument(text, "ocr", sha, mime, notes)
