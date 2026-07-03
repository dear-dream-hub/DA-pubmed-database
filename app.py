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

# --- AI 분석 함수 (한글 번역 및 파싱 로직 대폭 강화) ---
def analyze_paper_with_gemini(api_key, title, abstract, product_name):
    if not abstract: 
        return {"translated_title": "[초록 없음] " + title, "comment": "Abstract 미등록에 따른 분석 불가"}
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    prompt = f"""
    당신은 제약바이오 학술 전문가이자 의학 전문 번역가입니다. 아래 논문의 제목(영어)과 초록을 읽고 다음 두 가지를 작성하세요.
    
    1. 논문 제목(영어)을 한국어 의학/임상 학술 용어에 맞게 자연스럽고 매끄러운 한글로 번역하세요. (절대 영어 그대로 두지 마세요)
    2. 자사 품목인 '{product_name}' 관점에서 이 논문이 가지는 학술적/임상적 핵심 의미를 1~2줄로 요약하세요.
    
    반드시 아래의 형식을 정확히 지켜서 응답하세요. 다른 설명은 생략하세요.
    
    번역제목: 한글로 번역된 논문 제목
    요약내용: 임상적 의미 요약문
    
    논문 제목: {title}
    초록: {abstract}
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        translated_title = ""
        comment = ""
        
        # 줄바꿈 단위로 쪼개어 가장 확실하게 키워드 매칭 파싱
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        for line in lines:
            # AI가 대괄호 등을 임의로 붙일 경우를 대비해 특수문자 제거 처리 포함
            if line.startswith("번역제목:") or line.startswith("번역제목"):
                translated_title = re.sub(r"^번역제목:\s*", "", line)
                translated_title = translated_title.strip("[]\"' ")
            elif line.startswith("요약내용:") or line.startswith("요약내용"):
                comment = re.sub(r"^요약내용:\s*", "", line)
                comment = comment.strip("[]\"' ")
                
        # 만약 한 줄 텍스트 매칭도 안 되었다면 정규식 시도
        if not translated_title:
            t_match = re.search(r"번역제목\s*:\s*(.*)", text)
            if t_match: translated_title = t_match.group(1).strip("[]\"' ")
            
        if not comment:
            c_match = re.search(r"요약내용\s*:\s*(.*)", text)
            if c_match: comment = c_match.group(1).strip("[]\"' ")

        # 파싱은 성공했으나 번역 결과가 기존 영어 제목과 완전히 똑같거나 비어있는 상황 방어
        if not translated_title or translated_title.lower() == title.lower():
            # 3차 방어선: 강제로 제목만 단독 번역 요청
            direct_prompt = f"다음 영어 의학 논문 제목을 자연스러운 한글로만 번역해서 출력하세요.\n논문 제목: {title}"
            direct_res = model.generate_content(direct_prompt)
            translated_title = direct_res.text.strip("[]\"' ")

        return {
            "translated_title": translated_title if translated_title else "번역 오류 (원문 확인 요망)",
            "comment": comment if comment else "임상적 의미 요약 코멘트를 추출하지 못했습니다."
        }
    except Exception as e: 
        return {"translated_title": "번역 실패 (API 오류)", "comment": "AI 분석 중 오류가 발생했습니다."}

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
                                
                                st.markdown(f"**[{paper['pub_type']}]** <span style='background-color:#d1ecf1; color:#0c5460; padding:3px 8px; border-radius:5px; font-size:0.85em; font-weight:bold;'>{res['item']['kor']}</span>", unsafe_allow_html=True)
                                st.markdown(f"**{paper['title']}** [[🔗PubMed]](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)")
                                st.markdown("---")
                                st.markdown(f"🔖 {analysis.get('translated_title')}")
                                st.markdown(f"💡 {analysis.get('comment')}")
