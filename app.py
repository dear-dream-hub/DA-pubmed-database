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

# --- AI 분석 함수 (안전 필터 해제 및 파싱 오류 원천 차단) ---
def analyze_paper_with_gemini(api_key, title, abstract, product_name):
    if not abstract: 
        return {"translated_title": title, "comment": "Abstract 미등록에 따른 분석 불가"}
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    # 임상 데이터가 유해 콘텐츠로 오인되어 차단되는 것을 방지합니다.
    safety_settings = {
        'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
        'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
        'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
        'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'
    }
    
    prompt = f"""
    당신은 의학 논문 번역가이자 제약바이오 학술 전문가입니다. 다음 논문을 분석하여 매끄러운 한글 번역 제목과 임상적 의미 요약을 제공하세요.
    논문 제목: {title}
    초록: {abstract}
    자사 품목: {product_name}

    반드시 아래 JSON 형식으로만 답변하세요. 다른 텍스트는 절대 쓰지 마세요.
    {{
        "translated_title": "자연스러운 한글 번역 제목",
        "comment": "자사 품목 '{product_name}' 관점에서의 학술적/임상적 의미 1~2줄 요약"
    }}
    """
    try:
        response = model.generate_content(prompt, safety_settings=safety_settings)
        
        raw_text = response.text
        # 정규표현식을 이용해 불필요한 문장들을 무시하고 오직 { } 안의 내용만 강제 추출합니다.
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        
        if match:
            json_str = match.group(0)
            result = json.loads(json_str)
            
            # 번역이 안 되고 영어가 그대로 나오는 현상을 대비한 2차 방어선
            if not result.get("translated_title") or result.get("translated_title").lower() == title.lower():
                backup_res = model.generate_content(f"다음 영어 의학 논문 제목을 자연스러운 한글로만 번역하세요:\n{title}")
                result["translated_title"] = backup_res.text.strip("[]\"' \n")
                
            return result
        else:
            return {"translated_title": title, "comment": "데이터 추출 실패 (형식 오류)"}
            
    except Exception as e: 
        # 파싱이 실패하더라도 에러로 멈추지 않고 원문 제목을 반환하여 화면을 유지합니다.
        return {"translated_title": title, "comment": f"분석 오류 (한도 초과 또는 차단)"}

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
            # 펼치기 탭에는 한국어 키워드 (res['item']['kor'])
            with st.expander(f"📂 {res['item']['kor']} ({len(res['papers'])}건)"):
                for i in range(0, len(res['papers']), 3):
                    row_papers = res['papers'][i : i + 3]
                    cols = st.columns(3)
                    for idx, paper in enumerate(row_papers):
                        with cols[idx]:
                            with st.container(border=True):
                                analysis = analyze_paper_with_gemini(gemini_key, paper['title'], paper['abstract'], selected_product)
                                
                                # 태그에는 영어 키워드 (res['item']['eng'])
                                st.markdown(f"**[{paper['pub_type']}]** <span style='background-color:#d1ecf1; color:#0c5460; padding:3px 8px; border-radius:5px; font-size:0.85em; font-weight:bold;'>{res['item']['eng']}</span>", unsafe_allow_html=True)
                                st.markdown(f"**{paper['title']}** [[🔗PubMed]](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)")
                                st.markdown("---")
                                st.markdown(f"🔖 {analysis.get('translated_title')}")
                                st.markdown(f"💡 {analysis.get('comment')}")
