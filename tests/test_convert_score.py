"""Tests for the score-to-musicxml processing rules."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf
import pytest

from convert_score import (
    ConversionError,
    ScoreMetadata,
    apply_score_metadata,
    composer_from_homr_title,
    detect_score_metadata,
    ensure_staves_declarations,
    is_low_ink_page,
    merge_musicxml_pages,
    normalize_musicxml_timing,
    render_pdf_pages,
    validate_matching_parts,
)


def test_render_pdf_pages_uses_stable_names(tmp_path: Path) -> None:
    """Render PDF pages using stable names that preserve source order."""
    pdf_path = tmp_path / "score.pdf"
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    document.new_page()
    document.new_page()
    document.save(pdf_path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]

    pages = render_pdf_pages(pdf_path, tmp_path / "pages", dpi=72)

    assert [page.name for page in pages] == ["page-001.png", "page-002.png"]


def test_is_low_ink_page_distinguishes_blank_page(tmp_path: Path) -> None:
    """Classify an empty page as low ink without skipping an inked page."""
    pdf_path = tmp_path / "coverage.pdf"
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    document.new_page()
    inked_page = document.new_page()
    inked_page.draw_rect((50, 50, 400, 700), color=(0, 0, 0), fill=(0, 0, 0))
    document.save(pdf_path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    pages = render_pdf_pages(pdf_path, tmp_path / "pages", dpi=72)

    assert is_low_ink_page(pages[0])
    assert not is_low_ink_page(pages[1])


def test_validate_matching_parts_rejects_changed_part_ids(tmp_path: Path) -> None:
    """Reject page-level MusicXML files whose part IDs do not match."""
    first = tmp_path / "page-001.musicxml"
    second = tmp_path / "page-002.musicxml"
    first.write_text(
        "<score-partwise><part id='P1'/></score-partwise>", encoding="utf-8"
    )
    second.write_text(
        "<score-partwise><part id='P2'/></score-partwise>", encoding="utf-8"
    )

    with pytest.raises(ConversionError, match="Part IDs differ"):
        validate_matching_parts([first, second])


def test_ensure_staves_declarations_adds_grand_staff_count(tmp_path: Path) -> None:
    """Declare the detected staff count for grand-staff MusicXML."""
    musicxml_path = tmp_path / "score.musicxml"
    musicxml_path.write_text(
        """<score-partwise><part id="P1"><measure number="1">
        <attributes><divisions>1</divisions><clef><sign>G</sign></clef></attributes>
        <note><rest/><duration>1</duration><staff>2</staff></note>
        </measure></part></score-partwise>""",
        encoding="utf-8",
    )

    root = ET.parse(musicxml_path).getroot()  # noqa: S314
    ensure_staves_declarations(root)

    assert root.findtext("./part/measure/attributes/staves") == "2"


def test_merge_musicxml_pages_preserves_notes_ties_and_slurs(
    tmp_path: Path,
) -> None:
    """Append pages without removing HOMR's grace notes, ties, or slurs."""
    first_page = tmp_path / "page-001.musicxml"
    second_page = tmp_path / "page-002.musicxml"
    output = tmp_path / "combined.musicxml"
    first_page.write_text(
        """<score-partwise><part id="P1"><measure number="1">
        <attributes><divisions>24</divisions>
        <time><beats>3</beats><beat-type>8</beat-type></time></attributes>
        <note><rest/><duration>36</duration><voice>1</voice><staff>1</staff></note>
        <backup><duration>36</duration></backup>
        <note><rest/><duration>36</duration><voice>1</voice><staff>2</staff></note>
        </measure></part></score-partwise>""",
        encoding="utf-8",
    )
    second_page.write_text(
        """<score-partwise><part id="P1"><measure number="1">
        <note><grace/><pitch><step>C</step><octave>5</octave></pitch>
        <voice>1</voice><staff>1</staff>
        <tie type="start"/><notations><tied type="start"/>
        <slur type="start" number="1"/></notations></note>
        <note><rest/><duration>24</duration><voice>2</voice><staff>1</staff>
        <notations><slur type="stop" number="1"/></notations></note>
        </measure></part></score-partwise>""",
        encoding="utf-8",
    )

    merge_musicxml_pages([first_page, second_page], output)

    root = ET.parse(output).getroot()  # noqa: S314
    measures = root.findall("./part/measure")
    assert [measure.get("number") for measure in measures] == ["1", "2"]
    assert [child.tag for child in measures[0]] == [
        "attributes",
        "note",
        "backup",
        "note",
    ]
    assert [child.tag for child in measures[1]] == [
        "note",
        "forward",
        "backup",
        "note",
        "forward",
    ]
    assert measures[0].findtext("./backup/duration") == "36"
    assert measures[1].find("./note/grace") is not None
    assert measures[1].findtext("./note[2]/voice") == "2"
    assert measures[1].find("./note/tie[@type='start']") is not None
    assert measures[1].find("./note/notations/tied[@type='start']") is not None
    assert len(measures[1].findall(".//slur")) == 2


