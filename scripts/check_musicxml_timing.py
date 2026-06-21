"""Report MusicXML measures whose event cursor exceeds their time signature."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


@dataclass(frozen=True)
class TimingIssue:
    """One measure whose MusicXML event stream has invalid timing."""

    measure_number: str
    expected_duration: Fraction
    final_cursor: Fraction
    minimum_cursor: Fraction
    maximum_cursor: Fraction


def child_duration(child: ET.Element, divisions: int) -> Fraction:
    """Return a note, backup, or forward duration in quarter-note units."""
    duration_text = child.findtext("./duration")
    if duration_text is None:
        return Fraction()
    return Fraction(int(duration_text), divisions)


def find_timing_issues(root: ET.Element) -> list[TimingIssue]:
    """Find measures whose sequential event cursor leaves valid boundaries."""
    issues: list[TimingIssue] = []
    divisions = 1
    beats = 4
    beat_type = 4

    for measure in root.findall("./part/measure"):
        cursor = Fraction()
        minimum_cursor = Fraction()
        maximum_cursor = Fraction()

        for child in measure:
            if child.tag == "attributes":
                divisions_text = child.findtext("./divisions")
                if divisions_text is not None:
                    divisions = int(divisions_text)
                beats_text = child.findtext("./time/beats")
                beat_type_text = child.findtext("./time/beat-type")
                if beats_text is not None and beat_type_text is not None:
                    beats = int(beats_text)
                    beat_type = int(beat_type_text)
                continue

            duration = child_duration(child, divisions)
            if child.tag == "note":
                if child.find("./grace") is None and child.find("./chord") is None:
                    cursor += duration
            elif child.tag == "backup":
                cursor -= duration
            elif child.tag == "forward":
                cursor += duration

            minimum_cursor = min(minimum_cursor, cursor)
            maximum_cursor = max(maximum_cursor, cursor)

        expected_duration = Fraction(beats * 4, beat_type)
        if measure.get("implicit") == "yes":
            continue
        if (
            minimum_cursor < 0
            or maximum_cursor > expected_duration
            or cursor != expected_duration
        ):
            issues.append(
                TimingIssue(
                    measure_number=measure.get("number", "?"),
                    expected_duration=expected_duration,
                    final_cursor=cursor,
                    minimum_cursor=minimum_cursor,
                    maximum_cursor=maximum_cursor,
                )
            )

    return issues


def main() -> int:
    """Run the timing report command."""
    parser = argparse.ArgumentParser()
    parser.add_argument("musicxml", type=Path)
    parser.add_argument("--measure")
    args = parser.parse_args()

    root = ET.parse(args.musicxml).getroot()  # noqa: S314
    if args.measure:
        measure = next(
            (
                candidate
                for candidate in root.findall("./part/measure")
                if candidate.get("number") == args.measure
            ),
            None,
        )
        if measure is None:
            parser.error(f"measure not found: {args.measure}")
        divisions = 1
        cursor = Fraction()
        stream_durations: dict[tuple[str, str], Fraction] = {}
        for child in measure:
            if child.tag == "attributes":
                divisions_text = child.findtext("./divisions")
                if divisions_text is not None:
                    divisions = int(divisions_text)
                continue
            duration = child_duration(child, divisions)
            before = cursor
            if child.tag == "note":
                if child.find("./grace") is None and child.find("./chord") is None:
                    cursor += duration
                    stream = (
                        child.findtext("./staff") or "1",
                        child.findtext("./voice") or "1",
                    )
                    stream_durations[stream] = (
                        stream_durations.get(stream, Fraction()) + duration
                    )
            elif child.tag == "backup":
                cursor -= duration
            elif child.tag == "forward":
                cursor += duration
            if child.tag in {"note", "backup", "forward"}:
                print(
                    f"{child.tag:7} staff={child.findtext('./staff') or '-'} "
                    f"voice={child.findtext('./voice') or '-'} "
                    f"duration={duration} cursor={before}->{cursor}"
                )
        print(f"streams={stream_durations}")
        return 0

    issues = find_timing_issues(root)
    for issue in issues:
        print(
            f"measure {issue.measure_number}: "
            f"expected={issue.expected_duration}, "
            f"final={issue.final_cursor}, "
            f"min={issue.minimum_cursor}, "
            f"max={issue.maximum_cursor}"
        )
    print(f"{len(issues)} timing issue(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
