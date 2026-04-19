"""
Document extraction + chunking service — powered by Docling.

Single entry point:
    extract_and_chunk(file_bytes, filename)
        → (lc_docs, full_text, page_count)

Handles all formats (PDF, DOCX, PPTX, images) with:
  - Three-tier pipeline: Lean → Enriched (FAST tables) → OCR
  - RapidOCR for scanned / image-based documents
  - HybridChunker for document-aware chunking

Pipeline tiers:
  Tier 1 "Lean"     — No OCR, no table structure.  Fastest.
  Tier 2 "Enriched" — No OCR, FAST table structure. For table-heavy docs.
  Tier 3 "OCR"      — RapidOCR (fallback: Tesseract). For scanned docs.
"""

import os
import time
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
    TesseractCliOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.chunking import HybridChunker
from langchain_docling import DoclingLoader
from langchain_docling.loader import ExportType
from transformers import AutoTokenizer

from core.config import get_settings

settings = get_settings()

# ── Pipeline options (configured once) ────────────────────────────────

# Tier 1 — Lean: no OCR, no table structure.  Maximum speed.
_lean_pipeline_options = PdfPipelineOptions(
    do_ocr=False,
    do_table_structure=False,
    generate_page_images=False,
    generate_picture_images=False,
    allow_external_plugins=False,
)

_lean_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_lean_pipeline_options),
}

# Tier 2 — Enriched: no OCR, but FAST table structure for table-heavy docs.
_enriched_pipeline_options = PdfPipelineOptions(
    do_ocr=False,
    do_table_structure=True,
    generate_page_images=False,
    generate_picture_images=False,
    allow_external_plugins=False,
)
_enriched_pipeline_options.table_structure_options = TableStructureOptions(
    mode=TableFormerMode.FAST,
)

_enriched_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_enriched_pipeline_options),
}

# Tier 3a — OCR primary (RapidOCR - Fast & Light)
_ocr_pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    do_table_structure=True,
    allow_external_plugins=False,
    generate_page_images=False,
    generate_picture_images=False,
    ocr_options=RapidOcrOptions(),
)
_ocr_pipeline_options.table_structure_options = TableStructureOptions(
    mode=TableFormerMode.FAST,
)

_ocr_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_ocr_pipeline_options),
    InputFormat.IMAGE: PdfFormatOption(pipeline_options=_ocr_pipeline_options),
}

# Tier 3b — OCR fallback (Tesseract CLI)
_fallback_pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    ocr_model="tesseractcli",
    allow_external_plugins=False,
    generate_page_images=False,
    generate_picture_images=False,
    # Tesseract uses ISO-639-2 language codes.
    ocr_options=TesseractCliOcrOptions(lang=["eng", "ara", "hin"]),
)

_fallback_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_fallback_pipeline_options),
    InputFormat.IMAGE: PdfFormatOption(pipeline_options=_fallback_pipeline_options),
}


def get_ocr_format_options():
    """Factory to get OCR options based on settings (RapidOCR vs SuryaOCR)."""
    if settings.OCR_ENGINE.lower() == "suryaocr":
        try:
            from docling_surya import SuryaOcrOptions
            surya_options = PdfPipelineOptions(
                do_ocr=True,
                do_table_structure=True,
                ocr_model="suryaocr",
                allow_external_plugins=True,
                generate_page_images=False,
                generate_picture_images=False,
                ocr_options=SuryaOcrOptions(lang=["en"]), # Default to english, internal detection handles others
            )
            surya_options.table_structure_options = TableStructureOptions(
                mode=TableFormerMode.FAST,
            )
            return {
                InputFormat.PDF: PdfFormatOption(pipeline_options=surya_options),
                InputFormat.IMAGE: PdfFormatOption(pipeline_options=surya_options),
            }
        except ImportError:
            print("⚠️  docling-surya not installed; falling back to RapidOCR")
    
    return _ocr_format_options


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


def is_scanned_pdf_fast(tmp_path: str) -> bool:
    """
    Near-instant check for scanned PDFs using PyMuPDF (fitz).
    Checks text density in the digital layer to decide if OCR is primary target.
    """
    try:
        doc = fitz.open(tmp_path)
        return _check_doc_is_scanned(doc)
    except Exception as e:
        print(f"⚠️  Fast scan detection failed: {e}")
        return False


