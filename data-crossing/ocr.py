from pdf2image import convert_from_path
import pytesseract

def pdf_to_text(pdf_path):
    images = convert_from_path(pdf_path, dpi=300)
    full_text = ""
    
    for pages in images:
        text = pytesseract.image_to_string(pages, lang='por')
        full_text+=text
    
    return{
        "text": full_text
    }