def test_detect_score_metadata_uses_filename_when_pdf_metadata_is_generic(
    tmp_path: Path,
) -> None:
    """Infer title and composer from a conventional score filename."""
    pdf_path = tmp_path / "Street Where Wind Resides - Yukiko Isomura.pdf"
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    document.new_page()
    document.set_metadata({"title": "Document", "author": ""})
    document.save(pdf_path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]

    metadata = detect_score_metadata(pdf_path)

    assert metadata == ScoreMetadata(
        title="Street Where Wind Resides",
        composer="Yukiko Isomura",
    )


def test_detect_score_metadata_removes_date_prefix_and_ignores_photo_title(
    tmp_path: Path,
) -> None:
    """Prefer a clean filename over generic scanner metadata."""
    pdf_path = tmp_path / "20260214-Blue Valentine.pdf"
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    document.new_page()
    document.set_metadata({"title": "Photo", "author": ""})
    document.save(pdf_path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]

    metadata = detect_score_metadata(pdf_path)

    assert metadata == ScoreMetadata(title="Blue Valentine")


def test_detect_score_metadata_ignores_mymusicsheet_library_title(
    tmp_path: Path,
) -> None:
    """Prefer the score filename over a website export placeholder."""
    pdf_path = tmp_path / "Guitar, Loneliness and Blue Planet.pdf"
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    document.new_page()
    document.set_metadata({"title": "MyMusicSheet > Library", "author": ""})
    document.save(pdf_path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]

    metadata = detect_score_metadata(pdf_path)

    assert metadata == ScoreMetadata(title="Guitar, Loneliness and Blue Planet")


def test_apply_score_metadata_preserves_encoding_information() -> None:
    """Add title and composer while retaining HOMR identification details."""
    root = ET.fromstring(  # noqa: S314
        """<score-partwise><work><work-title/></work>
        <identification><encoding><software>homr</software></encoding></identification>
        <part-list/></score-partwise>"""
    )

    apply_score_metadata(
        root,
        ScoreMetadata(title="Wind Street", composer="Yukiko Isomura"),
    )

    assert root.findtext("./work/work-title") == "Wind Street"
    assert (
        root.findtext("./identification/creator[@type='composer']") == "Yukiko Isomura"
    )
    assert root.findtext("./identification/encoding/software") == "homr"


def test_composer_from_homr_title_recovers_composer_credit() -> None:
    """Interpret HOMR's compact composer credit without using it as a title."""
    root = ET.fromstring(  # noqa: S314
        "<score-partwise><work><work-title>Composedby otoha</work-title></work>"
        "</score-partwise>"
    )

    assert composer_from_homr_title(root) == "otoha"


