"""
Document extraction + chunking service — powered by Docling.

Single entry point:
    extract_and_chunk(file_bytes, filename)
        → (lc_docs, full_text, page_count)

Handles all formats (PDF, DOCX, PPTX, images) with:
  - Docling layout parsing (tables, headings, sections)
  - Surya OCR for scanned / image-based documents
  - HybridChunker for document-aware chunking
"""

import os
import tempfile
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docling_surya import SuryaOcrOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.chunking import HybridChunker
from langchain_docling import DoclingLoader
from langchain_docling.loader import ExportType

from core.config import get_settings

settings = get_settings()

# ── Pipeline options (configured once) ────────────────────────────────

# Primary OCR pipeline (Surya)
_pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    ocr_model="suryaocr",
    allow_external_plugins=True,
    ocr_options=SuryaOcrOptions(lang=["en", "ar"]),
    num_threads=8,
)

_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_pipeline_options),
    InputFormat.IMAGE: PdfFormatOption(pipeline_options=_pipeline_options),
}

# Fallback OCR pipeline (Tesseract CLI) for Surya/runtime incompatibilities.
_fallback_pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    ocr_model="tesseractcli",
    allow_external_plugins=False,
    # Tesseract uses ISO-639-2 language codes.
    ocr_options=TesseractCliOcrOptions(lang=["eng", "ara", "hin"]),
    num_threads=8,
)

_fallback_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_fallback_pipeline_options),
    InputFormat.IMAGE: PdfFormatOption(pipeline_options=_fallback_pipeline_options),
}

# Fast path for digital PDFs: skip OCR entirely.
_no_ocr_pipeline_options = PdfPipelineOptions(
    do_ocr=False,
    allow_external_plugins=False,
    num_threads=8,
)

_no_ocr_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_no_ocr_pipeline_options),
}


@dataclass
class _ChunkDoc:
    """Minimal document shape used by downstream embedding/storage code."""
    page_content: str
    metadata: dict


def _get_page_count(result: Any) -> int:
    """Extract page count from a docling ConversionResult."""
    if hasattr(result.document, "pages") and result.document.pages:
        return len(result.document.pages)
    if hasattr(result, "pages"):
        return len(result.pages)
    return _estimate_page_count(result.document)


def _should_enable_ocr(ext: str, full_text: str, page_count: int) -> bool:
    """
    Decide whether OCR is needed after a no-OCR parse.
    Uses simple text-density heuristics for PDFs.
    """
    if ext != ".pdf":
        return False

    text_len = len((full_text or "").strip())
    pages = max(page_count or 1, 1)
    chars_per_page = text_len / pages

    # Scanned PDFs often have very low extracted text density without OCR.
    return text_len < 1200 or chars_per_page < 180


