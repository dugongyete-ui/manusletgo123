"""Semantic file categorisation (Manus getSessionFilesV2 equivalent).

Maps a filename + content-type to one stable category so the UI can group
deliverables the way official Manus does: slides / tables / docs / media /
code / archives / other. Pure function, no IO — usable on both the session
files endpoint and the library aggregation.
"""

import os
from typing import Optional

CATEGORY_SLIDES = "slides"
CATEGORY_TABLES = "tables"
CATEGORY_DOCS = "docs"
CATEGORY_MEDIA = "media"
CATEGORY_CODE = "code"
CATEGORY_ARCHIVES = "archives"
CATEGORY_OTHER = "other"

_EXTENSION_MAP = {
    # Slides / presentations
    "ppt": CATEGORY_SLIDES, "pptx": CATEGORY_SLIDES, "odp": CATEGORY_SLIDES,
    "key": CATEGORY_SLIDES,
    # Tables / structured data
    "csv": CATEGORY_TABLES, "tsv": CATEGORY_TABLES, "xlsx": CATEGORY_TABLES,
    "xls": CATEGORY_TABLES, "ods": CATEGORY_TABLES,
    # Documents / writing
    "md": CATEGORY_DOCS, "txt": CATEGORY_DOCS, "pdf": CATEGORY_DOCS,
    "doc": CATEGORY_DOCS, "docx": CATEGORY_DOCS, "rtf": CATEGORY_DOCS,
    "odt": CATEGORY_DOCS, "tex": CATEGORY_DOCS, "epub": CATEGORY_DOCS,
    # Media (images / audio / video)
    "png": CATEGORY_MEDIA, "jpg": CATEGORY_MEDIA, "jpeg": CATEGORY_MEDIA,
    "gif": CATEGORY_MEDIA, "webp": CATEGORY_MEDIA, "svg": CATEGORY_MEDIA,
    "bmp": CATEGORY_MEDIA, "ico": CATEGORY_MEDIA,
    "mp3": CATEGORY_MEDIA, "wav": CATEGORY_MEDIA, "ogg": CATEGORY_MEDIA,
    "mp4": CATEGORY_MEDIA, "webm": CATEGORY_MEDIA, "mov": CATEGORY_MEDIA,
    "avi": CATEGORY_MEDIA, "mkv": CATEGORY_MEDIA,
    # Code / build outputs
    "js": CATEGORY_CODE, "mjs": CATEGORY_CODE, "ts": CATEGORY_CODE,
    "tsx": CATEGORY_CODE, "jsx": CATEGORY_CODE, "py": CATEGORY_CODE,
    "java": CATEGORY_CODE, "rb": CATEGORY_CODE, "go": CATEGORY_CODE,
    "rs": CATEGORY_CODE, "c": CATEGORY_CODE, "h": CATEGORY_CODE,
    "cpp": CATEGORY_CODE, "php": CATEGORY_CODE, "html": CATEGORY_CODE,
    "htm": CATEGORY_CODE, "css": CATEGORY_CODE, "scss": CATEGORY_CODE,
    "vue": CATEGORY_CODE, "svelte": CATEGORY_CODE, "json": CATEGORY_CODE,
    "yaml": CATEGORY_CODE, "yml": CATEGORY_CODE, "toml": CATEGORY_CODE,
    "xml": CATEGORY_CODE, "sql": CATEGORY_CODE, "sh": CATEGORY_CODE,
    "ipynb": CATEGORY_CODE,
    # Archives / bundles
    "zip": CATEGORY_ARCHIVES, "tar": CATEGORY_ARCHIVES,
    "gz": CATEGORY_ARCHIVES, "tgz": CATEGORY_ARCHIVES,
    "bz2": CATEGORY_ARCHIVES, "7z": CATEGORY_ARCHIVES, "rar": CATEGORY_ARCHIVES,
}

_CONTENT_TYPE_PREFIXES = (
    ("image/", CATEGORY_MEDIA),
    ("audio/", CATEGORY_MEDIA),
    ("video/", CATEGORY_MEDIA),
    ("text/html", CATEGORY_CODE),
    ("text/csv", CATEGORY_TABLES),
    ("application/pdf", CATEGORY_DOCS),
    ("application/json", CATEGORY_CODE),
    ("application/zip", CATEGORY_ARCHIVES),
    ("text/plain", CATEGORY_DOCS),
)


def categorize_file(
    filename: Optional[str],
    content_type: Optional[str] = None,
) -> str:
    """Best-effort semantic category for a deliverable file."""
    ext = ""
    if filename:
        ext = os.path.splitext(filename.strip().lower())[1].lstrip(".")
    if ext in _EXTENSION_MAP:
        return _EXTENSION_MAP[ext]
    ct = (content_type or "").split(";")[0].strip().lower()
    for prefix, category in _CONTENT_TYPE_PREFIXES:
        if ct.startswith(prefix):
            return category
    if ext:
        return CATEGORY_OTHER
    return CATEGORY_OTHER
