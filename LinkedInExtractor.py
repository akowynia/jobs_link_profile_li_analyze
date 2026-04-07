import ollama
from pathlib import Path
import time
from collections import Counter

class LinkedInExtractor:
    """
    Klasa do ekstrakcji danych z sekcji 'Doświadczenie' ze zrzutów ekranu LinkedIn.
    """
    
    def __init__(self, image_path: str, model: str = 'deepseek-ocr'):
        """
        Inicjalizacja ekstraktora.
        
        Args:
            image_path: Ścieżka do pliku ze zrzutem ekranu
            model: Nazwa modelu Ollama (domyślnie 'deepseek-ocr')
        """
        self.image_path = Path(image_path)
        self.model = model
        self.result = ""
        self.chunk_count = 0
        self.elapsed_time = 0
        self.loop_detected = False
        
    def validate_image(self) -> bool:
        """
        Sprawdza czy plik obrazu istnieje.
        
        Returns:
            True jeśli plik istnieje, False w przeciwnym razie
        """
        if not self.image_path.exists():
            print(f"BŁĄD: Nie znaleziono pliku {self.image_path}")
            return False
        return True
    
    def extract(self, prompt: str = 'Extract data from Doświadczenie', 
                output_file: str = None,
                timeout: int = 120,
                loop_detection: bool = True) -> str:
        """
        Ekstraktuje dane z obrazu.
        
        Args:
            prompt: Prompt dla modelu
            output_file: Opcjonalna ścieżka do pliku wyjściowego
            timeout: Maksymalny czas oczekiwania w sekundach
            loop_detection: Czy włączyć wykrywanie zapętleń
        
        Returns:
            Wyekstraktowany tekst
        """
        if not self.validate_image():
            return ""
        
        full_image_path = str(self.image_path.resolve())
        
        print("Wysyłam zapytanie do Ollama z modelem", self.model)
        print(f"Obraz: {full_image_path}")
        print("Trwa generowanie odpowiedzi (streaming)...\n")
        print("="*50)
        
        self.result = ""
        self.chunk_count = 0
        self.loop_detected = False
        start_time = time.time()
        
        try:
            stream = ollama.generate(
                model=self.model,
                prompt=prompt,
                images=[full_image_path],
                stream=True
            )
            
            for chunk in stream:
                if 'response' in chunk:
                    content = chunk['response']
                    self.chunk_count += 1
                    self.result += content
                    
                    # Wykrywanie zapętlenia
                    if loop_detection and self.chunk_count % 10 == 0 and len(self.result) > 100:
                        if self._detect_loop():
                            break
                    
                    print(content, end='', flush=True)
            
            print("\n" + "="*50)
            
            self.elapsed_time = time.time() - start_time
            self._print_summary()
            
        except KeyboardInterrupt:
            print("\n\n⚠️  Przerwano przez użytkownika (Ctrl+C)")
            print("="*50)
        except Exception as e:
            print(f"\n\n❌ BŁĄD: {str(e)}")
            print("="*50)
            raise
        
        # Zapisz do pliku jeśli podano ścieżkę
        if output_file and self.result:
            self.save_to_file(output_file)
        
        return self.result
    
    def _detect_loop(self) -> bool:
        """
        Wykrywa zapętlenie w wygenerowanym tekście.
        
        Returns:
            True jeśli wykryto zapętlenie
        """
        last_200 = self.result[-200:]
        lines = last_200.strip().split('\n')
        
        if len(lines) >= 5:
            last_5_lines = lines[-5:]
            word_counter = Counter()
            
            for line in last_5_lines:
                words = line.strip().split()
                word_counter.update(words)
            
            excluded_words = ['the', 'a', 'an', 'and', 'or', 'w', 'i', 'z', '-', '–', '—', '*', '•']
            
            for word, count in word_counter.items():
                if count >= 5 and word.lower() not in excluded_words:
                    self.loop_detected = True
                    print(f"\n\n⚠️  WYKRYTO ZAPĘTLENIE! Słowo '{word}' powtórzone {count} razy w ostatnich liniach")
                    return True
        
        return False
    
    def _print_summary(self):
        """Wyświetla podsumowanie ekstrakcji."""
        print(f"\nCzas generowania: {self.elapsed_time:.2f}s")
        print(f"Liczba chunków: {self.chunk_count}")
        
        if self.loop_detected:
            print("Status: ⚠️  Przerwano z powodu zapętlenia")
        else:
            print("Status: ✓ Zakończono pomyślnie")
    
    def save_to_file(self, output_file: str):
        """
        Zapisuje wynik do pliku.
        
        Args:
            output_file: Ścieżka do pliku wyjściowego
        """
        if not self.result:
            print("\n⚠️  Brak danych do zapisania")
            return
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(self.result)
            if self.loop_detected:
                f.write("\n\n[UWAGA: Generowanie przerwano z powodu wykrytego zapętlenia]")
        
        print(f"\nWynik zapisany do pliku: {output_file}")
        print(f"Długość odpowiedzi: {len(self.result)} znaków")
    
    def get_result(self) -> str:
        """
        Zwraca wyekstraktowany tekst.
        
        Returns:
            Wyekstraktowany tekst
        """
        return self.result


if __name__ == "__main__":
    # Przykład użycia
    extractor = LinkedInExtractor("image.png")
    result = extractor.extract(output_file="output.txt")
