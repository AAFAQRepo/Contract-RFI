from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import tempfile
import os
import time
from ocr_service.utils import ConverterRegistry

app = FastAPI(title="Contract RFI OCR Service")

@app.get("/health")
def health():
    return {"status": "ok", "engine": "docling-surya"}

@app.post("/convert")
def convert(
    file: UploadFile = File(...),
    tier: str = Form("ocr")
):
    """
    Accepts a PDF segment and returns the structured Docling document as JSON.
    Runs in a threadpool (via 'def') to allow parallel GPU processing.
    """
    if tier not in ["lean", "enriched", "ocr"]:
        raise HTTPException(status_code=400, detail="Invalid tier")

    t_start = time.time()
    filename = file.filename or "document.pdf"
    print(f"🚀 [OCR Service] Received {filename} ({tier}) - Starting Parallel Processing")
    
    suffix = os.path.splitext(filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        # Use sync file reading to avoid event loop blocking
        content = file.file.read() 
        tmp.write(content)
        tmp_path = tmp.name

    try:
        converter = ConverterRegistry.get(tier)
        result = converter.convert(tmp_path)
        
        # Serialize DoclingDocument to dict for transport
        doc_dict = result.document.export_to_dict()
        
        t_end = time.time()
        latency = t_end - t_start
        print(f"✅ [OCR Service] Finished {filename} in {latency:.2f}s")
        
        return {
            "document": doc_dict,
            "markdown": result.document.export_to_markdown(),
            "page_count": len(result.document.pages) if hasattr(result.document, "pages") else 1,
            "latency": latency
        }
    except Exception as e:
        print(f"❌ [OCR Service] Error converting {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
