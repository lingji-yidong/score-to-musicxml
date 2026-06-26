"""MusicXML cleanup rules for homr output."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction

from score_to_musicxml.errors import ConversionError


def ensure_staves_declarations(root: ET.Element) -> int:
    """
    Add missing ``staves`` declarations for homr grand-staff output.

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


def right_bar_style(measure: ET.Element) -> str | None:
    """Return the right barline style when one is present."""
    return measure.findtext("./barline[@location='right']/bar-style")


def is_staff_rest_only(measure: ET.Element, staff_number: str) -> bool:
    """Return whether a staff contains only rests in the measure."""
    staff_notes = [
        note
        for note in measure.findall("./note")
        if note.findtext("./staff") == staff_number
    ]
    return bool(staff_notes) and all(
        note.find("./rest") is not None for note in staff_notes
    )


def measure_has_single_rest(measure: ET.Element) -> bool:
    """Return whether a measure contains only one rest note."""
    notes = measure.findall("./note")
    return len(notes) == 1 and notes[0].find("./rest") is not None


def measure_key_fifths(measure: ET.Element) -> str | None:
    """Return the measure's key signature fifths value when present."""
    return measure.findtext("./attributes/key/fifths")


def is_section_bridge_fragment(
    previous_measure: ET.Element,
    measure: ET.Element,
    next_measure: ET.Element,
) -> bool:
    """Identify a false section-bridge system inserted before a new page."""
    section_bar_styles = {"light-light", "light-heavy", "heavy-heavy"}
    return (
        next_measure.find("./print[@new-system='yes']") is not None
        and measure.find("./print") is None
        and measure.find("./attributes/key") is not None
        and next_measure.find("./attributes/key") is not None
        and right_bar_style(previous_measure) in section_bar_styles
        and right_bar_style(measure) in section_bar_styles
        and is_staff_rest_only(measure, "2")
    )


def is_page_leading_rest_fragment(
    measure: ET.Element,
    next_measure: ET.Element,
) -> bool:
    """Identify a false page-leading rest emitted before the real first system."""
    final_bar_styles = {"light-heavy", "heavy-heavy"}
    measure_key = measure_key_fifths(measure)
    next_key = measure_key_fifths(next_measure)
    return (
        measure.find("./print[@new-system='yes']") is not None
        and measure_key is not None
        and next_key is not None
        and measure_key != next_key
        and right_bar_style(measure) in final_bar_styles
        and measure_has_single_rest(measure)
    )


def free_slur_number(active_numbers: set[str]) -> str | None:
    """Return an available MusicXML slur number."""
    for number in range(1, 7):
        candidate = str(number)
        if candidate not in active_numbers:
            return candidate
    return None


def normalize_slur_numbers(root: ET.Element) -> int:
    """
    Renumber nested slurs that homr emits with the same MusicXML number.

    MusicXML renderers use the ``number`` attribute to pair simultaneous slurs.
    homr often emits nested phrase and local slurs as ``number="1"`` on the
    same staff, so a renderer may drop or mis-pair them. This preserves every
    slur event in document order and only changes the number on overlapping
    starts and their matching stops.
    """
    changed_slurs = 0

    for part in root.findall("./part"):
        active_numbers_by_staff: dict[str, set[str]] = {}
        slur_stacks: dict[tuple[str, str], list[str]] = {}

        for measure in part.findall("./measure"):
            for note in measure.findall("./note"):
                staff = note.findtext("./staff", "1")
                active_numbers = active_numbers_by_staff.setdefault(staff, set())
                slurs = note.findall("./notations/slur")

                for slur in [
                    candidate for candidate in slurs if candidate.get("type") == "stop"
                ]:
                    source_number = slur.get("number", "1")
                    stack = slur_stacks.setdefault((staff, source_number), [])
                    if not stack:
                        continue
                    actual_number = stack.pop()
                    active_numbers.discard(actual_number)
                    if actual_number != source_number:
                        slur.set("number", actual_number)
                        changed_slurs += 1

                for slur in [
                    candidate for candidate in slurs if candidate.get("type") == "start"
                ]:
                    source_number = slur.get("number", "1")
                    actual_number = source_number
                    if source_number in active_numbers:
                        replacement = free_slur_number(active_numbers)
                        if replacement is None:
                            continue
                        actual_number = replacement
                        slur.set("number", actual_number)
                        changed_slurs += 1

                    active_numbers.add(actual_number)
                    stack = slur_stacks.setdefault((staff, source_number), [])
                    stack.append(actual_number)

    return changed_slurs


def remove_spurious_page_break_measures(root: ET.Element) -> int:
    """
    Drop isolated homr fragments inserted around page-leading systems.

    homr can produce a fake one-measure system at a page/section boundary: the
    previous measure closes a section, the fragment has only a single-staff
    pickup-like upper line plus lower-staff whole rest, and the next measure
    restarts the real page with ``new-system`` and its own key signature. It can
    also produce a page-leading one-rest fragment with a conflicting key
    signature and final bar before the real first system. Removing only these
    narrow shapes avoids rewriting ordinary musical content.
    """
    removed_measures = 0

    for part in root.findall("./part"):
        measures = part.findall("./measure")
        for index in range(len(measures) - 1, -1, -1):
            measure = measures[index]
            next_measure = measures[index + 1] if index + 1 < len(measures) else None
            previous_measure = measures[index - 1] if index else None
            is_fragment = False

            if next_measure is not None and is_page_leading_rest_fragment(
                measure,
                next_measure,
            ):
                is_fragment = True
            elif (
                previous_measure is not None
                and next_measure is not None
                and is_section_bridge_fragment(
                    previous_measure,
                    measure,
                    next_measure,
                )
            ):
                is_fragment = True

            if not is_fragment:
                continue

            part.remove(measure)
            removed_measures += 1

    return removed_measures


def normalize_measure_streams(
    measure: ET.Element,
    expected_duration: int,
) -> bool:
    """
    Rebuild interleaved homr staff streams when each stream is already complete.

    homr sometimes emits correct upper and lower staves with backups at the
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
    Repair safe homr timing errors and mark a genuine irregular final measure.

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


def apply_playback_tempo(root: ET.Element, tempo: int) -> None:
    """
    Set the playback tempo at the start of the score.

    homr only emits a ``sound`` element when a visible metronome marking is
    also requested. Preserve any direction content it generated while ensuring
    that the explicit ``--tempo`` value controls playback on its own.
    """
    first_measure = root.find("./part/measure")
    if first_measure is None:
        raise ConversionError("MusicXML does not contain a first measure")

    existing_sound = first_measure.find("./direction/sound")
    if existing_sound is not None:
        existing_sound.set("tempo", str(tempo))
        return

    direction = ET.Element("direction", {"placement": "above"})
    ET.SubElement(direction, "sound", {"tempo": str(tempo)})
    insertion_index = next(
        (
            index
            for index, child in enumerate(first_measure)
            if child.tag not in {"attributes", "print"}
        ),
        len(first_measure),
    )
    first_measure.insert(insertion_index, direction)
