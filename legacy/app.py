import streamlit as st
import re
import pandas as pd
import plotly.express as px
from transformers import pipeline
import io
import torch
import concurrent.futures
import time
import json
import os
from datetime import datetime

# --- Page Config ---
st.set_page_config(
    page_title="CX Sentiment Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for Corporate Look ---
st.markdown("""
    <style>
        .block-container {
            padding-top: 3rem;
            padding-bottom: 5rem;
        }
        h1, h2, h3 {
            font-family: 'Segoe UI', sans-serif;
            font-weight: 600;
        }
        .stMetric {
            background-color: #f8f9fa;
            border: 1px solid #e9ecef;
            padding: 15px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        /* Tab Styling */
        .stTabs [data-baseweb="tab-list"] {
            gap: 10px;
        }
        .stTabs [data-baseweb="tab"] {
            height: 50px;
            white-space: pre-wrap;
            background-color: #f0f2f6;
            border-radius: 5px;
            gap: 1px;
            padding-top: 10px;
            padding-bottom: 10px;
        }
        .stTabs [aria-selected="true"] {
            background-color: #ff4b4b !important;
            color: white !important;
            font-weight: bold;
        }
    </style>
""", unsafe_allow_html=True)

# --- Helper Functions ---
@st.cache_data
def load_data(uploaded_file):
    if uploaded_file.name.endswith('.xlsx'):
        return pd.read_excel(uploaded_file)
    else:
        return pd.read_csv(uploaded_file)



# --- Executive Logic ---
def calculate_executive_metrics(df):
    total = len(df)
    if total == 0: return 0, 0, pd.Series()
    
    pos = len(df[df['Sentiment_Label'] == 'Pozitif'])
    neu = len(df[df['Sentiment_Label'] == 'Nötr'])
    
    # SHI Formula: (Pos% * 100) + (Neu% * 50)
    shi_score = ((pos / total) * 100) + ((neu / total) * 50)
    
    # Critical Negative count (based on Score <= -0.80)
    if 'Sentiment_Score' in df.columns:
        crisis_count = len(df[df['Sentiment_Score'] <= -0.80])
    else:
        crisis_count = 0
    
    top_issues = pd.Series()
    if 'Şirket Perspektifi' in df.columns and 'Sentiment_Label' in df.columns:
        top_issues = df[df['Sentiment_Label'] == 'Negatif']['Şirket Perspektifi'].value_counts().head(3)
    
    return int(shi_score), crisis_count, top_issues

def generate_executive_brief_logic(df):
    total = len(df)
    neg = len(df[df['Sentiment_Label'] == 'Negatif'])
    neg_rate = (neg / total * 100) if total > 0 else 0
    
    top_issue = "None"
    if 'Şirket Perspektifi' in df.columns:
        issues = df[df['Sentiment_Label'] == 'Negatif']['Şirket Perspektifi'].value_counts()
        if not issues.empty:
            top_issue = issues.index[0]

    brief = f"**Executive Summary:** Analysis of **{total}** reviews shows a negative sentiment rate of **{neg_rate:.1f}%**. "
    brief += f"The primary operational bottleneck identified is **'{top_issue}'**. "
    if neg_rate > 20:
        brief += "Immediate action is recommended to address rising customer dissatisfaction."
    else:
        brief += "Sentiment levels are currently within acceptable range."
    return brief

@st.cache_resource
def load_bert_model():
    model_name = "savasy/bert-base-turkish-sentiment-cased"
    sentiment_pipeline = pipeline("sentiment-analysis", model=model_name)
    return sentiment_pipeline

def analyze_sentiment_bert_batch(texts, pipeline, batch_size=32):
    valid_texts = [t if isinstance(t, str) else "" for t in texts]
    predictions = pipeline(valid_texts, batch_size=batch_size, truncation=True)
    results = []
    for pred in predictions:
        label = pred['label']
        score = pred['score']
        if label == 'positive':
            results.append((score, 0.0, "Pozitif"))
        elif label == 'negative':
            results.append((-score, 0.0, "Negatif"))
        else:
            results.append((0.0, 0.0, "Nötr"))
    return results

def load_knowledge_base():
    try:
        kb_df = pd.read_csv("training_data.csv")
        text_col = None
        for col in kb_df.columns:
            if col in ["Müşteri Yorumu", "Review", "review", "comments", "Yorum"]:
                text_col = col
                break
        if text_col and 'Correct Label' in kb_df.columns:
             return dict(zip(kb_df[text_col], kb_df['Correct Label']))
    except:
        pass
    return {}



# --- Sidebar ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3003/3003033.png", width=50)
    st.title("CX Dashboard")
    st.write("Upload your customer reviews to generate insights.")
    
    st.markdown("---")
    
    uploaded_file = st.file_uploader("Upload Excel or CSV", type=['xlsx', 'csv'], key="main_file_uploader")
    
    # Auto-Reset Logic if file changes
    if uploaded_file:
        if 'last_uploaded_file' not in st.session_state or st.session_state['last_uploaded_file'] != uploaded_file.name:
            # New file detected! Clear cache
            if 'processed_df' in st.session_state: del st.session_state['processed_df']
            if 'exec_brief' in st.session_state: del st.session_state['exec_brief']
            st.session_state['last_uploaded_file'] = uploaded_file.name
            # st.rerun() # Optional, but safer to let main flow handle it
    st.markdown("---")
    st.markdown("**Instructions:**")
    st.markdown("Your file must contain a column named **'Müşteri Yorumu'** or **'Review'**.")

    st.markdown("---")


    st.markdown("---")
    st.subheader("Filter Options")
    sentiment_filter = st.selectbox("Show Sentiment:", ["All", "Pozitif", "Nötr", "Negatif"])

# --- Helper Functions (Rules) ---
def load_rules():
    if not os.path.exists("cx_rules.json"):
        return {"customer_rules": [], "company_rules": []}
    try:
        with open("cx_rules.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"customer_rules": [], "company_rules": []}

def save_rules(rules):
    with open("cx_rules.json", "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=4)

def load_params():
    if not os.path.exists("cx_params.json"):
        return {"max_shipping_days": 3, "max_warehouse_days": 2}
    try:
        with open("cx_params.json", "r", encoding="utf-8") as f:
             return json.load(f)
    except:
        return {"max_shipping_days": 3, "max_warehouse_days": 2}

def save_params(params):
    with open("cx_params.json", "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=4)

# --- Core Analysis Engine ---
@st.cache_data(show_spinner=False)
@st.cache_data(show_spinner=False)
@st.cache_data(show_spinner=False)
def process_dataframe(df, target_col, rules, knowledge_base, params):
    # Shared constants
    CRITICAL_KEYWORDS = [
        "hırsızlık", "hırsız", "suçlama", "alarm", "polis", "mahkeme", "dava", "savcılık", 
        "tehdit", "taciz", "hakaret", "küfür", "güvenlik", "etiket", "unutulmuş"
    ]

    # --- Heuristic Summary Logic ---

    # Tier 1: Strong Sentiment (Adjectives)
    TIER1_SENTIMENT = [
        "ilgisiz", "saygısız", "kaba", "çözümsüz", "mağdur", "rezalet", "berbat", "iğrenç", 
        "profesyonellikten uzak", "lakayıt", "bilgisiz", "yetersiz", "sorumsuz", "dalga geçer gibi",
        "oyalayıcı", "ezbere", "küstah", "yalancı", "fiyasko", "alaya", "aptal", "dalga"
    ]
    
    # Tier 2: Pain Points (Nouns/Issues)
    TIER2_ISSUES = [
        "iade", "iptal", "ücret", "para", "teslimat", "kargo", "gecikme", "bozuk", "defolu", 
        "eksik", "yanlış", "sahte", "hile", "yalan", "tutar", "fatura", "kayıp", "hasarlı",
        "beden", "kalite", "kumaş", "dikiş", "leke", "ayıplı", "kusurlu", "değişim", "reddedildi", 
        "kabul edilmedi", "red", "kırık"
    ]
    
    # Tier 3: Action Failures (Verbs/Results)
    TIER3_FAILURES = [
        "gelmedi", "ulaşmadı", "yapılmadı", "etmedi", "açmadı", "kapattı", "dönmedi", 
        "bitmedi", "ulaşamıyorum", "bağlanamıyorum", "cevap yok", "bekliyorum", "alamadım"
    ]

    # --- Keyword Extraction / Summary Logic ---
    def generate_summary_heuristic(text):
        if not isinstance(text, str): return ""
        
        # 1. Clean Email Noise
        cutoff_patterns = [
            r"Sent from my iPhone", r"Sent from my Android", r"On\s.*wrote:", r"Tarihinde\s.*yazdı:",
            r"From:\s", r"Kimden:\s", r"Subject:\s", r"Konu:\s", r"Saygılarımızla", r"İyi çalışmalar",
            r"LC\s?Waikiki\sMüşteri\sHizmetleri", r"Müşteri\sHizmetleri", r"https?://\S+",
            r"\bMERHABALAR?\b", r"\bSAYIN\sYETKİLİ\b", r"\bTEŞEKKÜRLER\b"
        ]
        
        cleaned_text = text
        for pattern in cutoff_patterns:
            match = re.search(pattern, cleaned_text, re.IGNORECASE | re.DOTALL)
            if match:
                 # HEADER/GREETING PATTERNS: Remove the pattern, KEEP the rest.
                 # We removed "LC" and "MÜŞTERI HIZMETLERI" because they appear in reply footers too.
                 if any(x in pattern.upper() for x in ["MERHABA", "SAYIN", "SUBJECT", "KONU"]):
                     cleaned_text = re.sub(pattern, " ", cleaned_text, flags=re.IGNORECASE)
                 # FOOTER/SIGNATURE PATTERNS: Keep text BEFORE the match.
                 else:
                     cleaned_text = cleaned_text[:match.start()]
        
        cleaned_text = cleaned_text.strip()
        if not cleaned_text: cleaned_text = text[:100]

        # --- DICTIONARY HEURISTIC (TIERED) ---
        
        # Tier 0: Critical / Legal / Security (PRIORITY 1)
        tier0_critical = CRITICAL_KEYWORDS

        # Concept Mapping (Higher Priority)
        CONCEPT_MAPPING = {
            "İletişim Sorunu": ["aramadılar", "ulaşamadım", "cevap yok", "açmıyor", "muhatap", "dönüş yapmadı", "kapattı", "ulaşılmıyor", "numaramı bıraktım", "telefona cevap"],
            "İade/Ücret Sorunu": ["iade", "ücret", "para", "hesap", "yatmadı", "tutar"],
            "Teslimat Gecikmesi": ["kargo", "gelmedi", "teslim", "gecikti", "bekliyorum", "ulaşmadı"]
        }

        found_keywords = []
        lower_text = cleaned_text.lower()
        
        # Critical words first!
        for word in tier0_critical:
            if word in lower_text: found_keywords.append("🚨 " + word.upper())

        # Check Concepts
        for concept, keywords in CONCEPT_MAPPING.items():
            if any(kw in lower_text for kw in keywords):
                found_keywords.append(concept)


        for word in TIER1_SENTIMENT:
            if word in lower_text: found_keywords.append(word.title())
        for word in TIER2_ISSUES:
             if word in lower_text: found_keywords.append(word.title())
        for word in TIER3_FAILURES:
             if word in lower_text: found_keywords.append(word.title())

        unique_keywords = []
        seen = set()
        for kw in found_keywords:
            if kw not in seen:
                unique_keywords.append(kw)
                seen.add(kw)

        if unique_keywords:
            return "📝 " + ", ".join(unique_keywords[:5])
        
        words = re.findall(r'\w+', cleaned_text)
        words = [w for w in words if len(w) > 4 and w.lower() not in ["tarihinde", "olarak", "kadar"]]
        longest = sorted(list(set(words)), key=len, reverse=True)[:4]
        return "📝 " + ", ".join(longest) if longest else ""

    # --- Perspective Logic ---
    def get_customer_perspective(text):
        if not isinstance(text, str): return "-"
        t = text.lower()
        # 1. Smart Rules
        for rule in rules["customer_rules"]:
            for kw in rule["keywords"]:
                if kw in t: return rule["label"]
        # 2. Hardcoded
        if "iade" in t and ("istiyorum" in t or "talep" in t or "hakkım" in t): return "İade Talebi"
        if "değişim" in t and ("istiyorum" in t or "talep" in t or "hakkım" in t): return "Değişim Talebi"
        if "iptal" in t and ("istiyorum" in t or "etmeliyim" in t): return "İptal Talebi"
        if "ücret" in t and "iade" in t: return "Ücret İadesi Talebi"
        if "yetkili" in t and ("görüşmek" in t or "arıyorum" in t): return "Yetkiliyle Görüşme Talebi"
        if "çözüm" in t and ("bekliyorum" in t or "istiyorum" in t): return "Çözüm Beklentisi"
        if "mağdur" in t: return "Mağduriyet Giderimi"
        if "şikayetçiyim" in t: return "Resmi Şikayet"
        return "Memnuniyetsizlik / Bilgi Talebi"

    def get_company_perspective(text):
        if not isinstance(text, str): return "-"
        t = text.lower()
        # 1. Smart Rules
        for rule in rules["company_rules"]:
            for kw in rule["keywords"]:
                if kw in t: return rule["label"]
        # 2. Hardcoded
        if "değişim" in t and ("yok" in t or "red" in t or "kabul" in t or "yapılmadı" in t): return "Değişim Prosedürü / Stok"
        if "online" in t and ("mağaza" in t or "değişim" in t): return "Omnichannel (Online-Mağaza) Uyuşmazlığı"
        if "ayıplı" in t or "defolu" in t or "kusurlu" in t or "yırtık" in t or "leke" in t: return "Ürün Kalite Kontrol (Defolu Gönderim)"
        if "personel" in t or "temsilci" in t or "çalışan" in t or "görevli" in t:
            if "kaba" in t or "saygısız" in t or "ilgisiz" in t or "bağırdı" in t: return "Personel Davranışı / Eğitim"
        if "kargo" in t or "teslimat" in t or "getirmedi" in t: return "Lojistik / Kargo Firması Hatası"
        if "stok" in t or "kalmadı" in t or "temin" in t: return "Stok Yönetimi"
        if "sistem" in t or "hata" in t or "açılmıyor" in t: return "Dijital Altyapı / IT Sorunu"
        if "yanlış" in t and ("bilgi" in t or "yönlendirme" in t): return "Hatalı Bilgilendirme"
        return "Genel Operasyonel Aksaklık"
    
    df_proc = df.copy()

    # Apply Logic (Heuristic only)
    df_proc['Yorum Özet'] = df_proc[target_col].apply(generate_summary_heuristic)

    df_proc['Şirket Perspektifi'] = df_proc[target_col].apply(get_company_perspective)
    
    # Sentiment Analysis (BERT ONLY + Heuristic Overrides)
    bert_pipeline = load_bert_model()

    all_results = [None] * len(df_proc)
    texts_to_process = []
    indices_to_process = []
    
    for idx, text in enumerate(df_proc[target_col]):
        t_str = str(text)
        t_lower = t_str.lower()
        
        # 1. Knowledge Base
        if t_str in knowledge_base:
            lbl = knowledge_base[text]
            sc = 0.9 if lbl == 'Pozitif' else -0.9 if lbl == 'Negatif' else 0.0
            all_results[idx] = (sc, 0.0, lbl)
            continue

        # 2. Critical Override
        is_critical = False
        for crit in CRITICAL_KEYWORDS:
             if crit in t_lower:
                 all_results[idx] = (-0.95, 1.0, "Negatif")
                 is_critical = True
                 break
        if is_critical: continue

        # 3. Strong Negative Override
        is_strong = False
        for word in TIER1_SENTIMENT:
             if word in t_lower:
                 all_results[idx] = (-0.75, 1.0, "Negatif")
                 is_strong = True
                 break
        if is_strong: continue
        
        # If not overridden, queue for BERT
        texts_to_process.append(t_str)
        indices_to_process.append(idx)
    
    # Run BERT Batch
    if texts_to_process:
        batch_results = analyze_sentiment_bert_batch(texts_to_process, bert_pipeline)
        
        # Post-process BERT results
        for i, res in zip(indices_to_process, batch_results):
            score, subj, label = res
            orig_text = str(df_proc.iloc[i][target_col]).lower()
            
            # --- PARAMETER CHECK (SLA) ---
            # Extract duration: "3 gün", "5 iş günü"
            duration_match = re.search(r'(\d+)\s*(?:gün|iş günü|hafta)', orig_text)
            if duration_match:
                days = int(duration_match.group(1))
                if "hafta" in duration_match.group(0): days = days * 7
                
                # Check for Shipping Context
                if any(x in orig_text for x in ["kargo", "sipariş", "teslim", "gelmedi", "bekliyorum"]):
                    sla = params.get("max_shipping_days", 3)
                    if days <= sla:
                         score = 0.05
                         label = f"SLA Uyumlu ({days} Gün <= {sla})"
                    else:
                         score = -0.60
                         label = f"SLA Aşımı ({days} Gün > {sla})"

                # Check for Warehouse Context
                elif any(x in orig_text for x in ["hazırlanıyor", "depo", "paket", "çıkış"]):
                    sla = params.get("max_warehouse_days", 2)
                    if days <= sla:
                         score = 0.05
                         label = f"SLA Uyumlu ({days} Gün <= {sla})"
                    else:
                         score = -0.60
                         label = f"SLA Aşımı ({days} Gün > {sla})"

            # --- TIER 2 CHECK (Operational Fallback) ---
            # Only if NOT overridden by SLA logic above (meaning label is still generic Negatif/Pozitif)
            if "SLA" not in label:
                 # Check for operational issues if model thinks it is NOT negative
                 if score > -0.05:
                     for word in TIER2_ISSUES:
                         if word in orig_text:
                             score = -0.40
                             label = "Negatif"
                             break
            
            all_results[i] = (score, subj, label)

    df_proc['Sentiment_Score'], df_proc['Subjectivity'], df_proc['Sentiment_Label'] = zip(*all_results)
    
    # Risk Classification
    def classify_risk(score):
        if score is None: return "⚪ Nötr"
        if score < -0.05: return "🔴 Negatif"
        if score > 0.05: return "🟢 Pozitif"
        return "⚪ Nötr"
    
    df_proc['Risk Durumu'] = df_proc['Sentiment_Score'].apply(classify_risk)
    df_proc = df_proc.sort_values(by='Sentiment_Score', ascending=True)
    
    return df_proc

# --- Visualization Helper ---
def render_dashboard_analysis(df, target_col):
    st.markdown("### 1. Detailed Analysis & Selection")
    df_display = df.copy()
    df_display['Select for Correction'] = False 
    cols = [target_col]
    if 'Risk Durumu' in df_display.columns: cols.append('Risk Durumu')
    if 'Yorum Özet' in df_display.columns: cols.append('Yorum Özet')
    if 'Müşteri Perspektifi' in df_display.columns: cols.append('Müşteri Perspektifi')
    if 'Şirket Perspektifi' in df_display.columns: cols.append('Şirket Perspektifi')
    
    if 'Source' in df_display.columns: cols.append('Source')
    cols.extend(['Sentiment_Score', 'Select for Correction'])
    
    # Filter existing columns only
    cols = [c for c in cols if c in df_display.columns]

    selection_df = st.data_editor(
        df_display[cols],
        column_config={"Select for Correction": st.column_config.CheckboxColumn("Fix This", default=False)},
        disabled=[c for c in cols if c != "Select for Correction"],
        use_container_width=True, hide_index=True, key="main_editor"
    )

    selected_rows = selection_df[selection_df['Select for Correction'] == True]
    if not selected_rows.empty:
        st.divider()
        st.markdown("### 2. Learning Queue & Correction")
        correction_data = selected_rows[[target_col, 'Sentiment_Label']].copy()
        correction_data = correction_data.rename(columns={'Sentiment_Label': 'Current Prediction'})
        correction_data['Best Label'] = correction_data['Current Prediction']
        correction_data['Reason'] = "" 
        
        corrected_df = st.data_editor(
            correction_data,
            column_config={
                    "Best Label": st.column_config.SelectboxColumn("Correct Label", options=["Pozitif", "Nötr", "Negatif"], required=True),
                    "Current Prediction": st.column_config.TextColumn("Predicted", disabled=True),
                    "Reason": st.column_config.TextColumn("Correction Reason (Optional)", width="large")
            },
            disabled=[target_col, "Current Prediction"],
            use_container_width=True, hide_index=True, key="correction_editor"
        )

        if st.button("🚀 Train & Save", type="primary"):
            try:
                save_df = corrected_df[[target_col, 'Best Label', 'Reason']].rename(columns={'Best Label': 'Correct Label'})
                save_df['Timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                with open("training_data.csv", "a", encoding="utf-8") as f:
                    file_is_empty = f.tell() == 0
                    save_df.to_csv(f, header=file_is_empty, index=False)
                    
                st.success("✅ Learned & Logged! Future analysis will use these labels.")
                st.balloons()
            except Exception as e:
                st.error(f"Error saving: {e}")
    else:
        st.write("") 

# --- Main Page Layout ---
tab_main, tab_rules, tab_ops = st.tabs(["📊 Dashboard & Analysis", "🧠 Smart Rules", "⚙️ Operasyonel Parametreler"])

# ==========================================
# TAB 1: DASHBOARD & ANALYSIS (SINGLE VIEW)
# ==========================================
with tab_main:
    # 1. State Check: If we have processed data, SHOW DASHBOARD
    if 'processed_df' in st.session_state:
        df_exec = st.session_state['processed_df']
        
        # --- EXECUTIVE SECTION ---
        st.header("👔 Executive Summary")
        shi, crisis, top_issues = calculate_executive_metrics(df_exec)
        
        m1, m2, m3 = st.columns(3)
        m1.metric("❤️ Sentiment Health Index", f"{shi}/100", delta=f"{shi-50} vs Baseline")
        m2.metric("🚨 Crisis Radar (Incidents)", f"{crisis}", delta="Critical", delta_color="inverse")
        m3.metric("📉 Total Reviews", len(df_exec))
        
        st.divider()
        
        c1, c2 = st.columns([2, 1])
        with c1:
            st.subheader("💡 Strategic Insight")
            if 'exec_brief' not in st.session_state:
                 with st.spinner("Generating Strategic Brief..."):
                     st.session_state['exec_brief'] = generate_executive_brief_logic(df_exec)
            st.info(st.session_state['exec_brief'], icon="✨")
                
        with c2:
            st.subheader("🔥 Top 3 Bottlenecks")
            if not top_issues.empty:
                st.bar_chart(top_issues, color="#ff4b4b")
            else:
                st.write("No negative issues found.")
        
        st.divider()
        
        # --- DETAILED ANALYSIS SECTION ---
        target_col = None
        for col in df_exec.columns:
            if col in ["Müşteri Yorumu", "Review", "review", "comments", "Yorum"]:
                target_col = col
                break
        
        if target_col:
            render_dashboard_analysis(df_exec, target_col)
            
            st.divider()
            if st.button("🔄 New Analysis (Clear Data)", type="secondary"):
                del st.session_state['processed_df']
                if 'exec_brief' in st.session_state: del st.session_state['exec_brief']
                st.rerun()
        else:
             if st.button("⚠️ Context Lost - Click to Reset"):
                del st.session_state['processed_df']
                st.rerun()

    # 2. Upload & Process Flow
    elif uploaded_file is not None:
        try:
             df = load_data(uploaded_file)
             st.info("✅ File Loaded. Ready to analyze.")
             st.dataframe(df.head(3))
             
             target_col = None
             possible_cols = ["Müşteri Yorumu", "Review", "review", "comments", "Yorum"]
             for col in df.columns:
                 if col in possible_cols:
                     target_col = col
                     break

             if target_col:
                 current_rules = load_rules()
                 knowledge_base = load_knowledge_base()
                 params = load_params() # Load dynamic SLAs
                 if knowledge_base:
                    st.toast(f"Loaded {len(knowledge_base)} learned patterns.", icon="🧠")

                 # Auto-Start Analysis (No Button)
                 with st.spinner('Automatically analyzing new file with your rules...'):
                     # Call Global process_dataframe
                     df_result = process_dataframe(df, target_col, current_rules, knowledge_base, params)
                     st.session_state['processed_df'] = df_result
                     # Clear old brief
                     if 'exec_brief' in st.session_state: del st.session_state['exec_brief']
                     
                     st.rerun()
             else:
                 st.error("❌ Column 'Müşteri Yorumu' or 'Review' not found.")
        except Exception as e:
            st.error(f"Error loading file: {e}")

    else:
        # Default Landing
        st.header("Welcome to the CX Sentiment Dashboard 👋")
        st.markdown("### 1. Upload File -> 2. Start Analysis -> 3. View Insights")
        st.info("Please upload an Excel or CSV file from the sidebar to begin.")


# ==========================================
# TAB 2: SMART RULES EDITOR (SAME AS BEFORE)
# ==========================================
with tab_rules:
    st.header("🧠 Smart Rules Engine")
    st.markdown("Define your own rules to teach the system specific patterns.")
    
    rules = load_rules()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("👤 Customer Perspective Rules")
        st.info("If review contains keywords -> Assign this Label")
        
        with st.form("add_cust_rule"):
            cust_kw = st.text_input("Keywords (comma separated)", placeholder="online değişim, buton yok")
            cust_lbl = st.text_input("Label to Assign", placeholder="Dijital Eksiklik Talebi")
            submitted_cust = st.form_submit_button("➕ Add Rule")
            
            if submitted_cust and cust_kw and cust_lbl:
                new_rule = {"keywords": [k.strip().lower() for k in cust_kw.split(",")], "label": cust_lbl}
                rules["customer_rules"].append(new_rule)
                save_rules(rules)
                st.success(f"Added: {cust_lbl}")
                st.rerun()
        
        # Display/Delete Rules
        if rules["customer_rules"]:
            st.write("##### Active Rules:")
            for i, rule in enumerate(rules["customer_rules"]):
                c1, c2 = st.columns([4, 1])
                c1.code(f"IF {rule['keywords']} THEN '{rule['label']}'")
                if c2.button("🗑️", key=f"del_cust_{i}"):
                    rules["customer_rules"].pop(i)
                    save_rules(rules)
                    st.rerun()

    with col2:
        st.subheader("🏢 Company Perspective Rules")
        st.info("If review contains keywords -> Assign this Root Cause")
        
        with st.form("add_comp_rule"):
            comp_kw = st.text_input("Keywords (comma separated)", placeholder="stok hatası, temin edilemedi")
            comp_lbl = st.text_input("Root Cause to Assign", placeholder="Stok Yönetimi")
            submitted_comp = st.form_submit_button("➕ Add Rule")
            
            if submitted_comp and comp_kw and comp_lbl:
                new_rule = {"keywords": [k.strip().lower() for k in comp_kw.split(",")], "label": comp_lbl}
                rules["company_rules"].append(new_rule)
                save_rules(rules)
                st.success(f"Added: {comp_lbl}")
                st.rerun()

        # Display/Delete Rules
        if rules["company_rules"]:
            st.write("##### Active Rules:")
            for i, rule in enumerate(rules["company_rules"]):
                c1, c2 = st.columns([4, 1])
                c1.code(f"IF {rule['keywords']} THEN '{rule['label']}'")
                if c2.button("🗑️", key=f"del_comp_{i}"):
                    rules["company_rules"].pop(i)
                    save_rules(rules)
                    st.rerun()

# ==========================================
# TAB 3: OPERATIONAL PARAMETERS (NEW)
# ==========================================
with tab_ops:
    st.header("⚙️ Operasyonel Parametreler (SLA)")
    st.markdown("Tanımladığınız süre kriterlerine göre sistem duygu durumunu otomatik belirler.")
    
    current_params = load_params()
    
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("📦 Kargo & Teslimat")
        max_shipping = st.number_input(
            "Maksimum Kargo Süresi (Gün)", 
            min_value=1, max_value=30, 
            value=current_params.get("max_shipping_days", 3),
            help="Eğer müşteri bu süreden daha az beklediyse 'Nötr/Pozitif' sayılır. Aşarsa 'Negatif' olur."
        )
        
    with c2:
        st.subheader("🏭 Depo & Hazırlık")
        max_warehouse = st.number_input(
            "Maksimum Depo Çıkış Süresi (Gün)", 
            min_value=1, max_value=15, 
            value=current_params.get("max_warehouse_days", 2),
            help="Ürünün hazırlanıp kargoya verilme süresi."
        )
        
    st.divider()
    
    if st.button("💾 Parametreleri Kaydet", type="primary"):
        new_params = {
            "max_shipping_days": max_shipping,
            "max_warehouse_days": max_warehouse
        }
        save_params(new_params)
        st.success("✅ Parametreler güncellendi! Bir sonraki analizde bu süreler dikkate alınacak.")
        
    st.info("""
    **Nasıl Çalışır?**
    Sistem yorumun içinde geçen süre ifadelerini (Örn: "5 gün oldu", "2 iş günü bekledim") yakalar.
    - **Süre <= Limit:** Sistem bunu "Operasyonel Başarı" sayar ve puanı **+0.05 (Pozitif/Nötr)** yapar.
    - **Süre > Limit:** Sistem bunu "SLA Aşımı" sayar ve puanı **-0.60 (Negatif)** yapar.
    """)
