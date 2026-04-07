import weasyprint
import sqlite3
import json
import argparse
import html
import re
import os
from pathlib import Path
from datetime import datetime, timedelta

class PDFCreator:
    def __init__(self):
        self.conn = None

    def connect_database(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        print(f"Połączono z bazą danych: {db_path}")

    def close_database(self):
        if getattr(self, 'conn', None):
            self.conn.close()

    def fetch_records(self, limit=None):
        cursor = self.conn.cursor()
        query = "SELECT * FROM CVAnalysisResults ORDER BY creation_date DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
        cursor.execute(query)
        return cursor.fetchall()

    def _parse_field_as_list(self, value):
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return list(value)
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return list(parsed.values())
        except Exception:
            pass
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(',') if p.strip()]
            return parts
        return [str(value)]

    def extract_json_from_text(self, text):
        if not text:
            return ''
        try:
            m = re.search(r'```json\s*({.*?})\s*```', text, re.DOTALL)
            if m:
                return m.group(1)
            m2 = re.search(r'({.*})', text, re.DOTALL)
            if m2:
                return m2.group(1)
        except Exception:
            pass
        return text

    def render_record(self, record):
        job_link_raw = record['job_link'] or ''
        job_link_html = f'<a href="{html.escape(job_link_raw)}">{html.escape(job_link_raw)}</a>' if job_link_raw else ''
        creation_date = record['creation_date'] or ''
        score = record['score'] if record['score'] is not None else 'N/A'
        summary = html.escape(record['summary'] or '')

        strengths = self._parse_field_as_list(record['strengths'])
        weaknesses = self._parse_field_as_list(record['weaknesses'])
        matched = self._parse_field_as_list(record['matched_skills'])
        missing = self._parse_field_as_list(record['missing_skills'])

        strengths_html = ''.join(f'<li>{html.escape(s)}</li>' for s in strengths) or '<li>Brak</li>'
        weaknesses_html = ''.join(f'<li>{html.escape(w)}</li>' for w in weaknesses) or '<li>Brak</li>'
        matched_html = ''.join(f'<li>{html.escape(m)}</li>' for m in matched) or '<li>Brak</li>'
        missing_html = ''.join(f'<li>{html.escape(m)}</li>' for m in missing) or '<li>Brak</li>'

        page_html = f"""
        <div class="page card">
          <div class="header">
            <div class="left">
                            <div class="kicker">Raport dopasowania CV</div>
                            <div class="job">{job_link_html or 'Brak linku oferty'}</div>
                            <div class="meta"><span class="date">Data analizy: {creation_date}</span></div>
            </div>
            <div class="right">
              <div class="score-badge">{score}/10</div>
            </div>
          </div>
                    <div class="analysis-content-group">
                        <h2>Podsumowanie</h2>
                        <div class="summary-box">{summary or 'Brak podsumowania.'}</div>

                        <div class="columns">
                            <div class="col">
                                <div class="section-card">
                                    <h3>Mocne strony</h3>
                                    <ul class="list">{strengths_html}</ul>
                                </div>
                                <div class="section-card">
                                    <h3>Słabsze obszary</h3>
                                    <ul class="list">{weaknesses_html}</ul>
                                </div>
                            </div>
                            <div class="col">
                                <div class="section-card">
                                    <h3>Pasujące umiejętności</h3>
                                    <ul class="list">{matched_html}</ul>
                                </div>
                                <div class="section-card">
                                    <h3>Brakujące umiejętności</h3>
                                    <ul class="list">{missing_html}</ul>
                                </div>
                            </div>
                        </div>
          </div>
        </div>
        """

        return page_html

    def build_full_html(self, records):
        gendate = datetime.now().strftime('%Y-%m-%d %H:%M')
        css = f'''
        @page {{ size: A4; margin: 24mm }}
        @page {{
          @bottom-center {{
            content: "Strona " counter(page) " / " counter(pages) " — Wygenerowano: {gendate}";
            font-size: 10px; color: #555;
          }}
        }}
                body {{ font-family: DejaVu Sans, Arial, sans-serif; color: #222; -webkit-font-smoothing:antialiased; font-size: 12px }}
                .card {{ page-break-after: always; page-break-inside: avoid; break-inside: avoid-page; border-left:6px solid #0b63c6; padding:16px 16px 22px 16px; margin-bottom:10px; background:#fff }}
                .card:last-child {{ page-break-after: auto }}
        .header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:14px; border-bottom:1px solid #e8edf3; padding-bottom:10px }}
        .kicker {{ font-size:11px; text-transform:uppercase; letter-spacing:.4px; color:#6b7785; margin-bottom:6px }}
        .left .job {{ font-size:14px; color:#0b63c6; font-weight:700; text-decoration:none; line-height:1.35 }}
        .left .job a {{ color: #0b63c6; text-decoration: none }}
        .meta {{ font-size:11px; color:#666; margin-top:6px }}
                .score-badge {{ background:linear-gradient(180deg,#12a0ff,#005ec2); color:#fff; padding:10px 14px; border-radius:10px; font-weight:700; font-size:14px; white-space: nowrap }}
                .analysis-content-group {{ page-break-inside: avoid; break-inside: avoid-page }}
                h2 {{ margin:8px 0 8px 0; font-size:16px; color:#222; page-break-after: avoid }}
                h3 {{ margin:0 0 6px 0; font-size:13px; color:#1f2a37; page-break-after: avoid }}
                .summary-box {{ font-size:12px; margin-bottom:8px; color:#2f3a46; background:#f7faff; border:1px solid #e5eef9; border-radius:8px; padding:8px 10px; line-height:1.4; page-break-inside: avoid; break-inside: avoid-page }}
                .columns {{ display: table; width: 100%; table-layout: fixed; border-spacing: 10px 0; page-break-inside: avoid; break-inside: avoid-page }}
                .col {{ display: table-cell; vertical-align: top }}
                .section-card {{ border:1px solid #e8edf3; border-radius:8px; padding:8px 10px; margin-bottom:10px; background:#fcfdff; page-break-inside: avoid; break-inside: avoid-page }}
        .list {{ margin:6px 0 0 18px; padding:0 }}
                .list li {{ margin-bottom:4px; font-size:11px; line-height:1.3; page-break-inside: avoid }}
        a {{ color: #0b63c6 }}
        '''

        pages = [self.render_record(r) for r in records]
        html_doc = f"""
        <html>
        <head>
          <meta charset="utf-8" />
          <style>{css}</style>
        </head>
        <body>
          {''.join(pages)}
        </body>
        </html>
        """
        return html_doc

    def fetch_records_between(self, start_date, end_date, limit=None):
        cursor = self.conn.cursor()
        query = "SELECT * FROM CVAnalysisResults WHERE date(creation_date) BETWEEN date(?) AND date(?) ORDER BY creation_date DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
        cursor.execute(query, (start_date, end_date))
        return cursor.fetchall()

    def create_pdf_from_db(self, db_path, output_path, limit=None, start_date=None, end_date=None, last_n_days=None):
        self.connect_database(db_path)
        try:
            # wybór rekordów wg podanego zakresu
            if last_n_days is not None:
                start = (datetime.now() - timedelta(days=int(last_n_days))).date().isoformat()
                end = datetime.now().date().isoformat()
                records = self.fetch_records_between(start, end, limit)
            elif start_date and end_date:
                records = self.fetch_records_between(start_date, end_date, limit)
            elif start_date and not end_date:
                records = self.fetch_records_between(start_date, start_date, limit)
            else:
                records = self.fetch_records(limit)

            if not records:
                print('Brak rekordów w bazie do zapisania.')
                return

            # upewnij się, że katalog docelowy istnieje
            out_dir = Path(output_path).parent
            out_dir.mkdir(parents=True, exist_ok=True)

            full_html = self.build_full_html(records)
            weasyprint.HTML(string=full_html).write_pdf(output_path)
            print(f'PDF zapisany do: {output_path} (rekordów: {len(records)})')
        finally:
            self.close_database()


