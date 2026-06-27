"""MusicXML page validation, merging, and final score writing."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

from score_to_musicxml.errors import ConversionError
from score_to_musicxml.metadata import (
    ScoreMetadata,
    apply_score_metadata,
    composer_from_homr_title,
)
from score_to_musicxml.musicxml.rules import (
    apply_playback_tempo,
    ensure_staves_declarations,
    normalize_musicxml_timing,
    normalize_slur_numbers,
    remove_spurious_page_break_measures,
    repair_time_signatures_from_streams,
)
from score_to_musicxml.progress import log


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


def renumber_measures(parts: list[ET.Element]) -> None:
    """Renumber all measures in each part from one."""
    for part in parts:
        for measure_number, measure in enumerate(
            part.findall("./measure"),
            start=1,
        ):
            measure.set("number", str(measure_number))


def merge_musicxml_pages(  # noqa: PLR0912
    page_paths: list[Path],
    output_path: Path,
    metadata: ScoreMetadata | None = None,
    tempo: int | None = None,
) -> None:
    """
    Merge page-level MusicXML, then apply conservative homr cleanup rules.

    Page measures are appended by matching part position. Post-merge rules stay
    narrow and deterministic so they can be tested independently from PDF OCR.
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

    renumber_measures(combined_parts)

    updated_parts = ensure_staves_declarations(root)
    if updated_parts:
        log(f"Added explicit staff-count declarations to {updated_parts} part(s)")

    removed_break_measures = remove_spurious_page_break_measures(root)
    if removed_break_measures:
        log(f"Removed {removed_break_measures} spurious page-break measure(s)")
        renumber_measures(combined_parts)

    repaired_time_signatures = repair_time_signatures_from_streams(root)
    if repaired_time_signatures:
        log(f"Repaired {repaired_time_signatures} inferred time signature(s)")

    reordered_measures, irregular_measures = normalize_musicxml_timing(root)
    if reordered_measures:
        log(f"Reordered {reordered_measures} interleaved measure stream(s)")
    if irregular_measures:
        log(f"Marked {irregular_measures} irregular final measure(s)")
    renumbered_slurs = normalize_slur_numbers(root)
    if renumbered_slurs:
        log(f"Renumbered {renumbered_slurs} nested slur event(s)")

    if not root.findall(".//note"):
        raise ConversionError("Merged MusicXML does not contain any notes")

    if metadata is not None:
        resolved_metadata = ScoreMetadata(
            title=metadata.title,
            composer=metadata.composer or composer_from_homr_title(root),
        )
        apply_score_metadata(root, resolved_metadata)

    if tempo is not None:
        apply_playback_tempo(root, tempo)

    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
