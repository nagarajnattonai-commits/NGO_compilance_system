"""Bounded extraction of normalized text; original immutable bytes are never changed."""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from typing import Protocol
from xml.etree import ElementTree

from .ai_provider import AiProviderError

MAX_EXTRACTED_CHARACTERS = 2_000_000
MAX_OCR_BYTES = 25 * 1024 * 1024
MIN_READABLE_CHARACTERS = 80


class OcrProvider(Protocol):
    def extract(self, content: bytes, mime_type: str) -> str: ...


_ocr: OcrProvider | None = None


def configure_ocr(provider: OcrProvider | None) -> None:
    global _ocr
    _ocr = provider


def ocr_configured() -> bool:
    return _ocr is not None


def _ocr_text(content: bytes, mime_type: str) -> tuple[str, str]:
    if len(content) > MAX_OCR_BYTES:
        raise AiProviderError("OCR_PAYLOAD_TOO_LARGE")
    if not _ocr:
        raise AiProviderError("OCR_UNAVAILABLE")
    try:
        value = normalize_text(_ocr.extract(content, mime_type))
    except AiProviderError:
        raise
    except Exception:
        raise AiProviderError("OCR_FAILED") from None
    if not value:
        raise AiProviderError("OCR_FAILED")
    return value, "ocr-v1"


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\x00", "")
    value = "".join(character for character in value if character in "\n\t" or unicodedata.category(character)[0] != "C")
    paragraphs = [re.sub(r"[ \t]+", " ", part).strip() for part in re.split(r"\n+", value)]
    return "\n\n".join(part for part in paragraphs if part)[:MAX_EXTRACTED_CHARACTERS]


def _office_xml(content: bytes, mime_type: str) -> tuple[str, str]:
    path = "word/document.xml" if mime_type.endswith("wordprocessingml.document") else "xl/sharedStrings.xml"
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [path] if path in archive.namelist() else []
            if mime_type.endswith("sheet"):
                names += sorted(name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
            text = []
            for name in names:
                root = ElementTree.fromstring(archive.read(name))
                text.extend(node.text or "" for node in root.iter() if node.tag.rsplit("}", 1)[-1] in {"t", "v"})
        return "\n".join(text), "office-xml-v1"
    except Exception:
        raise AiProviderError("EXTRACTION_FAILED") from None


def extract_text(content: bytes, mime_type: str) -> tuple[str, str]:
    if mime_type == "application/pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content), strict=True)
            if len(reader.pages) > 500:
                raise ValueError("page limit")
            return normalize_text("\n".join(page.extract_text() or "" for page in reader.pages)), "pypdf-v1"
        except AiProviderError:
            raise
        except Exception:
            raise AiProviderError("EXTRACTION_FAILED") from None
    if mime_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        value, extractor = _office_xml(content, mime_type)
        return normalize_text(value), extractor
    if mime_type.startswith("image/"):
        return _ocr_text(content, mime_type)
    raise AiProviderError("EXTRACTION_UNSUPPORTED")


def extract_text_with_ocr_fallback(content: bytes, mime_type: str) -> tuple[str, str, bool]:
    """Reuse normal extraction and invoke OCR only for images or text-poor PDFs."""
    text, extractor = extract_text(content, mime_type)
    if mime_type == "application/pdf" and len(re.sub(r"\s+", "", text)) < MIN_READABLE_CHARACTERS:
        text, extractor = _ocr_text(content, mime_type)
        return text, extractor, True
    return text, extractor, extractor.startswith("ocr-")


def deterministic_chunks(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    if size < 200 or overlap < 0 or overlap >= size:
        raise ValueError("Invalid chunk configuration")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + size // 2, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks
