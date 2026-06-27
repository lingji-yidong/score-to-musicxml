"""Apply the converter's safe MusicXML timing repairs to an existing file."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from score_to_musicxml.metadata import (
    ScoreMetadata,
    apply_score_metadata,
)
from score_to_musicxml.musicxml.rules import (
    normalize_musicxml_timing,
    normalize_slur_numbers,
    remove_spurious_page_break_measures,
    repair_time_signatures_from_streams,
)


def main() -> None:
    """Repair timing in place or write the result to another path."""
    parser = argparse.ArgumentParser()
    parser.add_argument("input_musicxml", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--composer")
    args = parser.parse_args()

    output_path = args.output or args.input_musicxml
    tree = ET.parse(args.input_musicxml)  # noqa: S314
    removed = remove_spurious_page_break_measures(tree.getroot())
    if removed:
        for part in tree.getroot().findall("./part"):
            for measure_number, measure in enumerate(
                part.findall("./measure"),
                start=1,
            ):
                measure.set("number", str(measure_number))
    repaired_time_signatures = repair_time_signatures_from_streams(tree.getroot())
    reordered, irregular = normalize_musicxml_timing(tree.getroot())
    renumbered = normalize_slur_numbers(tree.getroot())
    apply_score_metadata(
        tree.getroot(),
        ScoreMetadata(title=args.title, composer=args.composer),
    )
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    print(
        f"Removed {removed} spurious page-break measure(s); "
        f"repaired {repaired_time_signatures} time signature(s); "
        f"reordered {reordered} measure(s); "
        f"marked {irregular} irregular final measure(s); "
        f"renumbered {renumbered} nested slur event(s)"
    )


if __name__ == "__main__":
    main()
