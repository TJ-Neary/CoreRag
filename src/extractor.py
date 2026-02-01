import logging
import pypdf
import docx
from pathlib import Path

def extract_text(file_path: Path) -> str:
    """Extracts text content from supported file types."""
    ext = file_path.suffix.lower()
    
    try:
        if ext == '.pdf':
            return _extract_pdf(file_path)
        elif ext == '.docx':
            return _extract_docx(file_path)
        elif ext in ['.txt', '.md', '.log', '.csv', '.json', '.yaml']:
            return file_path.read_text(errors='replace')
        else:
            logging.warning(f"Unsupported file type: {ext}. Skipping extraction.")
            return ""
    except Exception as e:
        logging.error(f"Error extracting text from {file_path.name}: {e}")
        return ""

def _extract_pdf(path: Path) -> str:
    text = ""
    with open(path, 'rb') as f:
        reader = pypdf.PdfReader(f)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    return text

def _extract_docx(path: Path) -> str:
    doc = docx.Document(path)
    return "\n".join([p.text for p in doc.paragraphs])
