import streamlit as st
import pandas as pd
from Bio import Entrez
import google.generativeai as genai
import json

# --- 기본 설정 ---
st.set_page_config(page_title="Weekly Update 대시보드", layout="wide")
Entrez.email = "your_email@example.com"

# --- 데이터 로드 ---
@st.cache_data
def load_data():
    df_kor = pd.read_excel("database.xlsx", sheet_name="한글")
    df_eng = pd.read_excel("database.xlsx", sheet_name="영어")
    df_kor[['팀', '파트', '품목']] = df_kor[['팀', '파트', '품목']].ffill()
    df_eng[['팀', '파트', '품목']] = df_eng[['팀', '파트', '품목']].ffill()
    return df_kor, df_eng

# --- 검색 함수 ---
def search_pubmed(keyword, days=7, max_results=9):
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
    except: return []

# --- AI 분석 함수 (오류 방지를 위한 JSON 강제화 및 2중 구조) ---
def analyze_paper_with_gemini(api_key, title, abstract, product_name):
    if not abstract: 
        return {"translated_title": "[초록 미등록] " + title, "comment": "Abstract 미등록에 따른 분석 불가"}
    
    genai.configure(api_key=api_key)
    # 완벽한 JSON 출력을 위해 시스템 레벨에서 형식을 강제 지정합니다.
    model = genai.GenerativeModel(
        model_name='gemini-2.0-flash',
        generation_config={"response_mime_type": "application/json"}
    )
    
    prompt = f"""
    당신은 의학 논문 번역가이자 제약바이오 학술 전문가입니다. 다음 논문을 분석하여 의학 용어에 맞는 매끄러운 한글 번역 제목과 임상적 의미 요약을 제공하세요.
    응답은 반드시 지정된 JSON 포맷을 준수해야 하며, JSON 외의 텍스트를 포함해서는 안 됩니다.

    논문 제목: {title}
    초록: {abstract}
    자사 품목: {product_name}

    정확히 다음 JSON 스키마 구조로만 답변하세요:
    {{
        "translated_title": "논문 제목의 자연스러운 한글 번역 (절대 영어 원문을 그대로 출력하지 마십시오)",
        "comment": "자사 품목 '{product_name}' 관점에서의 학술적/임상적 의미 1~2줄 요약"
    }}
    """
    try:
        response = model.generate_content(prompt)
        result = json.loads(response.text.strip())
        
        # 2차 방어: 구조는 만들어졌으나 번역이 누락되어 기존 영어와 같을 경우 예외 처리
        if not result.get("translated_title") or result.get("translated_title").lower() == title.lower():
            backup_model = genai.GenerativeModel('gemini-2.0-flash')
            backup_res = backup_model.generate_content(f"다음 영어 의학 논문 제목을 자연스러운 한글로만 번역하세요. 다른 말은 쓰지 마세요:\n{title}")
            result["translated_title"] = backup_res.text.strip("[]\"' ")
            
        return result
    except: 
        return {"translated_title": "번역 실패 (파싱 오류)", "comment": "AI 분석 중 일시적인 오류가 발생했습니다."}

# --- 사이드바 ---
with st.sidebar:
    st.header("⚙️ 대시보드 설정")
    gemini_key = st.text_input("🔑 Gemini API Key", type="password")
    df_kor, df_eng = load_data()
    selected_team = st.selectbox("1. 팀", df_kor['팀'].dropna().unique())
    selected_part = st.selectbox("2. 파트", df_kor[df_kor['팀'] == selected_team]['파트'].dropna().unique())
    selected_product = st.selectbox("3. 품목", df_kor[(df_kor['팀'] == selected_team) & (df_kor['파트'] == selected_part)]['품목'].dropna().unique())
    selected_period = st.selectbox("4. 기간", ["최근 일주일", "최근 한 달"])

# --- 메인 로직 ---
st.title(f"📊 {selected_product} Weekly Update")

if st.button("🚀 분석 시작", type="primary"):
    if not gemini_key: st.error("⚠️ API Key를 입력하세요!"); st.stop()
    
    keyword_mapping = []
    for col in ['관련질환', '경쟁성분', '관련계열', '관련품목', '기타']:
        if col in df_eng.columns:
            for e, k in zip(df_eng[(df_eng['팀'] == selected_team) & (df_eng['파트'] == selected_part) & (df_eng['품목'] == selected_product)][col].dropna(), 
                            df_kor[(df_kor['팀'] == selected_team) & (df_kor['파트'] == selected_part) & (df_kor['품목'] == selected_product)][col].dropna()):
                keyword_mapping.append({'category': col, 'kor': k, 'eng': e})
    
    search_results = []
    with st.spinner("PubMed 데이터 수집 중..."):
        for item in keyword_mapping:
            papers = search_pubmed(item['eng'], days=7 if selected_period=="최근 일주일" else 30, max_results=9)
            search_results.append({'item': item, 'papers': papers})

    active_results = sorted([res for res in search_results if len(res['papers']) > 0], key=lambda x: len(x['papers']), reverse=True)

    if not active_results: st.info("업데이트된 논문이 없습니다.")
    else:
        st.subheader("📈 논문 업데이트 현황")
        for res in active_results:
            # st.expander 제목에는 한국어 키워드(res['item']['kor']) 적용
            with st.expander(f"📂 {res['item']['kor']} ({len(res['papers'])}건)"):
                for i in range(0, len(res['papers']), 3):
                    row_papers = res['papers'][i : i + 3]
                    cols = st.columns(3)
                    for idx, paper in enumerate(row_papers):
                        with cols[idx]:
                            with st.container(border=True):
                                analysis = analyze_paper_with_gemini(gemini_key, paper['title'], paper['abstract'], selected_product)
                                
                                # 문헌 종류 옆의 키워드 마크다운은 영어 키워드(res['item']['eng'])로 변경 적용
                                st.markdown(f"**[{paper['pub_type']}]** <span style='background-color:#d1ecf1; color:#0c5460; padding:3px 8px; border-radius:5px; font-size:0.85em; font-weight:bold;'>{res['item']['eng']}</span>", unsafe_allow_html=True)
                                st.markdown(f"**{paper['title']}** [[🔗PubMed]](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)")
                                st.markdown("---")
                                st.markdown(f"🔖 {analysis.get('translated_title')}")
                                st.markdown(f"💡 {analysis.get('comment')}")
