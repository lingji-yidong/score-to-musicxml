"""Apply the converter's safe MusicXML timing repairs to an existing file."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

from convert_score import (
    ScoreMetadata,
    apply_score_metadata,
    normalize_musicxml_timing,
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
    reordered, irregular = normalize_musicxml_timing(tree.getroot())
    apply_score_metadata(
        tree.getroot(),
        ScoreMetadata(title=args.title, composer=args.composer),
    )
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    print(
        f"Reordered {reordered} measure(s); "
        f"marked {irregular} irregular final measure(s)"
    )


if __name__ == "__main__":
    main()
