from pathlib import Path

import pytest
from csv_convert import convert_csv, CsvConvertError
from markdown_parser import parse_markdown

TEMPLATES = Path(__file__).resolve().parent.parent / "config" / "templates"


def test_convert_roundtrips_through_parser(tmp_path):
    csv = tmp_path / "in.csv"
    csv.write_text(
        "project_id,issue_type,component,summary,epic_key,story_points,description\n"
        "PROJ,story,Frontend,Login Form,PROJ-100,5,Log in with email\n"
        "PROJ,task,Backend,Auth Middleware,PROJ-100,3,Configure JWT\n",
        encoding="utf-8",
    )
    md = convert_csv(csv, TEMPLATES)
    assert not md.lstrip().startswith("---")  # no leading delimiter
    out = tmp_path / "out.md"
    out.write_text(md, encoding="utf-8")
    result = parse_markdown(out)  # convert output must parse
    assert [t.summary for t in result.tickets] == ["Login Form", "Auth Middleware"]
    assert "### Acceptance Criteria" in md  # story template body reused


def test_missing_required_column_fails(tmp_path):
    csv = tmp_path / "bad.csv"
    csv.write_text(
        "project_id,issue_type,summary\nPROJ,story,No Component\n", encoding="utf-8"
    )
    with pytest.raises(CsvConvertError) as exc:
        convert_csv(csv, TEMPLATES)
    assert any("component" in e for e in exc.value.errors)


def test_non_utf8_csv_fails_with_conversion_error(tmp_path):
    csv = tmp_path / "windows-1252.csv"
    csv.write_bytes(
        b"project_id,issue_type,component,summary\nPROJ,story,Frontend,Dash \x96\n"
    )

    with pytest.raises(CsvConvertError) as exc:
        convert_csv(csv, TEMPLATES)

    assert "not valid UTF-8" in exc.value.errors[0]


def test_quoted_multiline_description_keeps_line_break(tmp_path):
    csv = tmp_path / "multiline.csv"
    csv.write_text(
        "project_id,issue_type,component,summary,description\n"
        'PROJ,story,Frontend,Login Form,"First line\nSecond line"\n',
        encoding="utf-8",
    )

    markdown = convert_csv(csv, TEMPLATES)

    assert "First line\nSecond line" in markdown


def test_metadata_scalars_roundtrip_without_corruption(tmp_path):
    csv = tmp_path / "scalars.csv"
    csv.write_text(
        "project_id,issue_type,component,summary,custom_text\n"
        'PROJ,story,Mobile #1,Login Form,"Deploy: ""blue"" #1"\n',
        encoding="utf-8",
    )

    markdown = convert_csv(csv, TEMPLATES)
    out = tmp_path / "tickets.md"
    out.write_text(markdown, encoding="utf-8")
    ticket = parse_markdown(out).tickets[0]

    assert ticket.component == "Mobile #1"
    assert ticket.extra_fields["custom_text"] == 'Deploy: "blue" #1'


def test_surplus_csv_cells_are_rejected(tmp_path):
    csv = tmp_path / "surplus.csv"
    csv.write_text(
        "project_id,issue_type,component,summary\n"
        "PROJ,story,Frontend,Login Form,unexpected\n",
        encoding="utf-8",
    )

    with pytest.raises(CsvConvertError) as exc:
        convert_csv(csv, TEMPLATES)

    assert "more values than columns" in exc.value.errors[0]


def test_multiline_csv_summary_is_rejected(tmp_path):
    csv = tmp_path / "multiline-summary.csv"
    csv.write_text(
        "project_id,issue_type,component,summary\n"
        'PROJ,story,Frontend,"Login\nForm"\n',
        encoding="utf-8",
    )

    with pytest.raises(CsvConvertError) as exc:
        convert_csv(csv, TEMPLATES)

    assert "summary must be one line" in exc.value.errors[0]


def test_description_fails_if_custom_template_has_no_placeholder(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "story.md").write_text(
        "### Description\nCustom fixed text.\n", encoding="utf-8"
    )
    csv = tmp_path / "description.csv"
    csv.write_text(
        "project_id,issue_type,component,summary,description\n"
        "PROJ,story,Frontend,Login Form,Source description\n",
        encoding="utf-8",
    )

    with pytest.raises(CsvConvertError) as exc:
        convert_csv(csv, templates)

    assert "no TODO placeholder" in exc.value.errors[0]


def test_description_does_not_use_placeholder_from_later_template_section(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "story.md").write_text(
        "### Description\nFixed text.\n\n### Acceptance Criteria\n"
        "<!-- TODO: criteria -->\n",
        encoding="utf-8",
    )
    csv = tmp_path / "description.csv"
    csv.write_text(
        "project_id,issue_type,component,summary,description\n"
        "PROJ,story,Frontend,Login Form,Source description\n",
        encoding="utf-8",
    )

    with pytest.raises(CsvConvertError) as exc:
        convert_csv(csv, templates)

    assert "leading section" in exc.value.errors[0]
