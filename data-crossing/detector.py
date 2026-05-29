import fitz
import sys

def detect(pdf_path: str, threshold: int = 50) -> dict:
    doc = fitz.open(pdf_path)
    full_text = ""

    for page in doc:
        full_text += page.get_text()

    doc.close()

    doc_type = "searchable" if len(full_text) >= threshold else "scanned"

    return {
        "type": doc_type,
        "total_chars": len(full_text),
        "text": full_text
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 detector.py file.pdf")
        sys.exit(1)

    result = detect(sys.argv[1])
    print(f"Type: {result['type']}")
    print(f"Characters: {result['total_chars']}")