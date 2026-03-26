from docling_surya import SuryaOcrOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
import os

def main():
    # Path to the uploaded document
    source = os.path.join(os.path.dirname(__file__), "doc", "SLA - ESOM and AAFAQ (1).pdf")

    if not os.path.exists(source):
        print(f"File not found: {source}")
        return

    print(f"Processing: {source}")

    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        ocr_model="suryaocr",
        allow_external_plugins=True,
        # Recognizing English by default as per the user's example
        ocr_options=SuryaOcrOptions(lang=["en"]),
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )

    result = converter.convert(source)
    markdown_output = result.document.export_to_markdown()
    
    # Save output to a file (in doc/ directory) for easier review
    output_path = source + ".md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown_output)

    print(f"OCR Complete! Markdown written to: {output_path}")
    
    # Print a snippet to standard output
    print("-" * 40)
    print("Snippet of extraction:")
    print("-" * 40)
    print(markdown_output[:2000])

if __name__ == "__main__":
    main()