def _to_dict_safe(value: Any) -> dict | None:
    """Best-effort conversion of pydantic/dataclass-like objects to dict."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            return None
    if hasattr(value, "dict"):
        try:
            return value.dict()
        except Exception:
            return None
    return None


def _serialize_chunk(chunker: HybridChunker, chunk: Any) -> str:
    """Serialize a Docling chunk to text with API compatibility fallbacks."""
    try:
        return chunker.serialize(chunk=chunk)
    except TypeError:
        pass

    try:
        return chunker.serialize(chunk)
    except Exception:
        pass

    for attr in ("text", "content", "page_content"):
        value = getattr(chunk, attr, None)
        if isinstance(value, str) and value.strip():
            return value

    return str(chunk)


def _build_lc_docs_from_document(document: Any) -> list[_ChunkDoc]:
    """
    Build LangChain-like docs directly from an already-converted Docling document.
    This avoids a second full conversion pass in DoclingLoader.
    """
    chunker = HybridChunker(
        tokenizer=settings.EMBEDDING_MODEL,
        max_tokens=512,  # multilingual-e5-large-instruct max sequence length
    )

    try:
        chunks_iter = chunker.chunk(dl_doc=document)
    except TypeError:
        chunks_iter = chunker.chunk(document)

    out: list[_ChunkDoc] = []
    for chunk in chunks_iter:
        text = _serialize_chunk(chunker, chunk).strip()
        if not text:
            continue

        headings: list[str] = []
        doc_items: list[dict] = []

        meta = getattr(chunk, "meta", None)
        if meta is not None:
            raw_headings = getattr(meta, "headings", None) or []
            headings = [str(h) for h in raw_headings if h]

            raw_doc_items = getattr(meta, "doc_items", None) or []
            for item in raw_doc_items:
                item_dict = _to_dict_safe(item)
                if item_dict:
                    doc_items.append(item_dict)

        out.append(
            _ChunkDoc(
                page_content=text,
                metadata={"dl_meta": {"headings": headings, "doc_items": doc_items}},
            )
        )

    return out


def _convert_with_ocr(tmp_path: str):
    """Convert document with OCR path (Surya preferred, Tesseract fallback)."""
    patched_count = _patch_surya_cached_config_if_needed()
    if patched_count:
        print(f"🛠️  Patched Surya config in {patched_count} cached model file(s)")

    converter = DocumentConverter(format_options=_format_options)
    try:
        result = converter.convert(tmp_path)
        return result, converter
    except AttributeError as exc:
        # Known Surya/transformers incompatibility in some environments:
        # "SuryaDecoderConfig has no attribute pad_token_id".
        if "pad_token_id" not in str(exc):
            raise

        print("⚠️  Surya OCR init failed with pad_token_id error; attempting self-heal")
        patched_after_failure = _patch_surya_cached_config_if_needed()

        if patched_after_failure:
            print(f"🛠️  Patched Surya config in {patched_after_failure} cached model file(s); retrying Surya")
            converter = DocumentConverter(format_options=_format_options)
            try:
                result = converter.convert(tmp_path)
                return result, converter
            except AttributeError as exc_retry:
                if "pad_token_id" not in str(exc_retry):
                    raise

                print("⚠️  Surya retry still failed; falling back to Tesseract OCR")
                converter = DocumentConverter(format_options=_fallback_format_options)
                result = converter.convert(tmp_path)
                return result, converter

        print("⚠️  No patchable Surya config found; falling back to Tesseract OCR")
        converter = DocumentConverter(format_options=_fallback_format_options)
        result = converter.convert(tmp_path)
        return result, converter


def _patch_surya_cached_config_if_needed() -> int:
    """
    Surya model config compatibility fix.

    In some docling-surya/surya-ocr combinations, the decoder config loaded from
    cache misses `decoder.pad_token_id`, which causes:
      AttributeError: 'SuryaDecoderConfig' object has no attribute 'pad_token_id'

    If top-level `pad_token_id` exists, copy it into `decoder.pad_token_id`.
    Returns number of files patched.
    """
    base = Path.home() / ".cache" / "docling" / "models" / "SuryaOcr" / "text_recognition"
    if not base.exists():
        return 0

    patched = 0
    for cfg_path in sorted(base.glob("*/config.json")):
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            decoder = cfg.get("decoder")
            top_level_pad = cfg.get("pad_token_id")
            if isinstance(decoder, dict) and "pad_token_id" not in decoder and top_level_pad is not None:
                decoder["pad_token_id"] = top_level_pad
                cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                patched += 1
        except Exception:
            # Non-fatal: if patching fails, fallback path still handles extraction.
            pass

    return patched


def extract_and_chunk(
    file_bytes: bytes,
    filename: str,
) -> tuple[list, str, int]:
    """
    Extract text from a document and chunk it using Docling's HybridChunker.

    Args:
        file_bytes: Raw file content
        filename:   Original filename (used for extension detection)

    Returns:
        (lc_docs, full_text, page_count)
        - lc_docs:    list of LangChain Document objects (chunked)
        - full_text:  full markdown text of the document
        - page_count: number of pages detected
    """
    ext = Path(filename).suffix.lower()
    if not ext:
        ext = ".pdf"

    # Write bytes to a temp file (Docling needs a file path)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    full_text = ""
    page_count = 0
    converter = None

    try:
        print(f"📄 Docling: parsing {filename} ...")

        # ── Step 1: Convert document (fast path first for PDFs) ───────────
        if ext == ".pdf":
            # ── PRE-EMPTIVE OCR PROBE ───────────
            import fitz
            looks_like_scan = False
            try:
                doc_fitz = fitz.open(tmp_path)
                probe_pages = min(3, len(doc_fitz))
                extracted_len = 0
                for i in range(probe_pages):
                    extracted_len += len(doc_fitz[i].get_text("text").strip())
                doc_fitz.close()
                if extracted_len < 100:
                    looks_like_scan = True
            except Exception as e:
                print(f"⚠️ PyMuPDF probe failed: {e}")

            if looks_like_scan:
                print("🧾 Pre-emptive OCR triggered: Document appears to be a scanned image.")
                result, converter = _convert_with_ocr(tmp_path)
                full_text = result.document.export_to_markdown()
                page_count = _get_page_count(result)
            else:
                print("⚡ Fast path: trying PDF parse without OCR")
                converter = DocumentConverter(format_options=_no_ocr_format_options)
                result = converter.convert(tmp_path)
                full_text = result.document.export_to_markdown()
                page_count = _get_page_count(result)

                if _should_enable_ocr(ext=ext, full_text=full_text, page_count=page_count):
                    print("🧾 Low native text density detected; enabling OCR path")
                    result, converter = _convert_with_ocr(tmp_path)
                    full_text = result.document.export_to_markdown()
                    page_count = _get_page_count(result)
                else:
                    print("✅ Native PDF text sufficient; skipped OCR")
        else:
            result, converter = _convert_with_ocr(tmp_path)
            full_text = result.document.export_to_markdown()
            page_count = _get_page_count(result)

        print(f"✅ Docling: parsed {page_count} pages, {len(full_text)} chars")

        # ── Step 2: Chunk directly from conversion result (single pass) ────
        lc_docs = _build_lc_docs_from_document(result.document)
        if not lc_docs:
            raise RuntimeError("No chunks produced from direct Docling chunking")
        print(f"✂️  Docling: produced {len(lc_docs)} chunks")
        return lc_docs, full_text, page_count
    except Exception as chunk_err:
        # Compatibility fallback: keep old path as a safety net.
        print(f"⚠️  Direct chunking path failed ({chunk_err}); falling back to DoclingLoader")
        if converter is None:
            converter = DocumentConverter(format_options=_format_options)
        loader = DoclingLoader(
            file_path=tmp_path,
            export_type=ExportType.DOC_CHUNKS,
            converter=converter,
            chunker=HybridChunker(
                tokenizer=settings.EMBEDDING_MODEL,
                max_tokens=512,
            ),
        )
        lc_docs = loader.load()
        if not full_text:
            full_text = "\n\n".join((doc.page_content or "") for doc in lc_docs).strip()
        if page_count <= 0:
            page_count = 1
        print(f"✂️  Docling: produced {len(lc_docs)} chunks")
        return lc_docs, full_text, page_count

    finally:
        os.unlink(tmp_path)


def _estimate_page_count(document) -> int:
    """Estimate page count from document item provenance data."""
    max_page = 0
    try:
        for item in getattr(document, "body", []):
            for prov in getattr(item, "prov", []):
                if hasattr(prov, "page_no"):
                    max_page = max(max_page, prov.page_no)
    except Exception:
        pass
    return max_page if max_page > 0 else 1
