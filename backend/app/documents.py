"""
documents.py  --  File se text nikalna aur chhote tukdon (chunks) me todna.
"""
from io import BytesIO
from pathlib import Path

from docx import Document
import re

from google.genai import types
from pypdf import PdfReader, PdfWriter

from . import config
from .config import CHUNK_SIZE, CHUNK_OVERLAP, ALLOWED_EXTENSIONS
from .errors import BadInput


def extract_pages(filename: str, file_bytes: bytes) -> list[dict]:
    """
    Inputs: filename (extension se type pata chalta hai), file_bytes (raw bytes).
    Returns: [{'text': str, 'page': int}] -- sirf wahi pages jisme text ho.
    (Scanned PDF me text nahi hota -> khaali list; OCR included nahi hai.)
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise BadInput("Only PDF, DOCX or TXT files are supported.")
    try:
        if suffix == ".pdf":
            # PdfReader(stream) -> .pages (list); page.extract_text() -> str ya None
            reader = PdfReader(BytesIO(file_bytes))
            pages = []
            for number, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""      # BUG FIX: pehle har page 2 baar extract hota tha
                if text.strip():
                    pages.append({"text": text, "page": number})
            if not pages and config.OCR_ENABLED and len(reader.pages) > 0:
                return ocr_pdf(reader)       # scanned PDF: text layer nahi hai -> Gemini se padho
            return pages
        if suffix == ".docx":
            # Document(stream) -> .paragraphs (list); paragraph.text -> str
            doc = Document(BytesIO(file_bytes))
            text = "\n".join(p.text for p in doc.paragraphs)
            return [{"text": text, "page": 1}] if text.strip() else []
        text = file_bytes.decode("utf-8", errors="replace")
        return [{"text": text, "page": 1}] if text.strip() else []
    except BadInput:
        raise
    except Exception as exc:   # corrupt / password-protected file
        raise BadInput("This file couldn't be read (it may be corrupted or password-protected).") from exc


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Inputs: text, size (max characters per chunk), overlap (do chunks ke beech common characters).
    Returns: list[str] -- overlapping tukde (overlap isliye ki baat beech me na kate).
    """
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("size > overlap >= 0 hona chahiye.")
    normalized = " ".join(text.split())      # extra spaces/newlines hata do
    step, chunks, start = size - overlap, [], 0
    while start < len(normalized):
        piece = normalized[start:start + size].strip()
        if piece:
            chunks.append(piece)
        start += step
    return chunks


def build_chunks(filename: str, file_bytes: bytes) -> list[dict]:
    """
    Inputs: filename, file_bytes.
    Returns: [{'text', 'source' (filename), 'page', 'chunk_on_page'}]
    """
    result = []
    for page in extract_pages(filename, file_bytes):
        for index, chunk in enumerate(chunk_text(page["text"])):
            result.append({"text": chunk, "source": filename,
                           "page": page["page"], "chunk_on_page": index})
    return result


_PAGE_MARK = re.compile(r"^=== PAGE (\d+) ===\s*$", re.M)

def ocr_pdf(reader: PdfReader) -> list[dict]:
    """
    Scanned PDF ko Gemini (vision) se padhwata hai. Har OCR_PAGES_PER_REQUEST pages = 1 chat request.
    Input : reader (pypdf PdfReader).
    Output: [{'text': str, 'page': int}] -- asli page numbers ke saath (citations sahi rahein).
    Quota: chat limit (500/din) se kharch hota hai, isliye OCR_MAX_PAGES se bade PDF reject.
    """
    from .llm import get_gateway           # yahin import: circular import se bachne ke liye
    total = len(reader.pages)
    if total > config.OCR_MAX_PAGES:
        raise BadInput(f"This scanned PDF has {total} pages. On the free tier, scanned PDFs are limited to "
                       f"{config.OCR_MAX_PAGES} pages. Please split it and upload the parts.")
    gateway = get_gateway()
    pages: list[dict] = []
    step = config.OCR_PAGES_PER_REQUEST
    for start in range(0, total, step):
        writer = PdfWriter()
        for i in range(start, min(start + step, total)):
            writer.add_page(reader.pages[i])
        buf = BytesIO()
        writer.write(buf)
        # types.Part.from_bytes(data=bytes, mime_type=str) -> file ko model ko bhejne ka part
        pdf_part = types.Part.from_bytes(data=buf.getvalue(), mime_type="application/pdf")
        prompt = ("Transcribe ALL text in this PDF exactly as written. Start every page with a line "
                  "'=== PAGE n ===' (n = 1 for the first page of THIS file, then 2, ...). "
                  "Output only the transcription, no comments.")
        response = gateway.generate(
            None, [types.Content(role="user", parts=[pdf_part, types.Part(text=prompt)])],
            types.GenerateContentConfig(temperature=0.0, max_output_tokens=8000))
        try:
            text = (response.text or "").strip()
        except Exception:
            text = ""
        marks = list(_PAGE_MARK.finditer(text))
        if not marks and text:                       # model ne markers nahi lagaye: poora block first page ka
            pages.append({"text": text, "page": start + 1})
        for idx, m in enumerate(marks):
            end = marks[idx + 1].start() if idx + 1 < len(marks) else len(text)
            body = text[m.end():end].strip()
            if body:
                pages.append({"text": body, "page": start + int(m.group(1))})
    return pages