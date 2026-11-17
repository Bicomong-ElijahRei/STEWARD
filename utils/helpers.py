import os
import PyPDF2

def read_file_content_simple(file_path):
    """Read text content from .txt or .pdf (first 2000 chars) without AI."""
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read(2000)
        elif ext == '.pdf':
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ''
                for page in reader.pages[:3]:
                    text += page.extract_text() or ''
                return text[:2000]
        else:
            return "[Content extraction not supported]"
    except Exception as e:
        return f"Error reading file: {e}"