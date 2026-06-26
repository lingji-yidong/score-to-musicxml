"""PDF rendering and page-image inspection."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from score_to_musicxml.errors import ConversionError

DEFAULT_DPI = 300
LOW_INK_WHITE_RATIO = 0.995


def render_pdf_pages(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    """
    Render a PDF to deterministically named PNG files accepted by homr.

    This intentionally follows the PoC path: PyMuPDF Matrix scaling rather than
    changing the OCR pipeline or post-processing page images.

    Args:
        pdf_path: Source PDF score.
        output_dir: Temporary directory for page images.
        dpi: Rasterization resolution.

    Returns:
        Rendered page paths in source order.
    """
    if not pdf_path.is_file():
        raise ConversionError(f"Input PDF does not exist: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ConversionError(f"Input must be a PDF file: {pdf_path}")
    if dpi <= 0:
        raise ConversionError("DPI must be greater than zero")

    output_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72
    transform = pymupdf.Matrix(scale, scale)  # type: ignore[no-untyped-call]

    try:
        with pymupdf.open(pdf_path) as document:  # type: ignore[no-untyped-call]
            if document.needs_pass:
                raise ConversionError("Password-protected PDFs are not supported")
            if document.page_count == 0:
                raise ConversionError("Input PDF has no pages")

            page_digits = max(3, len(str(document.page_count)))
            page_paths: list[Path] = []
            for page_number, page in enumerate(document, start=1):
                page_path = output_dir / f"page-{page_number:0{page_digits}d}.png"
                page.get_pixmap(matrix=transform, alpha=False).save(page_path)
                page_paths.append(page_path)
            return page_paths
    except ConversionError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ConversionError(f"Unable to render PDF: {error}") from error


def is_low_ink_page(page_path: Path) -> bool:
    """
    Return whether an image is effectively a blank/non-score page.

    A page is skipped only after homr fails and at least 99.5% of its pixels
    share a near-white color. This avoids rejecting ordinary sparse score pages.
    """
    pixmap = pymupdf.Pixmap(page_path)  # type: ignore[no-untyped-call]
    white_ratio, dominant_color = pixmap.color_topusage()  # type: ignore[no-untyped-call]
    return white_ratio >= LOW_INK_WHITE_RATIO and all(
        channel >= 250 for channel in dominant_color
    )
