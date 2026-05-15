import sqlite3
import json
import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path
import cloudscraper
import bs4
import ollama
import os
import argparse
from analysis_utils import extract_json_from_text, safe_parse_json
import time


class MainJobAnalyzer:
    def __init__(self, db_path='discord_bot.db', analysis_db_path='cv_analysis.db', output_file='output.txt', analysis_file=None, model_name: str | None = None):
        self.db_path = db_path  # Baza danych dla ofert pracy
        self.analysis_db_path = analysis_db_path  # Osobna baza danych dla analiz CV
        self.output_file = output_file
        # Tworzenie nazwy pliku z datą z chwili uruchomienia
        if analysis_file is None:
            current_date = datetime.now().strftime('%Y-%m-%d')
            filename = f'analiza_{current_date}.txt'
            analyses_dir = Path('analyses_txt')
            analyses_dir.mkdir(parents=True, exist_ok=True)
            self.analysis_file = analyses_dir / filename
        else:
            # jeśli podano ścieżkę lub nazwę pliku, zapisz ją w folderze analyses_txt
            analyses_dir = Path('analyses_txt')
            analyses_dir.mkdir(parents=True, exist_ok=True)
            self.analysis_file = analyses_dir / analysis_file
        self.conn = None
        # Inicjalizacja bazy danych dla analiz
        self.init_analysis_database()
        # MIEJSCE NA INSTRUKCJE 
        self.ollama_instruction = """
Porównaj poniższe CV z opisem oferty pracy.

CV:
{cv_content}

Oferta pracy:
{job_description}

Odpowiedz WYŁĄCZNIE jednym obiektem JSON zgodnym z podanym schematem. Nie dodawaj żadnego tekstu, komentarzy, bloków markdown ani wyjaśnień.
"""

        self.system_prompt = (
            'Jesteś precyzyjnym asystentem analitycznym. '
            'Odpowiadasz WYŁĄCZNIE poprawnym, surowym obiektem JSON — bez bloków markdown, '
            'bez tekstu przed/po, bez komentarzy.\n\n'
            'Wymagany schemat odpowiedzi:\n'
            '{\n'
            '  "score": <int 1-10>,\n'
            '  "strengths": ["string", ...],\n'
            '  "weaknesses": ["string", ...],\n'
            '  "key_skills_match": {\n'
            '    "matched": ["string", ...],\n'
            '    "missing": ["string", ...]\n'
            '  },\n'
            '  "summary": "string"\n'
            '}\n\n'
            'Zasady:\n'
            '- score: ocena dopasowania 1-10 (liczba całkowita)\n'
            '- Skup się na konkretach: technologie, doświadczenie, certyfikaty\n'
            '- Wykryj wymagane języki w ofercie. Jeśli CV nie zawiera wymaganego języka, '
            'dodaj go do missing i obniż ocenę o 2 pkt za każdy brakujący (min. 1)\n'
            '- UŻYWAJ POPRAWNEGO JSON: używaj PODWÓJNYCH cudzysłowów (") dla kluczy i wartości tekstowych.\n'
            '- Zwracaj WSZYSTKIE pola z wzoru. Jeśli nie ma danych, użyj pustych list [] lub pustego stringa "" dla "summary".\n'
            '- Twoja odpowiedź to WYŁĄCZNIE obiekt JSON, nic więcej'
        )

        # Model Ollama — można przekazać przez parametr konstruktora, opcję CLI --model
        # lub zmienną środowiskową OLLAMA_MODEL. Domyślnie: 'ministral-3:8b'.
        env_model = os.environ.get('OLLAMA_MODEL')
        self.model_name = model_name or env_model or 'ministral-3:8b'

    def process_website(self, website):
        response = ""
        try:
            # Sprawdzenie, czy adres URL zaczyna się od http:// lub https://
            if not website.startswith(('http://', 'https://')):
                print(
                    "Niepoprawny adres URL. Proszę podać adres zaczynający się od http:// lub https://")
                return
            if website.startswith('https://czyjesteldorado.pl/'):
                print("pomijam stronę czyjesteldorado.pl")
                return 
            # Pobranie treści strony
            scraper = cloudscraper.create_scraper()
            response = scraper.get(website)
            response.raise_for_status()
        except Exception as e:
            print(f"Błąd podczas pobierania strony: {e}")
            return

        html = response.text or ''

        # Jeśli strona to komunikat o konieczności zaktualizowania przeglądarki
        # lub inny komunikat blokujący (JS, weryfikacja), spróbuj wyrenderować ją
        # przy pomocy Playwright. Jeśli brak fallbacku, pomiń stronę.
        if self._is_browser_update_page(html):
            print(f"[INFO] Strona wygląda na komunikat o aktualizacji przeglądarki — próbuję wyrenderować: {website}")
            rendered = self._render_with_playwright(website)
            if not rendered:
                print(f"[WARN] Nie udało się wyrenderować strony — pomijam: {website}")
                return
            html = rendered

        # Parsowanie HTML
        content = bs4.BeautifulSoup(html, features="html.parser")

        # Usuwanie niepotrzebnych elementów
        for tag in content(['script', 'style', 'nav', 'footer', 'header', 'noscript', 'iframe']):
            tag.decompose()

        # Wyciągnięcie czystego tekstu
        text_content = content.get_text(separator=' ', strip=True)

        # Usuwanie nadmiarowych białych znaków
        text_content = ' '.join(text_content.split())

        # Pomijaj bardzo krótkie strony
        if len(text_content) < 100:
            print(f"[WARN] Strona zawiera za mało treści: {len(text_content)} znaków — pomijam: {website}")
            return

        return text_content

    def _is_browser_update_page(self, html: str) -> bool:
        """Heurystyka wykrywająca komunikaty o aktualizacji przeglądarki / blokady JS."""
        if not html:
            return False

        lower = html.lower()
        phrases = (
            'update your browser',
            'please update your browser',
            'upgrade your browser',
            'browser not supported',
            'unsupported browser',
            'please enable javascript',
            'enable javascript',
            'please verify you are a human',
            'verify you are a human',
            'access denied',
            'zaktualizuj przegl',
            'zaktualizuj przeglądarkę',
            'włącz javascript',
        )

        for p in phrases:
            if p in lower:
                return True

        return False

    def _render_with_playwright(self, url: str, timeout: int = 30000) -> str | None:
        """Spróbuj wyrenderować stronę przy użyciu Playwright i zwróć HTML.

        Zwraca zawartość HTML lub None jeśli Playwright nie jest dostępny lub
        renderowanie się nie powiedzie.
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        except Exception:
            print("[INFO] Playwright nie jest zainstalowany. Zainstaluj: pip install playwright && playwright install")
            return None

        UA = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        )

        def _auto_scroll(page):
            page.evaluate("""
                async () => {
                    const distance = 800;
                    const delay = (ms) => new Promise(r => setTimeout(r, ms));
                    for (let i = 0; i < 20; i++) {
                        window.scrollBy(0, distance);
                        await delay(300);
                    }
                }
            """)

        attempts = 2
        for attempt in range(1, attempts + 1):
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                    context = browser.new_context(user_agent=UA, viewport={'width': 1280, 'height': 800})
                    page = context.new_page()
                    page.goto(url, timeout=timeout, wait_until='domcontentloaded')
                    try:
                        _auto_scroll(page)
                    except Exception:
                        pass
                    try:
                        page.wait_for_load_state('networkidle', timeout=5000)
                    except Exception:
                        pass
                    content = page.content()
                    text = bs4.BeautifulSoup(content, features="html.parser").get_text(separator=' ', strip=True)
                    if len(text) < 100:
                        print(f"[INFO] Playwright render returned too little text ({len(text)} chars) on attempt {attempt}")
                        browser.close()
                        if attempt < attempts:
                            time.sleep(1)
                            continue
                        return None
                    browser.close()
                    return content
            except PlaywrightTimeout as e:
                print(f"[WARN] Playwright timeout on attempt {attempt}: {e}")
                if attempt == attempts:
                    return None
                time.sleep(1)
                continue
            except Exception as e:
                print(f"[WARN] Playwright render failed on attempt {attempt}: {e}")
                if attempt == attempts:
                    return None
                time.sleep(1)
                continue

    def _is_browser_update_page(self, html: str) -> bool:
        """Heurystyka wykrywająca komunikaty o aktualizacji przeglądarki / blokady JS."""
        if not html:
            return False

        lower = html.lower()
        phrases = (
            'update your browser',
            'please update your browser',
            'upgrade your browser',
            'browser not supported',
            'unsupported browser',
            'please enable javascript',
            'enable javascript',
            'please verify you are a human',
            'verify you are a human',
            'access denied',
            'zaktualizuj przegl',
            'zaktualizuj przeglądarkę',
            'włącz javascript',
        )

        for p in phrases:
            if p in lower:
                return True

        return False

    def _get_manual_text_input(self):
        """Pomocnicza metoda do wczytywania wieloliniowego tekstu od użytkownika."""
        print("\nWklej treść oferty pracy poniżej.")
        print("Aby zakończyć, naciśnij Enter dwa razy (pusta linia) lub Ctrl+D.")
        lines = []
        while True:
            try:
                line = input()
                if not line and lines and not lines[-1]: # Dwie puste linie
                    break
                if not line and not lines: # Pusta linia na początku - czekaj dalej lub wyjdź jeśli chcesz
                    # Pozwólmy na jedną pustą linię, ale dwie kończą
                    lines.append(line)
                    continue
                if not line: # Pojedyncza pusta linia
                    lines.append(line)
                    # Sprawdź czy to już koniec (użytkownik może chcieć zakończyć)
                    # Ale lepiej czytać do momentu aż faktycznie skończy.
                    # Zmieńmy logikę: Czytaj aż do pustej linii jeśli coś już jest, 
                    # albo po prostu poinformuj użytkownika.
                    print("(Wczytano pustą linię. Naciśnij Enter jeszcze raz, aby zakończyć, lub kontynuuj wklejanie)")
                    second_line = input()
                    if not second_line:
                        break
                    else:
                        lines.append(second_line)
                        continue
                lines.append(line)
            except EOFError:
                break
        
        content = "\n".join(lines).strip()
        return content

    def connect_db(self):
        """Połącz z bazą danych"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        return self.conn.cursor()

    def init_analysis_database(self):
        """Inicjalizuj tabelę do przechowywania analiz CV"""
        # Połącz z osobną bazą danych dla analiz
        conn = sqlite3.connect(self.analysis_db_path)
        cursor = conn.cursor()
        
        # Tworzenie tabeli na wyniki analiz CV
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS CVAnalysisResults (
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
        ''')
        
        conn.commit()
        conn.close()
        print(f"Baza danych analiz CV została zainicjalizowana: {self.analysis_db_path}")

    def get_today_offers(self):
        """Pobierz oferty z dzisiejszą datą"""
        cursor = self.connect_db()
        today = date.today().isoformat()

        query = """
        SELECT * FROM JobsInformation 
        WHERE date(currentTime) = date(?)
        ORDER BY currentTime DESC
        """

        cursor.execute(query, (today,))
        offers = cursor.fetchall()
        return offers

    def get_between_dates_offers(self, start_date, end_date):
        """Pobierz oferty między dwoma datami"""
        cursor = self.connect_db()

        query = """
        SELECT * FROM JobsInformation 
        WHERE date(currentTime) BETWEEN date(?) AND date(?)
        ORDER BY currentTime DESC
        """

        cursor.execute(query, (start_date, end_date))
        offers = cursor.fetchall()
        return offers

    def read_output_file(self):
        """Wczytaj zawartość pliku output.txt"""
        output_path = Path(self.output_file)
        if output_path.exists():
            with open(output_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def return_job_links(self):
        """Wyświetl linki ofert pracy z dzisiejszą datą"""
        offers = self.get_today_offers()

        print(f"\n{'='*60}")
        print(f"Oferty pracy z dnia: {date.today().strftime('%Y-%m-%d')}")
        print(f"Liczba ofert: {len(offers)}")
        print(f"{'='*60}\n")

        if not offers:
            print("Brak ofert na dzisiejszy dzień.")
            return []
        checked_offers = []
        for offer in offers:
            if self.check_link_in_database_cv_analysis(offer['linkOffer']):
                print(f"Oferta {offer['linkOffer']} została już przeanalizowana. Pomijam.")
            else:
                checked_offers.append(offer)

        # Jeśli brak nieprzeanalizowanych ofert — zwróć pustą listę
        if not checked_offers:
            print("Brak nieprzeanalizowanych ofert do analizy.")
            return []

        print(f"Liczba nieprzeanalizowanych ofert: {len(checked_offers)}")
        # Zwróć tylko linki nieprzeanalizowanych ofert
        link_offers = [offer['linkOffer'] for offer in checked_offers]
        return link_offers

    def return_job_links_between_dates(self, start_date, end_date):
        """Wyświetl linki ofert pracy z określonego przedziału czasowego"""
        offers = self.get_between_dates_offers(start_date, end_date)

        print(f"\n{'='*60}")
        print(f"Oferty pracy z okresu: {start_date} - {end_date}")
        print(f"Liczba ofert: {len(offers)}")
        print(f"{'='*60}\n")

        if not offers:
            print(f"Brak ofert w okresie {start_date} - {end_date}.")
            return []
        checked_offers = []
        for offer in offers:
            if self.check_link_in_database_cv_analysis(offer['linkOffer']):
                print(f"Oferta {offer['linkOffer']} została już przeanalizowana. Pomijam.")
            else:
                checked_offers.append(offer)

        # Jeśli brak nieprzeanalizowanych ofert — zwróć pustą listę
        if not checked_offers:
            print(f"Brak nieprzeanalizowanych ofert w okresie {start_date} - {end_date}.")
            return []

        print(f"Liczba nieprzeanalizowanych ofert: {len(checked_offers)}")
        # Zwróć tylko linki nieprzeanalizowanych ofert
        link_offers = [offer['linkOffer'] for offer in checked_offers]
        return link_offers

    def close(self):
        """Zamknij połączenie z bazą danych"""
        if self.conn:
            self.conn.close()

    def process_offers(self, link_offers, cv_content):
        """Przetwarza listę ofert i analizuje dopasowanie do CV"""
        for link in link_offers:
            print(f"\nPrzetwarzam ofertę: {link}")

            # Pobierz treść oferty
            job_description = self.process_website(link)

            if not job_description:
                print(f"Nie udało się pobrać treści oferty: {link}")
                choice = input("Czy chcesz wkleić tekst oferty ręcznie? (t/N): ").strip().lower()
                if choice == 't':
                    job_description = self._get_manual_text_input()
                
                if not job_description:
                    print(f"Pomijam ofertę: {link}")
                    continue

            # Analizuj dopasowanie
            print("Analizuję dopasowanie...")
            analysis_result = self.analyze_with_ollama(cv_content, job_description)

            if analysis_result:
                # Zapisz analizę (przekaż również CV content)
                self.save_analysis(analysis_result, link, cv_content)
                print("Analiza ukończona!")
            else:
                print("Nie udało się przeprowadzić analizy.")

    def run_between_dates_offers(self, start_date, end_date):
        """Uruchom analizę dla ofert z określonego przedziału czasowego"""
        try:
            # Wczytaj CV z output.txt
            cv_content = self.read_output_file()
            if not cv_content:
                print("Nie znaleziono pliku output.txt z CV!")
                return

            # Wyświetl linki ofert z przedziału czasowego
            link_offers = self.return_job_links_between_dates(start_date, end_date)

            if not link_offers:
                return

            # Przetwórz oferty
            self.process_offers(link_offers, cv_content)

        except Exception as e:
            print(f"Błąd: {e}")
        finally:
            self.close()

    @staticmethod
    def _is_valid_analysis_json(obj) -> bool:
        """Sprawdza czy obiekt JSON ma wymagany schemat analizy CV."""
        if not isinstance(obj, dict):
            return False
        # wymagane pola i typy
        if 'score' not in obj or not isinstance(obj.get('score'), int):
            return False
        if 'strengths' not in obj or not isinstance(obj.get('strengths'), list):
            return False
        if 'weaknesses' not in obj or not isinstance(obj.get('weaknesses'), list):
            return False
        ksm = obj.get('key_skills_match')
        if not isinstance(ksm, dict):
            return False
        if 'matched' not in ksm or not isinstance(ksm.get('matched'), list):
            return False
        if 'missing' not in ksm or not isinstance(ksm.get('missing'), list):
            return False
        if 'summary' not in obj or not isinstance(obj.get('summary'), str):
            return False
        return True

    def analyze_with_ollama(self, cv_content, job_description):
        """Analizuj dopasowanie CV do oferty za pomocą Ollama.

        Jeśli otrzymany tekst nie zawiera poprawnego JSON zgodnego ze schematem,
        spróbuj wykonać analizę ponownie (retry) z informacją o błędzie.
        Zwraca znormalizowany JSON string lub None jeśli się nie uda."""

        prompt = self.ollama_instruction.format(
            cv_content=cv_content,
            job_description=job_description
        )

        max_attempts = 3
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                messages = [
                    {'role': 'system', 'content': self.system_prompt},
                    {'role': 'user', 'content': prompt}
                ]

                # W retry: dodaj informację o poprzednim błędzie
                if last_error and attempt > 1:
                    messages.append({
                        'role': 'user',
                        'content': (
                            f'Poprzednia odpowiedź była niepoprawna: {last_error}. '
                            f'Odpowiedz WYŁĄCZNIE poprawnym obiektem JSON zgodnym ze schematem.'
                        )
                    })

                response = ollama.chat(
                    model=self.model_name,
                    messages=messages,
                    format='json'
                )

                raw = response['message']['content']

                # Parsowanie z naprawą typowych błędów
                parsed = safe_parse_json(raw)

                if parsed and self._is_valid_analysis_json(parsed):
                    if attempt > 1:
                        print(f"Poprawny JSON otrzymany po {attempt} próbach.")
                    # Zwróć znormalizowany JSON (nie surową odpowiedź)
                    return json.dumps(parsed, ensure_ascii=False, indent=2)
                else:
                    missing_fields = []
                    if parsed:
                        for field in ['score', 'strengths', 'weaknesses', 'key_skills_match', 'summary']:
                            if field not in parsed:
                                missing_fields.append(field)
                    if missing_fields:
                        parsed_str = json.dumps(parsed, ensure_ascii=False)
                        last_error = (
                            f"Brak wymaganych pól: {', '.join(missing_fields)}. "
                            f"Otrzymany JSON: {parsed_str}. "
                            "Proszę zwrócić WYŁĄCZNIE kompletny obiekt JSON zgodny ze schematem; "
                            "jeśli brak danych, ustaw puste listy [] lub pusty string dla 'summary'."
                        )
                    else:
                        last_error = "Odpowiedź nie jest poprawnym obiektem JSON lub brak wymaganej struktury"
                    print(f"Otrzymany JSON niezgodny ze schematem (próba {attempt}): {last_error}")

            except Exception as e:
                last_error = str(e)
                print(f"Błąd podczas analizy z Ollama (próba {attempt}): {e}")

            # Pauza przed kolejną próbą
            if attempt < max_attempts:
                time.sleep(1)

        # Wyczerpano próby — NIE zapisuj śmieciowego rekordu
        print(f"BŁĄD: Po {max_attempts} próbach nie uzyskano poprawnego JSON-a. Rekord nie zostanie zapisany.")
        return None

    def save_analysis(self, content, job_link, cv_content=None):
        """Zapisz analizę do pliku i bazy danych"""
        try:
            # Zapisz do pliku
            with open(self.analysis_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"Link oferty: {job_link}\n")
                f.write(
                    f"Data analizy: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"{'='*80}\n")
                f.write(content)
                f.write(f"\n{'='*80}\n\n")
            print(f"Analiza zapisana do {self.analysis_file}")
            
            # Zapisz do bazy danych
            self.save_analysis_to_db(content, job_link, cv_content)
            
        except Exception as e:
            print(f"Błąd podczas zapisywania analizy: {e}")

    def extract_json_from_text(self, text):
        """Wyciągnij JSON z tekstu który może zawierać dodatkowy tekst"""
        return extract_json_from_text(text)

    def save_analysis_to_db(self, analysis_content, job_link, cv_content=None):
        """Zapisz wynik analizy do bazy danych"""
        try:
            # Połącz z osobną bazą danych dla analiz
            conn = sqlite3.connect(self.analysis_db_path)
            cursor = conn.cursor()
            
            # Parsowanie JSON z analizy (z naprawą typowych błędów)
            analysis_json = safe_parse_json(analysis_content)
            
            if not analysis_json or not isinstance(analysis_json.get('score'), int):
                print(f"[WARN] Pomijam zapis do DB — niepoprawny JSON dla: {job_link}")
                return
            
            score = analysis_json.get('score')
            strengths = json.dumps(analysis_json.get('strengths', []), ensure_ascii=False)
            weaknesses = json.dumps(analysis_json.get('weaknesses', []), ensure_ascii=False)
            
            key_skills_match = analysis_json.get('key_skills_match', {})
            matched_skills = json.dumps(key_skills_match.get('matched', []), ensure_ascii=False)
            missing_skills = json.dumps(key_skills_match.get('missing', []), ensure_ascii=False)
            
            summary = analysis_json.get('summary', '')
            print(f"Parsowanie JSON udane - ocena: {score}")
            
            # Hash CV dla identyfikacji
            cv_hash = None
            if cv_content:
                cv_hash = hashlib.md5(cv_content.encode('utf-8')).hexdigest()[:16]
            
            # Wstawienie do bazy danych
            cursor.execute('''
                INSERT INTO CVAnalysisResults 
                (job_link, creation_date, analysis_content, score, cv_content_hash, 
                 strengths, weaknesses, matched_skills, missing_skills, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job_link,
                datetime.now().isoformat(),
                analysis_content,
                score,
                cv_hash,
                strengths,
                weaknesses,
                matched_skills,
                missing_skills,
                summary
            ))
            
            conn.commit()
            print(f"Analiza zapisana do bazy danych: {self.analysis_db_path}")
            
        except Exception as e:
            print(f"Błąd podczas zapisywania do bazy danych: {e}")
        finally:
            if conn:
                conn.close()

    def get_all_analysis_results(self, limit=None):
        """Pobierz wszystkie wyniki analiz z bazy danych"""
        try:
            conn = sqlite3.connect(self.analysis_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = """
            SELECT * FROM CVAnalysisResults 
            ORDER BY creation_date DESC
            """
            
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query)
            results = cursor.fetchall()
            return results
            
        except Exception as e:
            print(f"Błąd podczas pobierania wyników analiz: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def get_analysis_by_score_range(self, min_score=None, max_score=None):
        """Pobierz analizy w określonym zakresie punktów"""
        try:
            conn = sqlite3.connect(self.analysis_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            conditions = []
            params = []
            
            if min_score is not None:
                conditions.append("score >= ?")
                params.append(min_score)
            
            if max_score is not None:
                conditions.append("score <= ?")
                params.append(max_score)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            query = f"""
            SELECT * FROM CVAnalysisResults 
            WHERE {where_clause}
            ORDER BY score DESC, creation_date DESC
            """
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            return results
            
        except Exception as e:
            print(f"Błąd podczas pobierania wyników według punktacji: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def get_analysis_statistics(self):
        """Pobierz statystyki analiz"""
        try:
            conn = sqlite3.connect(self.analysis_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Podstawowe statystyki
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_analyses,
                    AVG(score) as avg_score,
                    MAX(score) as max_score,
                    MIN(score) as min_score,
                    COUNT(DISTINCT cv_content_hash) as unique_cvs
                FROM CVAnalysisResults 
                WHERE score IS NOT NULL
            """)
            
            stats = cursor.fetchone()
            return dict(stats) if stats else {}
            
        except Exception as e:
            print(f"Błąd podczas pobierania statystyk: {e}")
            return {}
        finally:
            if conn:
                conn.close()

    def print_analysis_summary(self, limit=10):
        """Wyświetl podsumowanie ostatnich analiz"""
        results = self.get_all_analysis_results(limit)
        stats = self.get_analysis_statistics()
        
        print(f"\n{'='*80}")
        print("PODSUMOWANIE ANALIZ CV")
        print(f"{'='*80}")
        
        if stats:
            total_analyses = stats.get('total_analyses', 0) 
            avg_score = stats.get('avg_score', 0)
            max_score = stats.get('max_score', 0)
            min_score = stats.get('min_score', 0)
            unique_cvs = stats.get('unique_cvs', 0)
            
            print(f"Całkowita liczba analiz: {total_analyses}")
            if avg_score is not None:
                print(f"Średnia ocena: {avg_score:.1f}/10")
            else:
                print("Średnia ocena: N/A")
            print(f"Najwyższa ocena: {max_score}/10")
            print(f"Najniższa ocena: {min_score}/10")  
            print(f"Liczba różnych CV: {unique_cvs}")
        else:
            print("Brak danych statystycznych")
        
        print(f"\n{f'OSTATNIE {limit} ANALIZ':<50}")
        print("-" * 80)
        
        for result in results:
            score_display = f"{result['score']}/10" if result['score'] else "N/A"
            date_display = result['creation_date'][:16] if result['creation_date'] else "N/A"
            
            print(f"Data: {date_display} | Ocena: {score_display:<6} | Link: {result['job_link'][:60]}...")
        
        print(f"{'='*80}\n")

    def run(self):
        """Główna metoda uruchamiająca aplikację"""
        print("Analizator dopasowania CV do ofert pracy")
        print("=" * 50)
        print("Wybierz opcję:")
        print("1. Analizuj oferty z dzisiejszą datą")
        print("2. Analizuj oferty z określonego przedziału czasowego")
        print("3. Analizuj oferty z ostatnich X dni")
        print("4. Pokaż statystyki analiz z bazy danych")
        print("5. Pokaż najlepsze dopasowania (ocena >= 5)")
        print("6. Wklej ręcznie link do pojedynczej oferty")
        print("7. Wklej ręcznie tekst oferty i link")
        print("=" * 50)
        
        choice = input("Twój wybór (1-7): ").strip()
        
        if choice == '1':
            self.run_today_offers()
        elif choice == '2':
            print("Podaj datę początkową (YYYY-MM-DD):")
            start_date = input().strip()
            print("Podaj datę końcową (YYYY-MM-DD):")
            end_date = input().strip()
            self.run_between_dates_offers(start_date, end_date)
        elif choice == '3':
            self.run_last_x_days_offers()
        elif choice == '4':
            self.print_analysis_summary()
        elif choice == '5':
            self.show_best_matches()
        elif choice == '6':
            self.run_single_manual_offer()
        elif choice == '7':
            self.run_manual_text_offer()
        else:
            print("Nieprawidłowy wybór!")

    def run_last_x_days_offers(self):
        """Uruchom analizę dla ofert z ostatnich X dni (włącznie z dzisiaj)."""
        print("Podaj liczbę dni (np. 7):")
        days_input = input().strip()

        try:
            days = int(days_input)
            if days <= 0:
                print("Liczba dni musi być większa od 0.")
                return
        except ValueError:
            print("Nieprawidłowa liczba dni. Podaj liczbę całkowitą.")
            return

        end_date = date.today()
        start_date = end_date if days == 1 else end_date - timedelta(days=days - 1)
        self.run_between_dates_offers(start_date.isoformat(), end_date.isoformat())

    def show_best_matches(self):
        """Pokaż najlepiej dopasowane oferty"""
        results = self.get_analysis_by_score_range(min_score=5)
        
        print(f"\n{'='*80}")
        print("NAJLEPSZE DOPASOWANIA (OCENA >= 5/10)")
        print(f"{'='*80}")
        
        if not results:
            print("Brak analiz z oceną >= 5/10")
            return
        
        for result in results:
            print(f"\nOcena: {result['score']}/10")
            print(f"Data: {result['creation_date'][:16]}")
            print(f"Link: {result['job_link']}")
            
            if result['summary']:
                print(f"Podsumowanie: {result['summary'][:200]}...")
            
            # Pokaż mocne strony jeśli są dostępne
            if result['strengths']:
                try:
                    strengths = json.loads(result['strengths'])
                    if strengths:
                        print(f"Mocne strony: {', '.join(strengths[:3])}...")
                except:
                    pass
            
            print("-" * 40)

    def run_today_offers(self):
        """Uruchom analizę dla ofert z dzisiejszą datą"""
        try:
            # Wczytaj CV z output.txt
            cv_content = self.read_output_file()
            if not cv_content:
                print("Nie znaleziono pliku output.txt z CV!")
                return

            # Wyświetl linki ofert z dzisiejszą datą
            link_offers = self.return_job_links()

            if not link_offers:
                return
            

            # Przetwórz oferty
            self.process_offers(link_offers, cv_content)

        except Exception as e:
            print(f"Błąd: {e}")
        finally:
            self.close()

    def run_single_manual_offer(self):
        """Uruchom analizę dla ręcznie podanego linku"""
        try:
            cv_content = self.read_output_file()
            if not cv_content:
                print("Nie znaleziono pliku output.txt z CV!")
                return
            
            link = input("Wklej link do oferty pracy: ").strip()
            if not link.startswith(('http://', 'https://')):
                print("Niepoprawny format linku.")
                return
                
            if self.check_link_in_database_cv_analysis(link):
                print(f"OSTRZEŻENIE: Oferta z tego linku była już wcześniej analizowana.")
            
            self.process_offers([link], cv_content)
            
        except Exception as e:
            print(f"Błąd: {e}")
        finally:
            self.close()

    def run_manual_text_offer(self):
        """Uruchom analizę dla ręcznie wklejonego tekstu oferty"""
        try:
            cv_content = self.read_output_file()
            if not cv_content:
                print("Nie znaleziono pliku output.txt z CV!")
                return
            
            link = input("Podaj link do oferty (opcjonalnie, dla bazy danych): ").strip()
            if not link:
                link = f"manual_input_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            elif not link.startswith(('http://', 'https://')):
                print("OSTRZEŻENIE: Link nie zaczyna się od http/https. Zostanie zapisany jako tekst.")
                
            job_description = self._get_manual_text_input()
            
            if not job_description:
                print("Nie podano treści oferty. Przerywam.")
                return

            print("Analizuję dopasowanie...")
            analysis_result = self.analyze_with_ollama(cv_content, job_description)

            if analysis_result:
                self.save_analysis(analysis_result, link, cv_content)
                print("Analiza ukończona!")
            else:
                print("Nie udało się przeprowadzić analizy.")
                
        except Exception as e:
            print(f"Błąd: {e}")
        finally:
            self.close()

    def check_link_in_database_cv_analysis(self, link):
        """Sprawdź, czy dany link oferty pracy został już przeanalizowany"""
        try:
            conn = sqlite3.connect(self.analysis_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM CVAnalysisResults 
                WHERE job_link = ?
                ORDER BY creation_date DESC
                LIMIT 1
            """, (link,))
            
            result = cursor.fetchone()
            return result is not None
            
        except Exception as e:
            print(f"Błąd podczas sprawdzania linku w bazie danych: {e}")
            return False
        finally:
            if conn:
                conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Analizator dopasowania CV do ofert pracy')
    parser.add_argument('--model', help='Nazwa modelu Ollama (np. ministral-3:8b-cloud)', default=None)
    args = parser.parse_args()

    analyzer = MainJobAnalyzer(model_name=args.model)
    analyzer.run()
