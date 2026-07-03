import streamlit as st
import pandas as pd
from Bio import Entrez
import google.generativeai as genai
import json
import re

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

# --- AI 분석 함수 (텍스트 파싱 기반으로 안정성 대폭 강화) ---
def analyze_paper_with_gemini(api_key, title, abstract, product_name):
    if not abstract: 
        return {"translated_title": title, "comment": "Abstract 미등록에 따른 분석 불가"}
    
    genai.configure(api_key=api_key)
    # 2.0-flash 모델을 사용하여 빠른 속도 유지
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    prompt = f"""
    아래 논문 제목과 초록을 읽고 다음 요구사항을 수행하세요.
    1. 논문 제목을 한국어 학술 용어에 맞게 매끄럽게 한글로 번역하세요.
    2. 자사 품목인 '{product_name}' 관점에서 이 논문이 가지는 학술적/임상적 의미를 1~2줄로 요약하세요.
    
    답변은 반드시 아래 포맷만 정확히 지켜서 작성하세요. 다른 부연 설명은 절대 하지 마세요.
    
    제목: [한글 번역 제목]
    내용: [임상적 의미 요약]
    
    논문 제목: {title}
    초록: {abstract}
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # 정규표현식을 통해 안전하게 대괄호 안의 텍스트만 추출
        title_match = re.search(r"제목:\s*\[(.*?)\]", text)
        comment_match = re.search(r"내용:\s*\[(.*?)\]", text)
        
        translated_title = title_match.group(1).strip() if title_match else ""
        comment = comment_match.group(1).strip() if comment_match else ""
        
        # 정규식 매칭에 실패했을 경우를 위한 2차 방어선 (단순 한 줄씩 분리)
        if not translated_title or not comment:
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            for line in lines:
                if line.startswith("제목:"):
                    translated_title = line.replace("제목:", "").replace("[", "").replace("]", "").strip()
                elif line.startswith("내용:"):
                    comment = line.replace("내용:", "").replace("[", "").replace("]", "").strip()
        
        # 최종 반환 (만약 데이터가 끝까지 비어있다면 원문 및 에러 메시지 매핑)
        return {
            "translated_title": translated_title if translated_title else title,
            "comment": comment if comment else "핵심 코멘트를 추출하지 못했습니다."
        }
    except Exception as e: 
        # API 자체 오류나 차단이 발생했을 때 시스템이 다운되지 않도록 방어
        return {"translated_title": title, "comment": f"AI 분석 오류 (한도 초과 또는 API 차단)"}

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
            with st.expander(f"📂 {res['item']['kor']} ({len(res['papers'])}건)"):
                for i in range(0, len(res['papers']), 3):
                    row_papers = res['papers'][i : i + 3]
                    cols = st.columns(3)
                    for idx, paper in enumerate(row_papers):
                        with cols[idx]:
                            with st.container(border=True):
                                analysis = analyze_paper_with_gemini(gemini_key, paper['title'], paper['abstract'], selected_product)
                                
                                # 기존 요청 디자인 복원
                                st.markdown(f"**[{paper['pub_type']}]** <span style='background-color:#d1ecf1; color:#0c5460; padding:3px 8px; border-radius:5px; font-size:0.85em; font-weight:bold;'>{res['item']['kor']}</span>", unsafe_allow_html=True)
                                st.markdown(f"**{paper['title']}** [[🔗PubMed]](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)")
                                st.markdown("---")
                                st.markdown(f"🔖 {analysis.get('translated_title')}")
                                st.markdown(f"💡 {analysis.get('comment')}")
