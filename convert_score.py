"""Convert a PDF score to one MusicXML file with HOMR."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import cast

import pymupdf

DEFAULT_DPI = 300
DEFAULT_HOMR_REPO = Path(__file__).resolve().parent.parent / "homr"
LOW_INK_WHITE_RATIO = 0.995
GENERIC_PDF_TITLES = {
    "document",
    "image",
    "photo",
    "scan",
    "scanned document",
    "untitled",
}


class ConversionError(RuntimeError):
    """A conversion failure that can be shown without a traceback."""


@dataclass(frozen=True)
class ScoreMetadata:
    """Metadata that can be written to the exported MusicXML score."""

    title: str | None = None
    composer: str | None = None


def log(message: str) -> None:
    """Print one progress message immediately."""
    print(message, flush=True)


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
    HOMR's own title recognition.
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
    """Recover a composer when HOMR placed a credit in the title field."""
    homr_title = root.findtext("./work/work-title")
    if not homr_title:
        return None
    match = re.fullmatch(r"composed\s*by\s*(.+)", homr_title, re.IGNORECASE)
    if match is None:
        return None
    return " ".join(match.group(1).split()) or None


def render_pdf_pages(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    """
    Render a PDF to deterministically named PNG files accepted by HOMR.

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


def find_homr_repo() -> Path | None:
    """
    Return a local HOMR checkout, matching the PoC lookup strategy.

    The ``HOMR_REPO`` environment variable wins. If it is not set, the wrapper
    looks for a sibling checkout at ``../homr`` relative to this file.
    """
    configured_path = os.environ.get("HOMR_REPO")
    candidates = [
        Path(configured_path).expanduser() if configured_path else None,
        DEFAULT_HOMR_REPO,
    ]

    for candidate in candidates:
        if candidate is None:
            continue
        resolved_candidate = candidate.resolve()
        if (resolved_candidate / "pyproject.toml").is_file() and (
            resolved_candidate / "homr" / "main.py"
        ).is_file():
            return resolved_candidate

    return None


def homr_command() -> list[str]:
    """
    Build the HOMR command exactly like the PoC.

    Prefer the installed ``homr`` executable. If it is unavailable, fall back to
    ``uvx`` and use a local HOMR checkout when available.
    """
    installed_homr = shutil.which("homr")
    if installed_homr:
        return [installed_homr]

    installed_uvx = shutil.which("uvx")
    if installed_uvx:
        local_repo = find_homr_repo()
        if local_repo is not None:
            log(f"Using local HOMR checkout: {local_repo}")
            return [installed_uvx, "--from", str(local_repo), "homr"]
        return [installed_uvx, "homr"]

    raise ConversionError(
        "HOMR is unavailable. Install HOMR, install uv, or set HOMR_REPO."
    )


def is_low_ink_page(page_path: Path) -> bool:
    """
    Return whether an image is effectively a blank/non-score page.

    A page is skipped only after HOMR fails and at least 99.5% of its pixels
    share a near-white color. This avoids rejecting ordinary sparse score pages.
    """
    pixmap = pymupdf.Pixmap(page_path)  # type: ignore[no-untyped-call]
    white_ratio, dominant_color = pixmap.color_topusage()  # type: ignore[no-untyped-call]
    return white_ratio >= LOW_INK_WHITE_RATIO and all(
        channel >= 250 for channel in dominant_color
    )


