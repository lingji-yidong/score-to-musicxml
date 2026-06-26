"""Convert a PDF score to one MusicXML file with homr."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import cast

from score_to_musicxml.errors import ConversionError
from score_to_musicxml.homr_runner import run_homr
from score_to_musicxml.metadata import (
    ScoreMetadata,
    detect_score_metadata,
    detect_score_tempo,
)
from score_to_musicxml.musicxml.merge import merge_musicxml_pages
from score_to_musicxml.pdf import DEFAULT_DPI, render_pdf_pages
from score_to_musicxml.progress import log


def convert_pdf(args: argparse.Namespace) -> Path:
    """Run the complete PDF-to-MusicXML pipeline."""
    input_pdf = cast(Path, args.input_pdf)
    configured_output = cast(Path | None, args.output)
    output_path = configured_output or input_pdf.with_suffix(".musicxml")
    detected_metadata = detect_score_metadata(input_pdf)
    score_metadata = ScoreMetadata(
        title=cast(str | None, args.title) or detected_metadata.title,
        composer=cast(str | None, args.composer) or detected_metadata.composer,
    )
    explicit_tempo = cast(int | None, args.tempo)
    score_tempo = explicit_tempo or detect_score_tempo(input_pdf)
    if explicit_tempo is None and score_tempo is not None:
        log(f"Detected tempo: {score_tempo}")

    if output_path.exists() and not args.overwrite:
        raise ConversionError(
            f"Output already exists: {output_path}. Use --overwrite to replace it."
        )
    if output_path.suffix.lower() not in {".musicxml", ".xml"}:
        raise ConversionError("Output must use a .musicxml or .xml extension")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="score-to-musicxml-") as temporary_dir:
        temporary_path = Path(temporary_dir)
        page_paths = render_pdf_pages(input_pdf, temporary_path, args.dpi)
        log(f"Rendered {len(page_paths)} page(s) at {args.dpi} DPI")
        page_outputs = run_homr(
            page_paths,
            gpu=args.gpu,
            debug=args.debug,
            cache=args.cache,
            large_page=args.large_page,
            metronome=args.metronome,
            tempo=explicit_tempo,
        )

        temporary_output = temporary_path / "combined.musicxml"
        log(f"Combining {len(page_outputs)} page(s)")
        merge_musicxml_pages(
            page_outputs,
            temporary_output,
            metadata=score_metadata,
            tempo=score_tempo,
        )
        os.replace(temporary_output, output_path)

    if score_metadata.title:
        log(f"Title: {score_metadata.title}")
    if score_metadata.composer:
        log(f"Composer: {score_metadata.composer}")
    log(f"Saved: {output_path}")
    return output_path


def positive_integer(value: str) -> int:
    """Parse a positive integer for argparse."""
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line options while preserving homr option names."""
    parser = argparse.ArgumentParser(
        description="Convert a PDF score to MusicXML with homr."
    )
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--dpi", type=positive_integer, default=DEFAULT_DPI)
    parser.add_argument("--gpu", choices=("auto", "no", "force"), default="auto")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--cache", action="store_true")
    parser.add_argument("--large-page", action="store_true")
    parser.add_argument("--metronome", type=positive_integer)
    parser.add_argument("--tempo", type=positive_integer)
    parser.add_argument("--title", help="Override the detected score title")
    parser.add_argument("--composer", help="Override the detected composer")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the wrapper and return a shell-friendly exit code."""
    try:
        convert_pdf(parse_args(argv))
    except (ConversionError, ET.ParseError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
