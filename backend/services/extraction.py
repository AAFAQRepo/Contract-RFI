"""
Document extraction + chunking service — powered by Docling.

Single entry point:
    extract_and_chunk(file_bytes, filename)
        → (lc_docs, full_text, page_count)

Handles all formats (PDF, DOCX, PPTX, images) with:
  - Three-tier pipeline: Lean → Enriched (FAST tables) → OCR
  - SuryaOCR (default) for scanned / image-based documents
  - HybridChunker for document-aware chunking

Pipeline tiers:
  Tier 1 "Lean"     — No OCR, no table structure.  Fastest.
  Tier 2 "Enriched" — No OCR, FAST table structure. For table-heavy docs.
  Tier 3 "OCR"      — SuryaOCR (fallback: RapidOCR → Tesseract). For scanned docs.
"""

import os
import time
import tempfile
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import httpx
from docling.chunking import HybridChunker
from docling_core.types.doc.document import DoclingDocument
from transformers import AutoTokenizer
from core.config import get_settings

settings = get_settings()

# ── Silence Junk Logs ────────────────────────────────────────────────────────
logging.getLogger("docling").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.WARNING)
os.environ["TQDM_DISABLE"] = "1"

# ── Remote OCR Service Client ────────────────────────────────────────────────

OCR_SERVICE_URL = os.getenv("OCR_SERVICE_URL", "http://ocr-service:8001")

def remote_convert(file_bytes: bytes, filename: str, tier: str = "ocr"):
    """
    Calls the dedicated OCR service to perform conversion.
    """
    print(f"📡 Dispatching to Remote OCR Service: {filename} (tier={tier})...")
    files = {"file": (filename, file_bytes)}
    data = {"tier": tier}
    
    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(f"{OCR_SERVICE_URL}/convert", files=files, data=data)
            response.raise_for_status()
            res_json = response.json()
            
            # Reconstruct DoclingDocument from dict
            doc = DoclingDocument.model_validate(res_json["document"])
            return doc, res_json["markdown"], res_json["page_count"]
    except Exception as e:
        print(f"❌ Remote OCR failed for {filename}: {e}")
        raise

def remote_convert_batch(segments: list[tuple[bytes, str]], tier: str = "ocr"):
    """
    Calls the dedicated OCR service to perform BATCH conversion of multiple segments.
    Leverages A10 CUDA batching for massive speedup.
    """
    print(f"📡 Dispatching BATCH of {len(segments)} segments to Remote OCR Service...")
    
    # Format for httpx: list of tuples (name, (filename, bytes))
    files = [("files", (filename, file_bytes)) for file_bytes, filename in segments]
    data = {"tier": tier}
    
    try:
        with httpx.Client(timeout=600.0) as client:
            response = client.post(f"{OCR_SERVICE_URL}/convert_batch", files=files, data=data)
            response.raise_for_status()
            res_json = response.json()
            
            results = []
            for item in res_json["results"]:
                doc = DoclingDocument.model_validate(item["document"])
                results.append((doc, item["markdown"], item["page_count"]))
            
            return results, res_json["latency"]
    except Exception as e:
        print(f"❌ Remote BATCH OCR failed: {e}")
        raise

# ── Global Cached Tokenizer ──────────────────────────────────────────────────
_tokenizer = None

def get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        # Try local first to avoid 'junk' logging/network checks
        try:
            _tokenizer = AutoTokenizer.from_pretrained(
                settings.EMBEDDING_MODEL, 
                trust_remote_code=True, 
                local_files_only=True
            )
        except Exception:
            try:
                # If not local, allow one download
                print(f"⏳ Downloading tokenizer {settings.EMBEDDING_MODEL}...")
                _tokenizer = AutoTokenizer.from_pretrained(
                    settings.EMBEDDING_MODEL, 
                    trust_remote_code=True,
                    local_files_only=False
                )
            except Exception as e:
                print(f"❌ Failed to load tokenizer: {e}")
                raise
    return _tokenizer

print(f"📄 Extraction service (Client Mode) initialized using: {OCR_SERVICE_URL}")

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
    tokenizer = get_tokenizer()

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


def extract_and_chunk(
    file_bytes: bytes,
    filename: str,
    offset_page_no: int = 0,
) -> tuple[list, str, int]:
    """
    Extract text from a document and chunk it using Docling's HybridChunker.
    Uses a remote OCR service for the actual conversion to keep workers light.
    """
    ext = Path(filename).suffix.lower()
    if not ext:
        ext = ".pdf"

    try:
        t0 = time.time()
        print(f"📄 Docling: processing {filename} ...")

        # ── Step 1: Decision & Conversion ──────────────────────────────────
        tier = "lean"
        
        if ext == ".pdf":
            # Fast Local Check
            if is_scanned_pdf_fast_bytes(file_bytes):
                print("🧾 Fast detection: Scanned PDF confirmed. Using Tier 3 (OCR)")
                tier = "ocr"
            else:
                # Preliminary Lean Parse to check for tables
                doc, markdown, page_count = remote_convert(file_bytes, filename, tier="lean")
                
                if _should_enable_ocr(ext, markdown, page_count):
                    print("🧾 Low text density detected; switching to Tier 3 (OCR)")
                    tier = "ocr"
                elif _needs_table_enrichment(doc):
                    print("📊 Tables detected; switching to Tier 2 (enriched)")
                    tier = "enriched"
                else:
                    print("✅ Lean parse is sufficient")
                    # Already converted, skip redundant remote call
                    return _process_doc_result(doc, markdown, page_count, t0, offset_page_no)

        # Final Remote Convert (if not already returned)
        doc, markdown, page_count = remote_convert(file_bytes, filename, tier=tier)
        return _process_doc_result(doc, markdown, page_count, t0, offset_page_no)

    except Exception as err:
        print(f"❌ Extraction failed: {err}")
        raise


def _process_doc_result(doc, markdown, page_count, t_start, offset_page_no):
    t_total = time.time() - t_start
    print(f"✅ Docling: parsed {page_count} pages in {t_total:.1f}s")
    
    # ── Step 2: Chunk directly from conversion result (single pass) ──
    lc_docs = _build_lc_docs_from_document(doc, offset_page_no=offset_page_no)
    if not lc_docs:
        raise RuntimeError("No chunks produced from Docling document")
    
    print(f"✂️  Docling: produced {len(lc_docs)} chunks")
    return lc_docs, markdown, page_count


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
