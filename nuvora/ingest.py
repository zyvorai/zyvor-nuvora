# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Extract plain text from uploaded files. Standard library, except PDF (nuvora[pdf]) and local OCR (nuvora[ocr])."""
import csv
import io
import json
import re
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree

from .security import Fault

MAX_UPLOAD=20*1024*1024
TYPES={
    '.txt':'text/plain','.md':'text/markdown','.markdown':'text/markdown','.json':'application/json',
    '.csv':'text/csv','.html':'text/html','.htm':'text/html','.pdf':'application/pdf',
    '.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp',
    '.mp3':'audio/mpeg','.wav':'audio/wav','.m4a':'audio/mp4','.ogg':'audio/ogg','.webm':'audio/webm','.flac':'audio/flac',
}
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def kind(filename,content_type=''):
    suffix=('.'+filename.rsplit('.',1)[-1].lower()) if '.' in filename else ''
    if suffix in TYPES:
        return TYPES[suffix]
    base=(content_type or '').split(';')[0].strip().lower()
    if base in TYPES.values():
        return base
    raise Fault('Unsupported file type; use text, Markdown, JSON, CSV, HTML, DOCX, PDF, PNG/JPEG/WebP images or MP3/WAV/M4A/OGG/WebM/FLAC audio',415)


def media(detected):
    """'image', 'audio' or None for a detected content type."""
    return detected.split('/')[0] if detected.startswith(('image/','audio/')) else None


MAGIC={'image/png':(b'\x89PNG',),'image/jpeg':(b'\xff\xd8\xff',),'image/webp':(b'RIFF',)}


def check_image(data,detected):
    if not any(data.startswith(m) for m in MAGIC.get(detected,(b'',))):
        raise Fault('The file content does not match its image type',422)
    return data


def pdf_images(data,limit=50):
    """[(bytes, mime)] for the page images of a scanned PDF (one or more per page)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise Fault('PDF parsing needs the optional extra: pip install "zyvor-nuvora[pdf]"',503) from exc
    out=[]
    try:
        for page in PdfReader(io.BytesIO(data)).pages[:limit]:
            for image in page.images:
                raw=image.data
                mime='image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg' if raw.startswith(b'\xff\xd8') else None
                if mime:
                    out.append((raw,mime))
    except Exception as exc:
        raise Fault('Could not read images from this PDF',422) from exc
    return out


def ocr_local(images):
    """Tesseract OCR (nuvora[ocr] plus the tesseract binary)."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise Fault('OCR needs a vision model on this knowledge base or the optional extra: pip install "zyvor-nuvora[ocr]"',503) from exc
    pages=[]
    try:
        for raw,_ in images:
            pages.append(pytesseract.image_to_string(Image.open(io.BytesIO(raw))))
    except pytesseract.TesseractNotFoundError as exc:
        raise Fault('OCR needs the tesseract binary on the server',503) from exc
    return '\n\n'.join(pages)


def decode(data):
    for encoding in ('utf-8-sig','utf-16'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1')


class _Text(HTMLParser):
    SKIP={'script','style','noscript','template','svg'}
    BLOCK={'p','div','br','li','tr','h1','h2','h3','h4','h5','h6','section','article','pre','blockquote','table'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out=[]
        self.depth=0

    def handle_starttag(self,tag,attrs):
        if tag in self.SKIP:
            self.depth+=1
        elif tag in self.BLOCK:
            self.out.append('\n')

    def handle_endtag(self,tag):
        if tag in self.SKIP and self.depth:
            self.depth-=1
        elif tag in self.BLOCK:
            self.out.append('\n')

    def handle_data(self,data):
        if not self.depth:
            self.out.append(data)


def html_text(source):
    parser=_Text()
    parser.feed(source)
    parser.close()
    return ''.join(parser.out)


def docx_text(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info=archive.getinfo('word/document.xml')
            if info.file_size>50*1024*1024:
                raise Fault('DOCX document is too large',413)
            root=ElementTree.fromstring(archive.read(info))
    except (zipfile.BadZipFile,KeyError,ElementTree.ParseError) as exc:
        raise Fault('Not a readable DOCX file',422) from exc
    paragraphs=[]
    for para in root.iter(W+'p'):
        parts=[]
        for node in para.iter():
            if node.tag==W+'t' and node.text:
                parts.append(node.text)
            elif node.tag==W+'tab':
                parts.append('\t')
            elif node.tag in (W+'br',W+'cr'):
                parts.append('\n')
        paragraphs.append(''.join(parts))
    return '\n'.join(paragraphs)


def pdf_text(data):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise Fault('PDF parsing needs the optional extra: pip install "zyvor-nuvora[pdf]"',503) from exc
    try:
        reader=PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise Fault('Encrypted PDFs are not supported',422)
        return '\n\n'.join((page.extract_text() or '') for page in reader.pages[:2000])
    except Fault:
        raise
    except Exception as exc:
        raise Fault('Not a readable PDF file',422) from exc


def extract(filename,content_type,data):
    """Return (text, detected_type). Raises Fault for unsupported or unreadable input."""
    if not data:
        raise Fault('The file is empty')
    if len(data)>MAX_UPLOAD:
        raise Fault('Uploads are limited to 20 MiB',413)
    detected=kind(filename,content_type)
    if detected=='application/pdf':
        text=pdf_text(data)
    elif detected.endswith('wordprocessingml.document'):
        text=docx_text(data)
    elif detected=='text/html':
        text=html_text(decode(data))
    elif detected=='application/json':
        try:
            text=json.dumps(json.loads(decode(data)),indent=2,ensure_ascii=False)
        except ValueError as exc:
            raise Fault('Invalid JSON file',422) from exc
    elif detected=='text/csv':
        rows=csv.reader(io.StringIO(decode(data)))
        text='\n'.join(' | '.join(cell.strip() for cell in row) for row in rows)
    else:
        text=decode(data)
    text=re.sub(r'[ \t]+\n','\n',text.replace('\r\n','\n').replace('\x00',''))
    text=re.sub(r'\n{3,}','\n\n',text).strip()
    if not text:
        raise Fault('No text could be extracted from this file',422)
    return text[:500000],detected
