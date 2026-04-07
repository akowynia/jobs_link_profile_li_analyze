# Jobs-Link-Profile_LI_Analyze

Projekt automatyzuje analizę dopasowania CV do ofert pracy z użyciem lokalnych modeli Ollama na podstawie zrzutu ekranu wykonanego z doświadczenia linkedin jako cv. Jest to rozszerzenie projektu bazowego Jobs-alert-discord-IT i korzysta z jego bazy ofert.

## Relacja do projektu bazowego

To repozytorium zakłada, że masz dane ofert w bazie discord_bot.db generowanej przez:
https://github.com/akowynia/Jobs-alert-discord-IT

Bez tej bazy analiza ofert nie będzie działać.

## Co robi projekt

- pobiera oferty pracy z discord_bot.db
- czyści treść stron ofert (cloudscraper + BeautifulSoup)
- porównuje  (output.txt) z ofertą przez Ollama
- zapisuje wyniki do cv_analysis.db i plików analyses_txt
- udostępnia dashboard Streamlit
- generuje raport PDF z analiz
- wspiera import historycznych analiz z plików txt

## Szybki start

1. Utwórz i aktywuj środowisko:

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Zainstaluj zależności:

```bash
pip install -r requirements.txt
```

3. Uruchom Ollama i pobierz modele:

```bash
ollama pull ministral-3:8b
ollama pull deepseek-ocr
```
4. Wykonaj zrzut ekranu sekcji doświadczenia z LinkedIn: https://www.linkedin.com/in/twoje-linkedin-id/details/experience/

	Najwygodniej użyć rozszerzenia GoFullPage albo zwykłego narzędzia do zrzutów ekranu. Zapisz plik jako `image.png` w katalogu głównym projektu, a potem uruchom:

	```bash
	python LinkedinExtractor.py
	```

5. Upewnij się, że masz:
- discord_bot.db z projektu bazowego
- output.txt z treścią z poprzedniego kroku.

6. Uruchom analizator:

```bash
python main.py
```

## Przepływ pracy end-to-end

1. Jobs-alert-discord-IT zapisuje oferty do discord_bot.db.
2. main.py wybiera oferty z danego dnia lub zakresu.
3. Dla każdej oferty pobierana i czyszczona jest treść strony.
4. Ollama zwraca JSON z oceną i szczegółami dopasowania.
5. Wynik trafia do cv_analysis.db oraz do analyses_txt/analiza_YYYY-MM-DD.txt.
6. Wyniki można przeglądać w dashboard.py lub eksportować przez pdf_create.py.

## Uruchamianie modułów

Analiza ofert:

```bash
python main.py
```

Dashboard:

```bash
streamlit run dashboard.py
```

Generowanie PDF:

```bash
python pdf_create.py
```


Ekstrakcja danych ze zrzutu LinkedIn:

```bash
python LinkedInExtractor.py
```

## Zrzuty ekranu

Dashboard:

![Widok dashboardu](images/dashboard.png)

Przykład wygenerowanego raportu PDF:

![Przykład raportu PDF](images/raport_przyklad.png)


## Testy

Instalacja zależności developerskich:

```bash
pip install -r requirements-dev.txt
```

Uruchomienie testów:

```bash
pytest
```

Zakres testów:
- unit: parser JSON i logika detekcji pętli
- integration: główny analizator z mockami Ollama/HTTP/SQLite oraz PDF z mockiem WeasyPrint

## Uwagi dla macOS (WeasyPrint)

Jeśli generowanie PDF zwraca błąd bibliotek systemowych GTK/Pango (np. libgobject), doinstaluj wymagane biblioteki systemowe, bo to problem środowiska, nie logiki kodu.
