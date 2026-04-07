import streamlit as st
import sqlite3
import pandas as pd
import json

# Konfiguracja strony
st.set_page_config(
    page_title="Analizy CV - Dashboard",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Ścieżka do bazy danych
DB_PATH = 'cv_analysis.db'

# Funkcja pobierająca dane z bazy (zapamiętywana w cache dla wyższej wydajności)
@st.cache_data(ttl=60) # Odświeżaj cache co 60 sekund w razie nowych analiz
def load_data():
    try:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT * FROM CVAnalysisResults"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Konwersja dat - obsługa mieszanych formatów (ISO z 'T' i standardowe)
        if 'creation_date' in df.columns:
            df['creation_date'] = pd.to_datetime(
                df['creation_date'], 
                format='mixed',  # Obsługuje różne formaty dat
                errors='coerce'
            )
            
        return df
    except Exception as e:
        st.error(f"Wystąpił błąd przy łączeniu z bazą: {e}")
        return pd.DataFrame()

def format_list_field(field_text):
    if pd.isna(field_text) or not str(field_text).strip():
        return "Brak danych"
    
    text_str = str(field_text)
    
    # Próbujemy odczytać jako JSON
    try:
        items = json.loads(text_str)
        if isinstance(items, list):
            return "\n".join([f"- {item}" for item in items])
    except:
        pass
        
    # Próbujemy jako python text (ast.literal_eval)
    try:
        import ast
        items = ast.literal_eval(text_str)
        if isinstance(items, list):
            return "\n".join([f"- {item}" for item in items])
    except:
        pass
        
    return text_str

# Nagłówek aplikacji
st.title("💼 Interaktywny Panel Analiz CV")
st.markdown("Przeglądaj, sortuj i selekcjonuj przeprowadzone analizy ze swojej bazy danych.")

# Ładowanie danych
df = load_data()

if df.empty:
    st.warning("Brak danych w bazie 'cv_analysis.db' lub baza nie istnieje.")
else:
    # --- PANEL BOCZNY (Sidebar) ---
    st.sidebar.header("🔍 Filtry")
    
    # Przycisk odświeżania danych
    if st.sidebar.button("🔄 Odśwież dane"):
        st.cache_data.clear()
        st.rerun()
    
    # Przeszukiwanie tekstu pole 'job_link' lub 'summary'
    search_term = st.sidebar.text_input("Szukaj po stanowisku (Job Link):")
    
    # Filtrowanie wyniku — skala 0-10 (0 = brak oceny / NULL)
    # Stała skala 0-10 zamiast dynamicznej, by nie zgubić rekordów z NULL
    score_range = st.sidebar.slider(
        "Wynik (Score) — 0 = brak oceny:",
        min_value=0,
        max_value=10,
        value=(0, 10)
    )
    
    # Checkbox: pokaż rekordy bez oceny
    show_no_score = st.sidebar.checkbox("Pokaż rekordy bez oceny (NULL)", value=True)
    
    # Filtrowanie daty
    start_date, end_date = None, None
    if 'creation_date' in df.columns and pd.api.types.is_datetime64_any_dtype(df['creation_date']):
        valid_dates = df['creation_date'].dropna()
        if not valid_dates.empty:
            min_date = valid_dates.min().date()
            max_date = valid_dates.max().date()
            st.sidebar.markdown("**Data wykonania analizy:**")
            start_date = st.sidebar.date_input("Od:", min_date)
            end_date = st.sidebar.date_input("Do:", max_date)
            
    # --- APLIKOWANIE FILTRÓW ---
    filtered_df = df.copy()
    
    # Po tekście (Job Link)
    if search_term:
        filtered_df = filtered_df[filtered_df['job_link'].str.contains(search_term, case=False, na=False)]
        
    # Po wyniku — obsługa rekordów z NULL score
    if 'score' in filtered_df.columns:
        has_score = filtered_df['score'].notna()
        in_range = (filtered_df['score'] >= score_range[0]) & (filtered_df['score'] <= score_range[1])
        
        if show_no_score:
            filtered_df = filtered_df[in_range | ~has_score]
        else:
            filtered_df = filtered_df[in_range & has_score]
        
    # Po dacie
    if start_date and end_date and 'creation_date' in filtered_df.columns:
        start_ts = pd.to_datetime(start_date)
        # Dodajemy cały dzień, żeby objąć godziny 23:59:59 (rejestrowane w bazie)
        end_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1, seconds=-1)
        
        # Uwzględnij też rekordy z NULL datą (opcjonalnie)
        has_date = filtered_df['creation_date'].notna()
        in_date_range = (filtered_df['creation_date'] >= start_ts) & (filtered_df['creation_date'] <= end_ts)
        filtered_df = filtered_df[in_date_range | ~has_date]

    # --- WIDOK GŁÓWNY ---
    st.subheader(f"📊 Lista Analiz ({len(filtered_df)} znalezionych)")
    
    # Kolumny używane do ogólnego widoku
    cols_to_display = ['analysis_id', 'creation_date', 'job_link', 'score', 'summary']
    display_df = filtered_df[[c for c in cols_to_display if c in filtered_df.columns]]
    
    # Interaktywna Tabela
    event = st.dataframe(
        display_df,
        width='stretch',
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )

    # --- WIDOK SZCZEGÓŁÓW (Jeśli coś zaznaczono) ---
    selected_indices = event.selection.rows
    if selected_indices:
        st.divider()
        # Wyciągamy rzeczywisty indeks wybranego wiersza z przefiltrowanego df
        selected_index = filtered_df.index[selected_indices[0]]
        selected_row = filtered_df.loc[selected_index]
        
        st.header("📋 Szczegóły Wybranej Analizy")
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.markdown(f"**Stanowisko / Link:** {selected_row.get('job_link', 'Brak')}")
            st.markdown(f"**Data:** {selected_row.get('creation_date', 'Brak')}")
        with col2:
            st.metric(label="Wynik (Score)", value=selected_row.get('score', 'N/A'))
        with col3:
            st.markdown(f"**ID Analizy:** {selected_row.get('analysis_id', 'Brak')}")
            
        st.markdown("---")
        
        # Zakładki pozwalają na uporządkowanie wielu informacji (Mocne strony, słabe strony itp.)
        tab1, tab2, tab3, tab4 = st.tabs(["📌 Podsumowanie", "✅ Mocne & ❌ Słabe strony", "🎯 Umiejętności", "📄 Pełna treść"])
        
        with tab1:
            st.markdown("### Podsumowanie (Summary)")
            st.info(selected_row.get('summary', 'Brak wpisu w bazie.'))
            
        with tab2:
            col_s, col_w = st.columns(2)
            with col_s:
                st.success("### Mocne strony")
                st.markdown(format_list_field(selected_row.get('strengths', 'Brak')))
            with col_w:
                st.error("### Słabe strony")
                st.markdown(format_list_field(selected_row.get('weaknesses', 'Brak')))
                
        with tab3:
            col_ms, col_mis = st.columns(2)
            with col_ms:
                st.write("### Dopasowane umiejętności (Matched Skills)")
                st.markdown(format_list_field(selected_row.get('matched_skills', 'Brak')))
            with col_mis:
                st.write("### Brakujące umiejętności (Missing Skills)")
                st.markdown(format_list_field(selected_row.get('missing_skills', 'Brak')))
                
        with tab4:
            st.markdown("### Surowy wynik (Analysis Content)")
            with st.expander("Kliknij, aby rozwinąć cały tekst z API LLM"):
                content = str(selected_row.get('analysis_content', 'Brak wpisu.'))
                if content.strip().startswith("```"):
                    st.markdown(content)
                else:
                    st.code(content, language="json")
    else:
        st.info("💡 Zaznacz pojedynczy wiersz w tabeli wyżej, aby zobaczyć szczegóły analizy na pełnym ekranie.")
