import streamlit as st
import pandas as pd
from Bio import Entrez
import google.generativeai as genai
import json

# --- 기본 설정 ---
st.set_page_config(page_title="Weekly Update 대시보드", layout="wide")
Entrez.email = "your_email@example.com"

# --- 함수 1: 데이터 불러오기 ---
@st.cache_data
def load_data():
    df_kor = pd.read_excel("database.xlsx", sheet_name="한글")
    df_eng = pd.read_excel("database.xlsx", sheet_name="영어")
    df_kor[['팀', '파트', '품목']] = df_kor[['팀', '파트', '품목']].ffill()
    df_eng[['팀', '파트', '품목']] = df_eng[['팀', '파트', '품목']].ffill()
    return df_kor, df_eng

# --- 함수 2: PubMed 논문 검색 ---
def search_pubmed(keyword, days=7, max_results=3):
    query = f'("{keyword}"[Title/Abstract])'
    try:
        handle = Entrez.esearch(db="pubmed", term=query, reldate=days, datetype="edat", retmax=max_results)
        record = Entrez.read(handle)
        handle.close()
        
        id_list = record["IdList"]
        papers = []
        if id_list:
            handle = Entrez.efetch(db="pubmed", id=id_list, retmode="xml")
            records = Entrez.read(handle)
            handle.close()
            
            for article in records['PubmedArticle']:
                title = article['MedlineCitation']['Article']['ArticleTitle']
                pmid = str(article['MedlineCitation']['PMID'])
                
                abstract = ""
                if 'Abstract' in article['MedlineCitation']['Article']:
                    abstract_texts = article['MedlineCitation']['Article']['Abstract']['AbstractText']
                    abstract = " ".join([str(text) for text in abstract_texts])
                
                pub_type = "Journal Article"
                if 'PublicationTypeList' in article['MedlineCitation']['Article']:
                    pub_types = article['MedlineCitation']['Article']['PublicationTypeList']
                    if pub_types:
                        pub_type = str(pub_types[0])

                papers.append({'title': title, 'pmid': pmid, 'abstract': abstract, 'pub_type': pub_type})
        return papers
    except Exception as e:
        return []

# --- 함수 3: Gemini AI 분석 ---
def analyze_paper_with_gemini(api_key, title, abstract, product_name):
    if not abstract:
        return {"translated_title": "분석 불가", "comment": "Abstract 미등록에 따른 분석 불가"}
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    당신은 제약 바이오 학술 전문가입니다. 다음 논문의 제목과 초록을 읽고, 자사 품목인 '{product_name}'과의 연관성을 분석해주세요.
    논문 제목: {title}
    초록: {abstract}
    
    반드시 아래 JSON 형식으로만 답변하세요. 다른 설명은 생략하세요.
    {{
        "translated_title": "논문 제목의 매끄러운 한글 번역",
        "comment": "이 논문이 '{product_name}'의 관점에서 어떤 학술적/임상적 의미가 있는지 분석한 1~2줄의 핵심 코멘트"
    }}
    """
    try:
        response = model.generate_content(prompt)
        result_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(result_text)
    except Exception:
        return {"translated_title": "분석 불가", "comment": "분석 처리 중 오류 발생"}

# ==========================================
# UI 구성
# ==========================================
with st.sidebar:
    st.header("⚙️ 대시보드 설정")
    gemini_key = st.text_input("🔑 Gemini API Key를 입력하세요", type="password")
    st.divider()
    
    df_kor, df_eng = load_data()

    st.header("📂 품목 선택")
    selected_team = st.selectbox("1. 팀 선택", df_kor['팀'].dropna().unique())
    selected_part = st.selectbox("2. 파트 선택", df_kor[df_kor['팀'] == selected_team]['파트'].dropna().unique())
    selected_product = st.selectbox("3. 품목 선택", df_kor[(df_kor['팀'] == selected_team) & (df_kor['파트'] == selected_part)]['품목'].dropna().unique())
    
    # 수정사항 4: 기간 설정 추가
    period_map = {"최근 일주일": 7, "최근 한 달": 30}
    selected_period = st.selectbox("4. 기간 설정", list(period_map.keys()))

# 키워드 매핑
target_rows_eng = df_eng[(df_eng['팀'] == selected_team) & (df_eng['파트'] == selected_part) & (df_eng['품목'] == selected_product)]
target_rows_kor = df_kor[(df_kor['팀'] == selected_team) & (df_kor['파트'] == selected_part) & (df_kor['품목'] == selected_product)]
keyword_mapping = []
for col in ['관련질환', '경쟁성분', '관련계열', '관련품목', '기타']:
    if col in target_rows_eng.columns:
        for e, k in zip(target_rows_eng[col].dropna(), target_rows_kor[col].dropna()):
            keyword_mapping.append({'category': col, 'kor': k, 'eng': e})

st.title(f"📊 {selected_product} Weekly Update")
st.write(f"**선택 경로:** {selected_team} > {selected_part} > {selected_product}")
st.divider()

if st.button(f"🚀 {selected_period} 논문 업데이트 및 AI 분석 시작", type="primary", use_container_width=True):
    if not gemini_key:
        st.error("⚠️ Gemini API Key를 입력해주세요!")
        st.stop()
        
    search_results = []
    with st.spinner("PubMed에서 최신 논문을 수집하고 있습니다..."):
        for item in keyword_mapping:
            papers = search_pubmed(item['eng'], days=period_map[selected_period], max_results=3)
            search_results.append({'item': item, 'papers': papers})
            
    st.markdown("### 📈 키워드별 논문 업데이트 요약")
    summary_cols = st.columns(len(search_results))
    for idx, res in enumerate(search_results):
        with summary_cols[idx]:
            # 수정사항 1: 한국어(영어) 키워드 표시
            label_text = f"{res['item']['kor']}\n({res['item']['eng']})"
            st.metric(label=label_text, value=f"{len(res['papers'])}건")
    
    st.divider()
    st.markdown("### 📑 AI 분석 리포트")
    for res in search_results:
        if res['papers']:
            st.markdown(f"#### 📂 {res['item']['category']} : {res['item']['kor']}")
            paper_cols = st.columns(len(res['papers']))
            for idx, paper in enumerate(res['papers']):
                with paper_cols[idx]:
                    with st.container(border=True):
                        analysis = analyze_paper_with_gemini(gemini_key, paper['title'], paper['abstract'], selected_product)
                        st.markdown(f"**[{paper.get('pub_type', 'Article')}]** <span style='background-color:#d1ecf1; color:#0c5460; padding:3px 8px; border-radius:5px; font-size:0.85em; font-weight:bold;'>{res['item']['kor']}</span> <br><br> **{paper['title']}** [[🔗PubMed]](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)", unsafe_allow_html=True)
                        st.markdown("---")
                        st.markdown(f"🔖 **{analysis.get('translated_title')}**")
                        st.markdown(f"💡 {analysis.get('comment')}")