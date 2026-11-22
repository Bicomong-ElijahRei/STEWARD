import os
import re
import PyPDF2

try:
    import docx  # python-docx
except ImportError:
    docx = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

_EXT_FALLBACK = {
    ".pdf": "Documents", ".doc": "Documents", ".docx": "Documents",
    ".xls": "Spreadsheets", ".xlsx": "Spreadsheets", ".csv": "Spreadsheets",
    ".txt": "Text", ".md": "Text",
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images",
    ".mp4": "Media", ".mkv": "Media", ".mov": "Media", ".mp3": "Audio",
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives",
}

def sanitize_category(text, filepath="", max_len=40):
    """Reduce a model response to a valid Windows folder name.
    Rejects conversational replies (multi-line, sentences, long) and falls
    back to a deterministic extension category instead of an invalid name.
    """
    ext = os.path.splitext(filepath or "")[1].lower()
    fallback = _EXT_FALLBACK.get(ext, "Other")
    if not text:
        return fallback
    stripped = text.strip()
    if "\n" in stripped or len(stripped) > max_len:
        return fallback
    first = _re.sub(r"[*`#]", "", stripped.splitlines()[0])
    first = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", first)
    first = re.sub(r"\s+", " ", first).strip().rstrip(". ")
    if not first or first.endswith((".", "!", "?", ":", ",")):
        return fallback
    return first[:max_len]

def read_file_content_simple(file_path):
    """Read text content from .txt, .pdf, .docx, or .xlsx (first 2000 chars) without AI."""
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
        elif ext == '.docx':
            if docx is None:
                return "python-docx not installed. Install with: pip install python-docx"
            doc = docx.Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs)[:2000]
        elif ext == '.xlsx':
            if openpyxl is None:
                return "openpyxl not installed. Install with: pip install openpyxl"
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            result = []
            for sheet_name in wb.sheetnames[:3]:
                ws = wb[sheet_name]
                result.append(f"--- Sheet: {sheet_name} ---")
                for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
                    values = [str(v) for v in row if v is not None]
                    if values:
                        result.append(" | ".join(values))
            return "\n".join(result)[:2000]
        else:
            return "[Content extraction not supported]"
    except Exception as e:
        return f"Error reading file: {e}"