def run_homr(  # noqa: PLR0912, PLR0913
    page_paths: list[Path],
    *,
    gpu: str,
    debug: bool,
    cache: bool,
    large_page: bool,
    metronome: int | None,
    tempo: int | None,
) -> list[Path]:
    """
    Run HOMR's CLI on all rendered pages in one directory-mode process.

    The command resolution deliberately mirrors the PoC instead of calling
    ``sys.executable -m homr.main``. That avoids accidentally using a different
    Python environment, HOMR version, or model setup.
    """
    if not page_paths:
        raise ConversionError("No rendered pages were provided to HOMR")

    command = [*homr_command(), str(page_paths[0].parent)]
    if gpu != "auto":
        command.extend(["--gpu", gpu])
    if debug:
        command.append("--debug")
    if cache:
        command.append("--cache")
    if large_page:
        command.append("--output-large-page")
    if metronome is not None:
        command.extend(["--output-metronome", str(metronome)])
    if tempo is not None:
        command.extend(["--output-tempo", str(tempo)])

    log(f"Running HOMR on {page_paths[0].parent}...")
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise ConversionError(f"HOMR exited with status {error.returncode}") from error

    outputs: list[Path] = []
    missing: list[str] = []
    for page_path in page_paths:
        output_path = page_path.with_suffix(".musicxml")
        if output_path.is_file():
            outputs.append(output_path)
        elif is_low_ink_page(page_path):
            log(f"Skipping low-ink page with no HOMR output: {page_path.name}")
        else:
            missing.append(output_path.name)

    if missing:
        raise ConversionError(f"HOMR did not produce output for: {', '.join(missing)}")
    if not outputs:
        raise ConversionError("HOMR did not produce any MusicXML pages")
    return outputs


def validate_matching_parts(page_paths: list[Path]) -> None:
    """
    Reject page files whose MusicXML part IDs do not match.

    Pages are merged by part position. Checking IDs first prevents a changed
    page layout from silently attaching measures to the wrong instrument.
    """
    expected_ids: list[str] | None = None
    for page_path in page_paths:
        try:
            root = ET.parse(page_path).getroot()  # noqa: S314
        except (OSError, ET.ParseError) as error:
            raise ConversionError(
                f"Invalid MusicXML {page_path.name}: {error}"
            ) from error

        part_ids = [part.get("id", "") for part in root.findall("./part")]
        if not part_ids or any(not part_id for part_id in part_ids):
            raise ConversionError(f"Missing MusicXML part IDs in {page_path.name}")
        if expected_ids is None:
            expected_ids = part_ids
        elif part_ids != expected_ids:
            raise ConversionError(
                f"Part IDs differ in {page_path.name}: "
                f"expected {expected_ids}, got {part_ids}"
            )


def ensure_staves_declarations(root: ET.Element) -> int:
    """
    Add missing ``staves`` declarations for HOMR grand-staff output.

    Some notation programs need this declaration when notes explicitly refer to
    staff 2. No notes, rests, voices, durations, ties, or slurs are changed.

    Returns:
        Number of parts whose staff declaration was set.
    """
    updated_parts = 0

    for part in root.findall("./part"):
        staff_numbers = [
            int(staff.text)
            for staff in part.findall(".//note/staff")
            if staff.text is not None and staff.text.isdigit()
        ]
        staff_count = max(staff_numbers, default=1)
        if staff_count <= 1:
            continue

        first_measure = part.find("./measure")
        if first_measure is None:
            continue
        attributes = first_measure.find("./attributes")
        if attributes is None:
            attributes = ET.Element("attributes")
            first_measure.insert(0, attributes)

        staves = attributes.find("./staves")
        if staves is None:
            staves = ET.Element("staves")
            children = list(attributes)
            first_clef_index = next(
                (index for index, child in enumerate(children) if child.tag == "clef"),
                len(children),
            )
            attributes.insert(first_clef_index, staves)

        staves.text = str(staff_count)
        updated_parts += 1

    return updated_parts


def note_stream_key(note: ET.Element) -> tuple[str, str]:
    """Return the staff and voice identifying a MusicXML note stream."""
    return (
        note.findtext("./staff") or "1",
        note.findtext("./voice") or "1",
    )


def note_duration(note: ET.Element) -> int:
    """Return a note duration, treating grace notes as durationless."""
    if note.find("./grace") is not None:
        return 0
    duration_text = note.findtext("./duration")
    return int(duration_text) if duration_text is not None else 0


