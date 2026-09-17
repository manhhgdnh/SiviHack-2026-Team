"""Section parsing: every heading level, hierarchical ids, pseudo-heading and paragraph fallbacks."""

from pathlib import Path

from app.splitter import parse

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
RFP = (SAMPLES / "rfp_nordframe.md").read_text()
OVER = (SAMPLES / "response_4_overpromise.md").read_text()


def ids(doc):
    return [s.id for s in doc.sections]


def headers(doc):
    return [s.header for s in doc.sections]


def located(doc, quote) -> str:
    s = doc.locate(quote)
    assert s is not None, quote
    return s.id


def test_single_top_heading_is_the_title_and_numbering_starts_below_it():
    doc = parse(RFP)
    assert doc.mode == "headings"
    assert ids(doc) == ["§0", "§1", "§2", "§3", "§4", "§5"]
    assert headers(doc) == [
        "Request for Proposal — Warehouse Inventory Dashboard",
        "Background",
        "Requirements",
        "Budget",
        "Timeline",
        "Decision Date",
    ]
    # the title section keeps the front-matter lines as its body
    assert "NordFrame Logistics GmbH" in doc.sections[0].body
    assert "€80,000" in doc.sections[3].body and "€80,000" not in doc.sections[2].body


def test_nested_headings_get_dotted_ids_and_levels_may_skip():
    md = "# Title\n\n## A\na\n### A.1\na1\n### A.2\na2\n## B\nb\n#### B.deep\nd\n## C\nc"
    doc = parse(md)
    assert ids(doc) == ["§0", "§1", "§1.1", "§1.2", "§2", "§2.1", "§3"]
    assert doc.sections[5].header == "B.deep" and doc.sections[5].level == 4


def test_multiple_top_level_headings_number_from_the_top():
    md = "intro\n\n# One\nx\n## One.a\ny\n# Two\nz"
    doc = parse(md)
    assert ids(doc) == ["§0", "§1", "§1.1", "§2"]
    assert doc.sections[0].header == "preamble" and doc.sections[0].body == "intro"


def test_bold_lines_and_caps_lines_act_as_headings_when_there_are_none():
    md = (
        "Some intro.\n\n**Pricing**\nTotal is €50,000.\n\n"
        "TIMELINE AND MILESTONES\nWe deliver in 8 weeks.\n\n__Team__:\nThree people."
    )
    doc = parse(md)
    assert doc.mode == "pseudo"
    assert ids(doc) == ["§0", "§1", "§2", "§3"]
    assert headers(doc) == ["preamble", "Pricing", "TIMELINE AND MILESTONES", "Team"]
    assert "€50,000" in doc.sections[1].body and "8 weeks" in doc.sections[2].body


def test_plain_text_falls_back_to_paragraphs():
    md = "First paragraph here.\nStill first.\n\n\nSecond one.\n\nThird."
    doc = parse(md)
    assert doc.mode == "paragraphs"
    assert ids(doc) == ["¶1", "¶2", "¶3"]
    assert doc.sections[0].body == "First paragraph here.\nStill first."
    assert doc.sections[0].header.startswith("First paragraph")


def test_empty_document():
    doc = parse("  \n ")
    assert doc.mode == "empty" and doc.sections == [] and doc.outline().count == 0


def test_resolve_accepts_ids_headers_and_loose_labels():
    doc = parse(OVER)
    assert [s.header for s in doc.sections][1:] == [
        "Our Vision",
        "Proposed Solution",
        "Timeline",
        "Pricing",
        "Why Vantix",
    ]
    pricing = doc.sections[4]
    for label in [
        "§4",
        "4",
        "§4 Pricing",
        "Pricing",
        "pricing",
        "## Pricing",
        "Section 4",
        "PRICING:",
    ]:
        assert doc.resolve(label) is pricing, label
    assert doc.resolve("Timeline") is doc.sections[3]
    # header containment works both ways, but only for labels long enough to mean something
    assert doc.resolve("Proposed") is doc.sections[2]
    assert doc.resolve("nonsense") is None and doc.resolve(None) is None and doc.resolve("") is None


def test_locate_finds_the_section_holding_a_quote_across_wrapped_lines():
    doc = parse(RFP)
    assert located(doc, "no migration to a new database") == "§2"
    assert located(doc, "€80,000–€120,000 total, including first year of support.") == "§3"
    # the title's front matter belongs to §0
    assert located(doc, "NordFrame Logistics GmbH (fictional)") == "§0"
    assert doc.locate("The vendor guarantees 99.99% uptime") is None
    assert doc.locate("") is None


def test_outline_and_rendering_with_markers():
    doc = parse(OVER)
    out = doc.outline()
    assert out.count == 6 and out.sections[4].id == "§4" and out.sections[4].header == "Pricing"
    rendered = doc.render()
    assert "[§4 Pricing]\nTotal project cost:" in rendered
    assert rendered.index("[§1 Our Vision]") < rendered.index("[§2 Proposed Solution]")
