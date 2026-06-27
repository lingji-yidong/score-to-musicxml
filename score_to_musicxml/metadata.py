"""Score metadata and tempo detection helpers."""

from __future__ import annotations

import importlib
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pymupdf

from score_to_musicxml.errors import ConversionError

MIN_TEMPO = 20
MAX_TEMPO = 300
TEMPO_OCR_DPI = 360
TEMPO_OCR_CROP = (0.06, 0.15, 0.35, 0.27)
GENERIC_PDF_TITLES = {
    "document",
    "image",
    "photo",
    "scan",
    "scanned document",
    "untitled",
}


@dataclass(frozen=True)
class ScoreMetadata:
    """Metadata that can be written to the exported MusicXML score."""

    title: str | None = None
    composer: str | None = None


def meaningful_metadata_value(value: object) -> str | None:
    """Return a useful PDF metadata value, excluding generic placeholders."""
    if not isinstance(value, str):
        return None
    cleaned_value = " ".join(value.split())
    normalized_value = cleaned_value.casefold()
    if (
        not cleaned_value
        or normalized_value in GENERIC_PDF_TITLES
        or "mymusicsheet" in normalized_value
        or normalized_value.endswith("> library")
    ):
        return None
    return cleaned_value


def metadata_from_filename(pdf_path: Path) -> ScoreMetadata:
    """
    Infer score metadata from a human-readable PDF filename.

    A filename in the common ``Title - Composer.pdf`` form supplies both
    fields. Other filenames supply only a title because guessing a composer
    from an arbitrary hyphen would be unreliable.
    """
    stem = " ".join(pdf_path.stem.split())
    stem = re.sub(r"^\d{8}[-_\s]+", "", stem)
    if " - " not in stem:
        return ScoreMetadata(title=stem or None)

    title, composer = stem.rsplit(" - ", maxsplit=1)
    return ScoreMetadata(
        title=title.strip() or None,
        composer=composer.strip() or None,
    )


def detect_score_metadata(pdf_path: Path) -> ScoreMetadata:
    """
    Detect title and composer from PDF metadata, then fall back to its filename.

    PDF metadata is preferred when it contains real values. The filename
    fallback is deterministic and avoids adding another OCR pass on top of
    homr's own title recognition.
    """
    filename_metadata = metadata_from_filename(pdf_path)
    try:
        with pymupdf.open(pdf_path) as document:  # type: ignore[no-untyped-call]
            pdf_metadata = document.metadata or {}
    except (OSError, RuntimeError, ValueError) as error:
        raise ConversionError(f"Unable to read PDF metadata: {error}") from error

    return ScoreMetadata(
        title=meaningful_metadata_value(pdf_metadata.get("title"))
        or filename_metadata.title,
        composer=meaningful_metadata_value(pdf_metadata.get("author"))
        or filename_metadata.composer,
    )


def tempo_from_text(text: str) -> int | None:
    """Extract a plausible metronome number from text near an equals sign."""
    for match in re.finditer(r"[=\uff1d]\s*(\d{2,3})", text):
        tempo = int(match.group(1))
        if MIN_TEMPO <= tempo <= MAX_TEMPO:
            return tempo
    return None


def tempo_from_pdf_text(pdf_path: Path) -> int | None:
    """Detect tempo from an embedded PDF text layer when one is available."""
    try:
        with pymupdf.open(pdf_path) as document:  # type: ignore[no-untyped-call]
            for page_index in range(document.page_count):
                page = document[page_index]
                page_text = page.get_text("text")
                if not isinstance(page_text, str):
                    continue
                tempo = tempo_from_text(page_text)
                if tempo is not None:
                    return tempo
    except (OSError, RuntimeError, ValueError):
        return None
    return None


def tempo_from_first_page_ocr(pdf_path: Path) -> int | None:
    """
    Detect tempo from the first page's opening metronome-marking area.

    Many scanned scores have no usable text layer. OCR only a narrow upper-left
    crop so page numbers, lyrics, and copyright text are unlikely to masquerade
    as a metronome marking.
    """
    try:
        rapidocr_module = importlib.import_module("rapidocr")
        rapid_ocr_class = cast(Any, rapidocr_module).RapidOCR
    except (ImportError, AttributeError):
        return None

    try:
        with pymupdf.open(pdf_path) as document:  # type: ignore[no-untyped-call]
            if document.page_count == 0:
                return None
            page = document[0]
            left, top, right, bottom = TEMPO_OCR_CROP
            clip = pymupdf.Rect(  # type: ignore[no-untyped-call]
                page.rect.width * left,
                page.rect.height * top,
                page.rect.width * right,
                page.rect.height * bottom,
            )
            matrix = pymupdf.Matrix(  # type: ignore[no-untyped-call]
                TEMPO_OCR_DPI / 72,
                TEMPO_OCR_DPI / 72,
            )
            pixmap = page.get_pixmap(
                matrix=matrix,
                alpha=False,
                clip=clip,
            )
            with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
                pixmap.save(image_file.name)
                result = rapid_ocr_class()(image_file.name)
    except (OSError, RuntimeError, ValueError, IndexError):
        return None

    texts = getattr(result, "txts", None)
    if texts is None:
        return None
    return tempo_from_text(" ".join(str(text) for text in texts))


def detect_score_tempo(pdf_path: Path) -> int | None:
    """Detect a printed opening tempo marking from PDF text or first-page OCR."""
    return tempo_from_pdf_text(pdf_path) or tempo_from_first_page_ocr(pdf_path)


def apply_score_metadata(root: ET.Element, metadata: ScoreMetadata) -> None:
    """Write detected score title and composer without changing musical data."""
    if metadata.title:
        work = root.find("./work")
        if work is None:
            work = ET.Element("work")
            root.insert(0, work)
        work_title = work.find("./work-title")
        if work_title is None:
            work_title = ET.SubElement(work, "work-title")
        work_title.text = metadata.title

    if metadata.composer:
        identification = root.find("./identification")
        if identification is None:
            identification = ET.Element("identification")
            part_list = root.find("./part-list")
            insertion_index = (
                list(root).index(part_list) if part_list is not None else 0
            )
            root.insert(insertion_index, identification)

        composer = next(
            (
                creator
                for creator in identification.findall("./creator")
                if creator.get("type") == "composer"
            ),
            None,
        )
        if composer is None:
            composer = ET.Element("creator", {"type": "composer"})
            identification.insert(0, composer)
        composer.text = metadata.composer


def composer_from_homr_title(root: ET.Element) -> str | None:
    """Recover a composer when homr placed a credit in the title field."""
    homr_title = root.findtext("./work/work-title")
    if not homr_title:
        return None
    match = re.fullmatch(r"composed\s*by\s*(.+)", homr_title, re.IGNORECASE)
    if match is None:
        return None
    return " ".join(match.group(1).split()) or None