def test_normalize_musicxml_timing_reorders_complete_staff_streams() -> None:
    """Repair bad interleaving without changing notes, durations, or slurs."""
    root = ET.fromstring(  # noqa: S314
        """<score-partwise><part id="P1"><measure number="10">
        <attributes><divisions>2</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
        <note><rest/><duration>4</duration><voice>1</voice><staff>1</staff>
        <notations><slur type="start"/></notations></note>
        <backup><duration>4</duration></backup>
        <note><rest/><duration>8</duration><voice>5</voice><staff>2</staff></note>
        <backup><duration>2</duration></backup>
        <note><rest/><duration>4</duration><voice>1</voice><staff>1</staff></note>
        </measure></part></score-partwise>"""
    )

    reordered, irregular = normalize_musicxml_timing(root)

    measure = root.find("./part/measure")
    assert measure is not None
    assert reordered == 1
    assert irregular == 0
    assert [child.tag for child in measure] == [
        "attributes",
        "note",
        "note",
        "backup",
        "note",
    ]
    assert measure.findtext("./backup/duration") == "8"
    assert len(measure.findall(".//slur")) == 1


def test_normalize_musicxml_timing_marks_overfull_final_measure_implicit() -> None:
    """Keep intentional cadenza-like ending notes in an irregular final bar."""
    root = ET.fromstring(  # noqa: S314
        """<score-partwise><part id="P1"><measure number="179">
        <attributes><divisions>2</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
        <note><rest/><duration>8</duration><voice>1</voice><staff>1</staff></note>
        <note><pitch><step>F</step><octave>5</octave></pitch>
        <duration>4</duration><voice>1</voice><staff>1</staff></note>
        <backup><duration>8</duration></backup>
        <note><rest/><duration>8</duration><voice>5</voice><staff>2</staff></note>
        <barline location="right"><bar-style>heavy-heavy</bar-style></barline>
        </measure></part></score-partwise>"""
    )

    reordered, irregular = normalize_musicxml_timing(root)

    measure = root.find("./part/measure")
    assert measure is not None
    assert reordered == 0
    assert irregular == 1
    assert measure.get("implicit") == "yes"
    assert len(measure.findall("./note")) == 3


def test_normalize_musicxml_timing_pads_short_secondary_voice() -> None:
    """Complete a short voice with forward time instead of adding a rest."""
    root = ET.fromstring(  # noqa: S314
        """<score-partwise><part id="P1"><measure number="87">
        <attributes><divisions>2</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
        <note><rest/><duration>8</duration><voice>1</voice><staff>1</staff></note>
        <backup><duration>8</duration></backup>
        <note><rest/><duration>2</duration><voice>2</voice><staff>1</staff></note>
        <note><rest/><duration>8</duration><voice>5</voice><staff>2</staff></note>
        </measure></part></score-partwise>"""
    )

    reordered, irregular = normalize_musicxml_timing(root)

    measure = root.find("./part/measure")
    assert measure is not None
    assert reordered == 1
    assert irregular == 0
    assert measure.findtext("./forward/duration") == "6"
    assert len(measure.findall("./note")) == 3


def test_normalize_musicxml_timing_marks_short_section_ending_implicit() -> None:
    """Accept a short measure ending a section before the next page."""
    root = ET.fromstring(  # noqa: S314
        """<score-partwise><part id="P1">
        <measure number="105"><attributes><divisions>2</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
        <note><rest/><duration>2</duration><voice>1</voice><staff>1</staff></note>
        <barline location="right"><bar-style>heavy-heavy</bar-style></barline>
        </measure>
        <measure number="106"><note><rest/><duration>8</duration>
        <voice>1</voice><staff>1</staff></note></measure>
        </part></score-partwise>"""
    )

    reordered, irregular = normalize_musicxml_timing(root)

    measures = root.findall("./part/measure")
    assert reordered == 0
    assert irregular == 1
    assert measures[0].get("implicit") == "yes"
    assert measures[1].get("implicit") is None
