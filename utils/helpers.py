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

_WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
})

def sanitize_category(text, filepath="", max_len=40):
    """Reduce a model response to a valid Windows folder name.

    Rejects conversational replies (multi-line, sentences, long) and falls
    back to a deterministic extension category instead of an invalid name.
    This prevents WinError 123 when the LLM outputs essays instead of folder names.

    Args:
        text: The LLM response to sanitize
        filepath: The file being categorized (used for extension-based fallback)
        max_len: Maximum allowed length for the category name

    Returns:
        A clean, valid Windows folder name or extension-based fallback
    """
    ext = os.path.splitext(filepath or "")[1].lower()
    fallback = _EXT_FALLBACK.get(ext, "Other")
    if not isinstance(text, str) or not text:
        return fallback
    if isinstance(max_len, bool) or not isinstance(max_len, int) or max_len <= 0:
        return fallback

    stripped = text.strip()
    if "\n" in stripped or len(stripped) > max_len:
        return fallback
    # Remove markdown formatting characters but preserve underscores (valid in Windows)
    first = re.sub(r"[*`#]", "", stripped)
    # Remove Windows-illegal characters
    first = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", first)
    # Normalize whitespace
    first = re.sub(r"\s+", " ", first).strip()
    first = first[:max_len].rstrip(". ")
    if not first or first.endswith(("!", "?", ":", ",")):
        return fallback
    # Windows reserves device names even when an extension is present
    # (for example, CON.txt). Never create such a directory.
    device_stem = first.split(".", 1)[0].rstrip(" .").upper()
    if device_stem in _WINDOWS_RESERVED_NAMES:
        return fallback
    return first


FILE_PREVIEW_LIMIT = 2000
FILE_PREVIEW_MARKER = (
    f"\n\n[Content truncated: showing first {FILE_PREVIEW_LIMIT} characters]"
)


def truncate_file_preview(text, limit=FILE_PREVIEW_LIMIT):
    """Bound a file preview and explicitly disclose when content was cut off."""
    if not isinstance(text, str):
        return text
    if len(text) <= limit:
        return text
    return text[:limit] + FILE_PREVIEW_MARKER

def read_file_content_simple(file_path):
    """Read text content from .txt, .pdf, .docx, or .xlsx (first 2000 chars) without AI."""
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return truncate_file_preview(f.read(FILE_PREVIEW_LIMIT + 1))
        elif ext == '.pdf':
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ''
                for page in reader.pages[:3]:
                    text += page.extract_text() or ''
                return truncate_file_preview(text)
        elif ext == '.docx':
            if docx is None:
                return "python-docx not installed. Install with: pip install python-docx"
            doc = docx.Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return truncate_file_preview("\n".join(paragraphs))
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
            return truncate_file_preview("\n".join(result))
        return "[Content extraction not supported]"
    except Exception as e:
        return f"Error reading file: {e}"