def main():
    parser = argparse.ArgumentParser(description='Generuj PDF z bazy cv_analysis.db — 1 rekord = 1 strona')
    parser.add_argument('--db', default='cv_analysis.db', help='ścieżka do bazy danych')
    parser.add_argument('--limit', type=int, default=None, help='maksymalna liczba rekordów (opcjonalnie)')
    args = parser.parse_args()

    creator = PDFCreator()

    # Interaktywne menu wyboru okresu
    print('\nWybierz okres analiz do zapisania w PDF:')
    print('1) Oferty z dzisiaj')
    print('2) Oferty z przedziału dat (YYYY-MM-DD)')
    print('3) Ostatnie N dni')
    print('4) Wszystkie')
    choice = input('Wybór (1/2/3/4): ').strip()

    start_date = end_date = None
    last_n = None

    if choice == '1':
        start_date = end_date = datetime.now().date().isoformat()
    elif choice == '2':
        start_date = input('Data początkowa (YYYY-MM-DD): ').strip()
        end_date = input('Data końcowa (YYYY-MM-DD): ').strip()
    elif choice == '3':
        last_n = input('Podaj liczbę dni (np. 7): ').strip()
        try:
            last_n = int(last_n)
        except Exception:
            print('Nieprawidłowa liczba dni. Kończę.')
            return
    else:
        # wybierz wszystkie
        pass

    # przygotuj katalog i nazwę pliku z datą wywołania
    out_dir = Path('analyses_pdf')
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_file = out_dir / f'analyses_{timestamp}.pdf'

    creator.create_pdf_from_db(args.db, str(out_file), args.limit, start_date=start_date, end_date=end_date, last_n_days=last_n)


if __name__ == '__main__':
    main()
