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
import concurrent.futures
import threading
import logging

# ── Logging Suppression ───────────────────────────────────────────────
# Silence redundant plugin/initialization logs for cleaner parallel output
logging.getLogger("docling").setLevel(logging.ERROR)
logging.getLogger("docling_ibm_models").setLevel(logging.ERROR)
_logger = logging.getLogger(__name__)

# ── Thread-local Engine Cache ─────────────────────────────────────────
# Re-using converters and chunkers avoids 2-3s of init-time per segment.
_thread_cache = threading.local()

from core.config import get_settings

settings = get_settings()

# ── Pipeline options (configured once) ────────────────────────────────

# Primary OCR pipeline (Surya)
_pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    ocr_model="suryaocr",
    allow_external_plugins=True,
    ocr_options=SuryaOcrOptions(lang=["en", "ar"]),
    accelerator_device="cuda",  # Max speed, but uses ~2-3GB VRAM per worker
)

_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_pipeline_options),
    InputFormat.IMAGE: PdfFormatOption(pipeline_options=_pipeline_options),
}

# Fallback OCR pipeline (Tesseract CLI)
_fallback_pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    ocr_model="tesseractcli",
    allow_external_plugins=False,
    ocr_options=TesseractCliOcrOptions(lang=["eng", "ara", "hin"]),
    accelerator_device="cuda",
)

_fallback_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_fallback_pipeline_options),
    InputFormat.IMAGE: PdfFormatOption(pipeline_options=_fallback_pipeline_options),
}

# Fast path for digital PDFs: skip OCR entirely.
_no_ocr_pipeline_options = PdfPipelineOptions(
    do_ocr=False,
    allow_external_plugins=False,
    accelerator_device="cuda",
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


def _is_likely_scanned(filename: str, file_bytes: bytes) -> bool:
    """Heuristics to detect if a document needs OCR before even trying."""
    ext = Path(filename).suffix.lower()
    if ext in [".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".gif"]:
        return True
    
    if ext == ".pdf":
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            if len(doc) > 0:
                total_text = ""
                for i in range(min(3, len(doc))):
                    total_text += doc[i].get_text().strip()
                if len(total_text) < 100:
                    return True
        except Exception:
            pass
            
    return False


def _parallel_pdf_convert(tmp_path: str, format_options: dict) -> tuple[list, str, int]:
    """Split large PDF into chunks, process in parallel threads, and merge."""
    import fitz
    
    try:
        doc = fitz.open(tmp_path)
        page_count = len(doc)
    except Exception as e:
        print(f"⚠️  PyMuPDF open failed: {e}. Falling back to sequential.")
        converter = DocumentConverter(format_options=format_options)
        res = converter.convert(tmp_path)
        return _build_lc_docs_from_document(res.document), res.document.export_to_markdown(), _get_page_count(res)

    PARALLEL_THRESHOLD = 20
    if page_count < PARALLEL_THRESHOLD:
        doc.close()
        converter = DocumentConverter(format_options=format_options)
        res = converter.convert(tmp_path)
        return _build_lc_docs_from_document(res.document), res.document.export_to_markdown(), _get_page_count(res)

    print(f"🚀 Splitting {page_count} page PDF for parallel Docling conversion...")
    SEGMENT_SIZE = 40  # Increased for lower overhead
    segments = []
    for start_page in range(0, page_count, SEGMENT_SIZE):
        end_page = min(start_page + SEGMENT_SIZE - 1, page_count - 1)
        sub_doc = fitz.open()
        sub_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)
        
        fd, sub_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        sub_doc.save(sub_path)
        sub_doc.close()
        segments.append({"path": sub_path, "offset": start_page})
        
    doc.close()

    def process_segment(seg):
        # Retrieve or initialize thread-local converter
        cache_key = f"conv_{id(format_options)}"
        if not hasattr(_thread_cache, cache_key):
            setattr(_thread_cache, cache_key, DocumentConverter(format_options=format_options))
        
        converter = getattr(_thread_cache, cache_key)
        res = converter.convert(seg["path"])
        txt = res.document.export_to_markdown()
        docs = _build_lc_docs_from_document(res.document)
        # Fix page offsets from sub-document local page to global page
        offset = seg["offset"]
        for d in docs:
            items = d.metadata.get("dl_meta", {}).get("doc_items", [])
            for item in items:
                for prov in item.get("prov", []):
                    if "page_no" in prov:
                        prov["page_no"] += offset
        return docs, txt

    all_lc_docs = []
    full_texts = []
    
    # Using 3 workers is the "Goldilocks" zone for throughput vs scheduling overhead
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(process_segment, seg): seg for seg in segments}
        results = [None] * len(segments)
        for fut in concurrent.futures.as_completed(futures):
            seg = futures[fut]
            idx = segments.index(seg)
            try:
                r_docs, r_txt = fut.result()
                results[idx] = (r_docs, r_txt)
            except Exception as e:
                print(f"⚠️ Segment extraction failed: {e}")
                results[idx] = ([], "")

    # Cleanup temp segments
    for seg in segments:
        try:
            os.unlink(seg["path"])
        except:
            pass

    for r_docs, r_txt in results:
        if r_docs: all_lc_docs.extend(r_docs)
        if r_txt: full_texts.append(r_txt)
            
    return all_lc_docs, "\n\n".join(full_texts), page_count


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
    # Reuse thread-local chunker to stabilize chunk boundaries and save init time
    if not hasattr(_thread_cache, "chunker"):
        _thread_cache.chunker = HybridChunker(
            tokenizer=settings.EMBEDDING_MODEL,
            max_tokens=512,
        )
    chunker = _thread_cache.chunker

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

        # ── Step 1: Pre-emptive OCR Check ───────────
        needs_ocr = _is_likely_scanned(filename, file_bytes)
        if needs_ocr:
            print("🧾 Pre-emptive OCR triggered (detected image/scanned PDF)")
            lc_docs, full_text, page_count = _parallel_pdf_convert(tmp_path, _format_options)
            print(f"✅ Docling: parsed {page_count} pages, {len(full_text)} chars")
            print(f"✂️  Docling: produced {len(lc_docs)} chunks")
            return lc_docs, full_text, page_count

        # ── Step 2: Convert document (fast path first for PDFs) ───────────
        if ext == ".pdf":
            print("⚡ Fast path: trying PDF parse without OCR (Parallelized if large)")
            lc_docs, full_text, page_count = _parallel_pdf_convert(tmp_path, _no_ocr_format_options)

            if _should_enable_ocr(ext=ext, full_text=full_text, page_count=page_count):
                print("🧾 Low native text density detected; enabling OCR path")
                lc_docs, full_text, page_count = _parallel_pdf_convert(tmp_path, _format_options)
            else:
                print("✅ Native PDF text sufficient; skipped OCR")
        else:
            lc_docs, full_text, page_count = _parallel_pdf_convert(tmp_path, _format_options)

        print(f"✅ Docling: parsed {page_count} pages, {len(full_text)} chars")
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
