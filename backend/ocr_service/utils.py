from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
    TesseractCliOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from core.config import get_settings
import logging

settings = get_settings()

# ── Silence Junk Logs ────────────────────────────────────────────────────────
logging.getLogger("docling").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Tier 1 — Lean: no OCR, no table structure.
_lean_pipeline_options = PdfPipelineOptions(
    do_ocr=False,
    do_table_structure=False,
    allow_external_plugins=True,
)
_lean_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_lean_pipeline_options),
}

# Tier 2 — Enriched
_enriched_pipeline_options = PdfPipelineOptions(
    do_ocr=False,
    do_table_structure=True,
    allow_external_plugins=True,
)
_enriched_pipeline_options.table_structure_options = TableStructureOptions(mode=TableFormerMode.FAST)
_enriched_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_enriched_pipeline_options),
}

import torch
_device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🖥️ [OCR Service] Hardware detection: {_device.upper()}")

def get_ocr_format_options():
    """Factory to get OCR options based on settings."""
    if settings.OCR_ENGINE.lower() == "suryaocr":
        from docling_surya import SuryaOcrOptions
        surya_options = PdfPipelineOptions(
            do_ocr=True,
            do_table_structure=True,
            ocr_model="suryaocr",
            allow_external_plugins=True,
            ocr_options=SuryaOcrOptions(lang=["en"]),
        )
        surya_options.table_structure_options = TableStructureOptions(mode=TableFormerMode.FAST)
        return {
            InputFormat.PDF: PdfFormatOption(pipeline_options=surya_options),
            InputFormat.IMAGE: PdfFormatOption(pipeline_options=surya_options),
        }
    
    # Default RapidOCR fallback
    ocr_options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        ocr_options=RapidOcrOptions()
    )
    return {
        InputFormat.PDF: PdfFormatOption(pipeline_options=ocr_options),
        InputFormat.IMAGE: PdfFormatOption(pipeline_options=ocr_options),
    }

class ConverterRegistry:
    _instances = {}

    @classmethod
    def get(cls, tier: str) -> DocumentConverter:
        if tier not in cls._instances:
            print(f"⏳ [OCR Service] Warming up [{tier}] converter on {_device.upper()}...")
            t0 = time.time()
            if tier == "lean":
                cls._instances[tier] = DocumentConverter(format_options=_lean_format_options)
            elif tier == "enriched":
                cls._instances[tier] = DocumentConverter(format_options=_enriched_format_options)
            elif tier == "ocr":
                # Ensure torch is using the right device globally if possible
                cls._instances[tier] = DocumentConverter(format_options=get_ocr_format_options())
            
            t_warm = time.time() - t0
            print(f"✅ [OCR Service] Converter [{tier}] warmed in {t_warm:.1f}s.")
        return cls._instances[tier]
