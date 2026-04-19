import os
import sys

# Add the current directory and backend to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def download():
    print("🚀 Pre-downloading AI models for Docling and RapidOCR...")
    
    try:
        from docling.document_converter import DocumentConverter
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions, TableFormerMode
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import PdfFormatOption

        # Configure options that trigger all heavy models (Layout, Table, OCR)
        options = PdfPipelineOptions(
            do_ocr=True,
            do_table_structure=True,
            ocr_options=RapidOcrOptions()
        )
        options.table_structure_options.mode = TableFormerMode.ACCURATE
        
        # Initialize converter to trigger downloads
        # Docling 2.x usually downloads on the first .convert(), 
        # but initializing the pipeline might trigger some.
        # To be certain, we'd need a 1-page dummy PDF.
        print("Initializing Docling converter...")
        DocumentConverter(format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options)
        })
        
        print("✅ Docling models ready.")
    except Exception as e:
        print(f"⚠️  Docling model initialization skipped or failed: {e}")

    try:
        from rapidocr_onnxruntime import RapidOCR
        print("Initializing RapidOCR...")
        # RapidOCR downloads models on init if they don't exist in site-packages/rapidocr/models
        RapidOCR()
        print("✅ RapidOCR models ready.")
    except Exception as e:
        print(f"⚠️  RapidOCR model initialization failed: {e}")

    try:
        print("🔍 Checking if SuryaOCR is installed for pre-caching...")
        # Try to import surya internal models to trigger HF downloads
        from surya.model.detection.model import load_model as load_det_model
        from surya.model.recognition.model import load_model as load_rec_model
        from surya.model.ordering.model import load_model as load_order_model
        
        print("📥 Downloading Surya detection model...")
        load_det_model()
        print("📥 Downloading Surya recognition model...")
        load_rec_model()
        print("📥 Downloading Surya ordering model...")
        load_order_model()
        print("✅ SuryaOCR models pre-cached.")
    except ImportError:
        print("ℹ️  SuryaOCR not found, skipping pre-cache.")
    except Exception as e:
        print(f"⚠️  SuryaOCR pre-cache failed: {e}")

if __name__ == "__main__":
    download()
