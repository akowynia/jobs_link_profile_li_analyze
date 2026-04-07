import json

import main as main_module
from main import MainJobAnalyzer


def test_analyze_with_ollama_uses_mocked_response(tmp_path, mocker):
    analyzer = MainJobAnalyzer(
        db_path=str(tmp_path / 'jobs.db'),
        analysis_db_path=str(tmp_path / 'analysis.db'),
        output_file=str(tmp_path / 'output.txt'),
        analysis_file='test.txt',
    )

    mocked_chat = mocker.patch.object(
        main_module.ollama,
        'chat',
        return_value={'message': {'content': '{"score": 9, "summary": "ok", "strengths": [], "weaknesses": [], "key_skills_match": {"matched": [], "missing": []}}'}},
    )

    result = analyzer.analyze_with_ollama('cv', 'job')
    assert json.loads(result)['score'] == 9
    mocked_chat.assert_called_once()


def test_save_analysis_to_db_persists_score(tmp_path):
    analyzer = MainJobAnalyzer(
        db_path=str(tmp_path / 'jobs.db'),
        analysis_db_path=str(tmp_path / 'analysis.db'),
        output_file=str(tmp_path / 'output.txt'),
        analysis_file='test.txt',
    )

    content = '{"score": 8, "summary": "dopasowanie", "strengths": ["python"], "weaknesses": ["aws"], "key_skills_match": {"matched": ["python"], "missing": ["aws"]}}'
    analyzer.save_analysis_to_db(content, 'https://example.com/oferta', 'cv')

    rows = analyzer.get_all_analysis_results(limit=1)
    assert len(rows) == 1
    assert rows[0]['score'] == 8


def test_process_website_strips_html_tags(tmp_path, mocker):
    analyzer = MainJobAnalyzer(
        db_path=str(tmp_path / 'jobs.db'),
        analysis_db_path=str(tmp_path / 'analysis.db'),
        output_file=str(tmp_path / 'output.txt'),
        analysis_file='test.txt',
    )

    class DummyResponse:
        text = '<html><body><script>x</script><h1>Oferta</h1><p>Python Developer</p></body></html>'

        def raise_for_status(self):
            return None

    class DummyScraper:
        def get(self, _):
            return DummyResponse()

    mocker.patch.object(main_module.cloudscraper, 'create_scraper', return_value=DummyScraper())

    text = analyzer.process_website('https://example.com')
    assert 'Python Developer' in text
    assert 'script' not in text.lower()
