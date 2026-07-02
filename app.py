import streamlit as st
import pandas as pd
from Bio import Entrez
import google.generativeai as genai
import json
import os

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
                
                pub_type = "Article"
                if 'PublicationTypeList' in article['MedlineCitation']['Article']:
                    pub_types = article['MedlineCitation']['Article']['PublicationTypeList']
                    if pub_types: pub_type = str(pub_types[0])
                papers.append({'title': title, 'pmid': pmid, 'abstract': abstract, 'pub_type': pub_type})
        return papers
    except Exception:
        return []

# --- 함수 3: Gemini AI 분석 ---
def analyze_paper_with_gemini(api_key, title, abstract, product_name):
    if not abstract:
        return {"translated_title": "분석 불가", "comment": "Abstract 미등록에 따른 분석 불가"}
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    prompt = f"""
    당신은 제약 바이오 학술 전문가입니다. 다음 논문이 '{product_name}'에 미치는 학술적 의미를 JSON으로 요약하세요.
    제목: {title}
    초록: {abstract}
    반드시 마크다운 없이 JSON 형식으로만 답하세요.
    {{"translated_title": "한글 번역 제목", "comment": "핵심 의미 1~2줄 요약"}}
    """
    try:
        response = model.generate_content(prompt)
        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except:
        return {"translated_title": "분석 실패", "comment": "분석 중 오류 발생"}

# --- 메인 UI ---
with st.sidebar:
    st.header("⚙️ 대시보드 설정")
    gemini_key = os.environ.get("GEMINI_API_KEY") or st.text_input("🔑 Gemini API Key", type="password")
    df_kor, df_eng = load_data()
    st.header("📂 품목 선택")
    selected_team = st.selectbox("1. 팀", df_kor['팀'].dropna().unique())
    selected_part = st.selectbox("2. 파트", df_kor[df_kor['팀'] == selected_team]['파트'].dropna().unique())
    selected_product = st.selectbox("3. 품목", df_kor[(df_kor['팀'] == selected_team) & (df_kor['파트'] == selected_part)]['품목'].dropna().unique())
    selected_period = st.selectbox("4. 기간", ["최근 일주일", "최근 한 달"])

# 키워드 매핑
keyword_mapping = []
for col in ['관련질환', '경쟁성분', '관련계열', '관련품목', '기타']:
    if col in df_eng.columns:
        for e, k in zip(df_eng[(df_eng['팀'] == selected_team) & (df_eng['파트'] == selected_part) & (df_eng['품목'] == selected_product)][col].dropna(), 
                        df_kor[(df_kor['팀'] == selected_team) & (df_kor['파트'] == selected_part) & (df_kor['품목'] == selected_product)][col].dropna()):
            keyword_mapping.append({'category': col, 'kor': k, 'eng': e})

st.title(f"📊 {selected_product} Weekly Update")
if st.button("🚀 분석 시작", type="primary"):
    if not gemini_key: st.error("API Key 필요"); st.stop()
    
    search_results = []
    with st.spinner("PubMed 데이터 수집 중..."):
        for item in keyword_mapping:
            papers = search_pubmed(item['eng'], days=7 if selected_period=="최근 일주일" else 30)
            search_results.append({'item': item, 'papers': papers})

    # [디자인] 결과 정렬 및 0건 제거
    active_results = sorted([res for res in search_results if len(res['papers']) > 0], key=lambda x: len(x['papers']), reverse=True)

    if not active_results:
        st.info("해당 기간 내 업데이트된 논문이 없습니다.")
    else:
        st.subheader("📈 논문 업데이트 현황")
        for res in active_results:
            with st.expander(f"📂 {res['item']['kor']} ({len(res['papers'])}건)"):
                for paper in res['papers']:
                    analysis = analyze_paper_with_gemini(gemini_key, paper['title'], paper['abstract'], selected_product)
                    st.markdown(f"**{paper['title']}**")
                    st.caption(f"🔖 {analysis.get('translated_title')}")
                    st.write(f"💡 {analysis.get('comment')}")
                    st.markdown(f"[🔗 PubMed 링크](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)")
                    st.markdown("---")
