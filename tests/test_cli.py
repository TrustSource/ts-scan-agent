from ts_scan_agent.cli import _parse_edited_proposal


def test_parses_clean_title_line():
    title, body = _parse_edited_proposal('Title: Add support for X\n\nSome body text.')
    assert title == 'Add support for X'
    assert body == 'Some body text.'


def test_tolerates_leading_whitespace_before_title_marker():
    title, body = _parse_edited_proposal(' Title: Add support for X\n\nBody.')
    assert title == 'Add support for X'
    assert body == 'Body.'


def test_tolerates_blank_lines_before_title_marker():
    title, body = _parse_edited_proposal('\n\nTitle: Add support for X\n\nBody.')
    assert title == 'Add support for X'
    assert body == 'Body.'


def test_falls_back_to_none_title_when_marker_missing_rather_than_leaking_into_body():
    title, body = _parse_edited_proposal('Just a rewritten body, no title line.')
    assert title is None
    assert body == 'Just a rewritten body, no title line.'


def test_falls_back_when_first_nonblank_line_is_not_a_title_line():
    edited = 'Some other first line\nTitle: This should NOT be picked up\n\nBody.'
    title, body = _parse_edited_proposal(edited)
    assert title is None
    assert body == edited
