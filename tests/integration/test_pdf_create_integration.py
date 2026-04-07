from pathlib import Path

from pdf_create import PDFCreator


def _init_db(db_path: Path):
    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        '''
        CREATE TABLE CVAnalysisResults (
            analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_link TEXT NOT NULL,
            creation_date TEXT NOT NULL,
            analysis_content TEXT NOT NULL,
            score INTEGER,
            cv_content_hash TEXT,
            strengths TEXT,
            weaknesses TEXT,
            matched_skills TEXT,
            missing_skills TEXT,
            summary TEXT
        )
        '''
    )
    cur.execute(
        '''
        INSERT INTO CVAnalysisResults (
            job_link, creation_date, analysis_content, score, cv_content_hash,
            strengths, weaknesses, matched_skills, missing_skills, summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            'https://example.com/oferta',
            '2026-04-07T10:00:00',
            '{"score": 8}',
            8,
            'hash',
            '["python", "sql"]',
            '["aws"]',
            '["python"]',
            '["aws"]',
            'Solidny profil backend',
        ),
    )
    conn.commit()
    conn.close()


def test_create_pdf_from_db_calls_weasyprint(tmp_path, mocker):
    db_path = tmp_path / 'analysis.db'
    out_path = tmp_path / 'out.pdf'
    _init_db(db_path)

    creator = PDFCreator()

    fake_html = mocker.Mock()
    fake_html.write_pdf = mocker.Mock()
    html_ctor = mocker.patch('pdf_create.weasyprint.HTML', return_value=fake_html)

    creator.create_pdf_from_db(str(db_path), str(out_path), limit=1)

    html_ctor.assert_called_once()
    fake_html.write_pdf.assert_called_once_with(str(out_path))


def test_render_record_contains_sections():
    creator = PDFCreator()
    record = {
        'job_link': 'https://example.com/oferta',
        'creation_date': '2026-04-07T10:00:00',
        'score': 8,
        'summary': 'Podsumowanie testowe',
        'strengths': '["python"]',
        'weaknesses': '["aws"]',
        'matched_skills': '["python"]',
        'missing_skills': '["aws"]',
    }

    html = creator.render_record(record)

    assert 'Podsumowanie' in html
    assert 'Mocne strony' in html
    assert 'Słabsze obszary' in html
    assert 'Pasujące umiejętności' in html
    assert 'Brakujące umiejętności' in html