def measure_duration(
    divisions: int,
    beats: int,
    beat_type: int,
) -> int | None:
    """Return the expected measure duration in MusicXML division units."""
    duration = Fraction(divisions * beats * 4, beat_type)
    return duration.numerator if duration.denominator == 1 else None


def measure_has_invalid_cursor(
    measure: ET.Element,
    expected_duration: int,
) -> bool:
    """Return whether a measure's sequential MusicXML cursor is invalid."""
    cursor = 0
    minimum_cursor = 0
    maximum_cursor = 0
    for child in measure:
        duration_text = child.findtext("./duration")
        duration = int(duration_text) if duration_text is not None else 0
        if child.tag == "note":
            if child.find("./grace") is None and child.find("./chord") is None:
                cursor += duration
        elif child.tag == "backup":
            cursor -= duration
        elif child.tag == "forward":
            cursor += duration
        minimum_cursor = min(minimum_cursor, cursor)
        maximum_cursor = max(maximum_cursor, cursor)

    return (
        minimum_cursor < 0
        or maximum_cursor > expected_duration
        or cursor != expected_duration
    )


def normalize_measure_streams(
    measure: ET.Element,
    expected_duration: int,
) -> bool:
    """
    Rebuild interleaved HOMR staff streams when each stream is already complete.

    HOMR sometimes emits correct upper and lower staves with backups at the
    wrong interleaving points. Grouping each staff/voice stream and inserting
    one full-measure backup preserves every note and its notation.
    """
    children = list(measure)
    temporal_indexes = [
        index
        for index, child in enumerate(children)
        if child.tag in {"note", "backup", "forward"}
    ]
    if not temporal_indexes:
        return False

    first_temporal = temporal_indexes[0]
    last_temporal = temporal_indexes[-1]
    temporal_span = children[first_temporal : last_temporal + 1]
    if any(child.tag not in {"note", "backup"} for child in temporal_span):
        return False

    streams: dict[tuple[str, str], list[ET.Element]] = {}
    stream_durations: dict[tuple[str, str], int] = {}
    for child in temporal_span:
        if child.tag != "note":
            continue
        stream_key = note_stream_key(child)
        streams.setdefault(stream_key, []).append(child)
        if child.find("./chord") is None:
            stream_durations[stream_key] = stream_durations.get(
                stream_key, 0
            ) + note_duration(child)

    if len(streams) < 2 or any(
        duration > expected_duration for duration in stream_durations.values()
    ):
        return False

    replacement: list[ET.Element] = []
    for stream_index, (stream_key, notes) in enumerate(streams.items()):
        if stream_index:
            backup = ET.Element("backup")
            ET.SubElement(backup, "duration").text = str(expected_duration)
            replacement.append(backup)
        replacement.extend(notes)
        missing_duration = expected_duration - stream_durations[stream_key]
        if missing_duration:
            forward = ET.Element("forward")
            ET.SubElement(forward, "duration").text = str(missing_duration)
            replacement.append(forward)

    measure[first_temporal : last_temporal + 1] = replacement
    return True