def is_scanned_pdf_fast_bytes(file_bytes: bytes) -> bool:
    """Bytes-based version of the fast scan detection."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        return _check_doc_is_scanned(doc)
    except Exception as e:
        print(f"⚠️  Fast scan detection (bytes) failed: {e}")
        return False


def _check_doc_is_scanned(doc: fitz.Document) -> bool:
    """Internal helper to check text density across first few pages."""
    total_chars = 0
    page_count = len(doc)
    
    # Check first few pages for efficiency (scanned docs are usually consistent)
    check_pages = min(5, page_count)
    for i in range(check_pages):
        total_chars += len(doc[i].get_text().strip())
    
    doc.close()
    
    # Heuristic: less than 100 characters per page average in digital layer suggests scanned/image.
    avg_chars = total_chars / max(1, check_pages)
    return avg_chars < 100


def _needs_table_enrichment(document: Any) -> bool:
    """
    Check whether the lean-parsed document contains enough table blocks
    to warrant a second pass with FAST table-structure extraction.

    The lean pipeline still runs layout detection, which tags content blocks
    as "table" — it just doesn't reconstruct row/column structure.
    We count those tags here and decide whether the enriched pass is worth it.
    """
    table_count = 0
    # Docling stores items in document.body (list of DocItem)
    for item in getattr(document, "body", []):
        label = getattr(item, "label", None) or getattr(item, "content_type", "")
        if "table" in str(label).lower():
            table_count += 1
    # Only pay the TableFormer cost if there are meaningful tables.
    return table_count >= 3


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


def _build_lc_docs_from_document(document: Any, offset_page_no: int = 0) -> list[_ChunkDoc]:
    """
    Build LangChain-like docs directly from an already-converted Docling document.
    This avoids a second full conversion pass in DoclingLoader.
    """
    tokenizer = AutoTokenizer.from_pretrained(settings.EMBEDDING_MODEL, trust_remote_code=True)

    chunker = HybridChunker(
        tokenizer=tokenizer,
        max_tokens=600,
        merge_peers=True,
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
                    # Adjust page numbers for parallel chunk offsets
                    prov_list = item_dict.get("prov", [])
                    if prov_list:
                        for prov in prov_list:
                            if "page_no" in prov:
                                prov["page_no"] += offset_page_no
                    doc_items.append(item_dict)

        out.append(
            _ChunkDoc(
                page_content=text,
                metadata={"dl_meta": {"headings": headings, "doc_items": doc_items}},
            )
        )

    return out


def _convert_with_ocr(tmp_path: str):
    """Convert document with OCR path (SuryaOCR/RapidOCR preferred, Tesseract fallback)."""
    format_options = get_ocr_format_options()
    engine_name = "SuryaOCR" if settings.OCR_ENGINE.lower() == "suryaocr" else "RapidOCR"
    
    print(f"🔍 Using OCR Engine: {engine_name}")
    converter = DocumentConverter(format_options=format_options)
    try:
        result = converter.convert(tmp_path)
        return result, converter
    except Exception as exc:
        print(f"⚠️  {engine_name} failed ({exc}); falling back to Tesseract OCR")
        converter = DocumentConverter(format_options=_fallback_format_options)
        result = converter.convert(tmp_path)
        return result, converter


def extract_and_chunk(
    file_bytes: bytes,
    filename: str,
    offset_page_no: int = 0,
) -> tuple[list, str, int]:
    """
    Extract text from a document and chunk it using Docling's HybridChunker.

    Three-tier pipeline for PDFs:
      1. Lean parse  (no OCR, no table structure) — fastest
      2. If tables detected → re-parse with FAST table structure
      3. If text-sparse  → re-parse with OCR

    Args:
        file_bytes:     Raw file content
        filename:       Original filename (used for extension detection)
        offset_page_no: Page number offset for merged parallel segments

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
        t0 = time.time()
        print(f"📄 Docling: parsing {filename} ...")

        # ── Step 1: Convert document ──────────────────────────────────────
        if ext == ".pdf":
            # — Fast Detection: Skip Lean/Enriched if confirmed scanned ——————
            if is_scanned_pdf_fast(tmp_path):
                print("🧾 Fast detection: Scanned PDF confirmed. Jumping to Tier 3 (OCR)")
                result, converter = _convert_with_ocr(tmp_path)
                full_text = result.document.export_to_markdown()
                page_count = _get_page_count(result)
            else:
                # — Tier 1: Lean parse (no OCR, no table structure) ————————————
                print("⚡ Tier 1 (lean): parsing PDF without OCR or table structure")
                converter = DocumentConverter(format_options=_lean_format_options)
                result = converter.convert(tmp_path)
                full_text = result.document.export_to_markdown()
                page_count = _get_page_count(result)
                t_lean = time.time() - t0
                print(f"   Lean parse done in {t_lean:.1f}s — {page_count} pages, {len(full_text)} chars")

                if _should_enable_ocr(ext=ext, full_text=full_text, page_count=page_count):
                    # — Tier 3: OCR path (scanned PDF fallback) —————————————————
                    print("🧾 Low text density detected; switching to Tier 3 (OCR)")
                    result, converter = _convert_with_ocr(tmp_path)
                    full_text = result.document.export_to_markdown()
                    page_count = _get_page_count(result)
                elif _needs_table_enrichment(result.document):
                    # — Tier 2: Enriched parse (table-heavy PDF) ———————————————
                    t1 = time.time()
                    table_count = sum(
                        1 for item in getattr(result.document, "body", [])
                        if "table" in str(getattr(item, "label", "")).lower()
                    )
                    print(f"📊 Detected {table_count} tables; switching to Tier 2 (FAST table structure)")
                    converter = DocumentConverter(format_options=_enriched_format_options)
                    result = converter.convert(tmp_path)
                    full_text = result.document.export_to_markdown()
                    page_count = _get_page_count(result)
                    t_enrich = time.time() - t1
                    print(f"   Enriched parse done in {t_enrich:.1f}s")
                else:
                    print("✅ Text-rich PDF with few/no tables; lean parse is sufficient")

        else:
            # Non-PDF formats always go through OCR path
            result, converter = _convert_with_ocr(tmp_path)
            full_text = result.document.export_to_markdown()
            page_count = _get_page_count(result)

        t_total = time.time() - t0
        print(f"✅ Docling: parsed {page_count} pages, {len(full_text)} chars in {t_total:.1f}s")

        # ── Step 2: Chunk directly from conversion result (single pass) ────
        lc_docs = _build_lc_docs_from_document(result.document, offset_page_no=offset_page_no)
        if not lc_docs:
            raise RuntimeError("No chunks produced from direct Docling chunking")
        print(f"✂️  Docling: produced {len(lc_docs)} chunks")
        return lc_docs, full_text, page_count
    except Exception as chunk_err:
        # Compatibility fallback: keep old path as a safety net.
        print(f"⚠️  Direct chunking path failed ({chunk_err}); falling back to DoclingLoader")
        if converter is None:
            converter = DocumentConverter(format_options=_ocr_format_options)
        loader = DoclingLoader(
            file_path=tmp_path,
            export_type=ExportType.DOC_CHUNKS,
            converter=converter,
            chunker=HybridChunker(
                tokenizer=AutoTokenizer.from_pretrained(settings.EMBEDDING_MODEL, trust_remote_code=True),
                max_tokens=600,
                merge_peers=True,
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


def split_pdf_into_chunks(file_bytes: bytes, n: int = 2) -> list[tuple[bytes, int]]:
    """
    Split a PDF into N equal parts based on page count.
    Used for parallel processing across multiple workers.

    Returns:
        A list of (part_bytes, offset_page_no)
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    page_count = len(doc)

    if page_count < n:
        # If fewer pages than requested chunks, just do one page per chunk (or original if 1)
        n = max(1, page_count)

    if page_count <= 1:
        doc.close()
        return [(file_bytes, 0)]

    # Calculate page ranges for N chunks
    chunk_size = page_count // n
    remainder = page_count % n
    
    ranges = []
    current_page = 0
    for i in range(n):
        # Distribute remainder pages across the first few chunks
        extra = 1 if i < remainder else 0
        end_page = current_page + chunk_size + extra
        ranges.append((current_page, end_page))
        current_page = end_page

    parts = []
    for start, end in ranges:
        if start >= end:
            continue
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
        # We return the start page index as the offset to re-sync metadata later
        parts.append((new_doc.tobytes(), start))
        new_doc.close()

    doc.close()
    return parts
