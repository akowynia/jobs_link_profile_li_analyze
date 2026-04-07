from analysis_utils import extract_json_from_text


def test_extract_json_from_markdown_block():
    content = 'Wynik\n```json\n{"score": 8, "summary": "ok"}\n```\nkoniec'
    assert extract_json_from_text(content) == '{"score": 8, "summary": "ok"}'


def test_extract_json_from_plain_text():
    content = 'abc {"score": 7, "summary": "fit"} xyz'
    assert extract_json_from_text(content) == '{"score": 7, "summary": "fit"}'


def test_extract_json_returns_original_when_not_found():
    content = 'brak json tutaj'
    assert extract_json_from_text(content) == content