def normalize_musicxml_timing(root: ET.Element) -> tuple[int, int]:
    """
    Repair safe HOMR timing errors and mark a genuine irregular final measure.

    Returns:
        Counts of reordered measures and irregular final measures.
    """
    reordered_measures = 0
    irregular_measures = 0

    for part in root.findall("./part"):
        divisions = 1
        beats = 4
        beat_type = 4
        measures = part.findall("./measure")
        for measure in measures:
            attributes = measure.find("./attributes")
            if attributes is not None:
                divisions_text = attributes.findtext("./divisions")
                if divisions_text is not None:
                    divisions = int(divisions_text)
                beats_text = attributes.findtext("./time/beats")
                beat_type_text = attributes.findtext("./time/beat-type")
                if beats_text is not None and beat_type_text is not None:
                    beats = int(beats_text)
                    beat_type = int(beat_type_text)

            expected_duration = measure_duration(divisions, beats, beat_type)
            if expected_duration is None:
                continue
            has_invalid_cursor = measure_has_invalid_cursor(
                measure,
                expected_duration,
            )
            if has_invalid_cursor and normalize_measure_streams(
                measure,
                expected_duration,
            ):
                reordered_measures += 1
                continue

            stream_durations: dict[tuple[str, str], int] = {}
            for note in measure.findall("./note"):
                if note.find("./chord") is not None:
                    continue
                stream_key = note_stream_key(note)
                stream_durations[stream_key] = stream_durations.get(
                    stream_key, 0
                ) + note_duration(note)

            final_barline = measure.find("./barline[@location='right']/bar-style")
            has_final_barline = final_barline is not None and final_barline.text in {
                "light-heavy",
                "heavy-heavy",
            }
            if has_invalid_cursor and has_final_barline and stream_durations:
                measure.set("implicit", "yes")
                irregular_measures += 1

    return reordered_measures, irregular_measures


def merge_musicxml_pages(  # noqa: PLR0912
    page_paths: list[Path],
    output_path: Path,
    metadata: ScoreMetadata | None = None,
) -> None:
    """
    Merge page-level MusicXML without rewriting musical events.

    This is intentionally PoC-style: append page measures, renumber them, and
    add missing staff-count declarations. It does not normalize timing, rebuild
    voices, repair measures, or touch ties/slurs.
    """
    if not page_paths:
        raise ConversionError("No MusicXML pages were provided")

    validate_matching_parts(page_paths)
    try:
        tree = ET.parse(page_paths[0])  # noqa: S314
        root = tree.getroot()
        combined_parts = root.findall("./part")

        for page_path in page_paths[1:]:
            page_root = ET.parse(page_path).getroot()  # noqa: S314
            page_parts = page_root.findall("./part")
            if len(page_parts) != len(combined_parts):
                raise ConversionError(
                    f"{page_path.name} has {len(page_parts)} parts; "
                    f"expected {len(combined_parts)}"
                )

            for combined_part, page_part in zip(
                combined_parts,
                page_parts,
                strict=True,
            ):
                for measure in page_part.findall("./measure"):
                    combined_part.append(deepcopy(measure))
    except ConversionError:
        raise
    except (OSError, ET.ParseError, ValueError) as error:
        raise ConversionError(f"Unable to merge MusicXML pages: {error}") from error

    for part in combined_parts:
        for measure_number, measure in enumerate(
            part.findall("./measure"),
            start=1,
        ):
            measure.set("number", str(measure_number))

    updated_parts = ensure_staves_declarations(root)
    if updated_parts:
        log(f"Added explicit staff-count declarations to {updated_parts} part(s)")

    reordered_measures, irregular_measures = normalize_musicxml_timing(root)
    if reordered_measures:
        log(f"Reordered {reordered_measures} interleaved measure stream(s)")
    if irregular_measures:
        log(f"Marked {irregular_measures} irregular final measure(s)")

    if not root.findall(".//note"):
        raise ConversionError("Merged MusicXML does not contain any notes")

    if metadata is not None:
        resolved_metadata = ScoreMetadata(
            title=metadata.title,
            composer=metadata.composer or composer_from_homr_title(root),
        )
        apply_score_metadata(root, resolved_metadata)

    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


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
            tempo=args.tempo,
        )

        temporary_output = temporary_path / "combined.musicxml"
        log(f"Combining {len(page_outputs)} page(s)")
        merge_musicxml_pages(
            page_outputs,
            temporary_output,
            metadata=score_metadata,
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
    """Parse command-line options while preserving HOMR option names."""
    parser = argparse.ArgumentParser(
        description="Convert a PDF score to MusicXML with HOMR."
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
