import streamlit as st
import pandas as pd
from Bio import Entrez
import google.generativeai as genai
import json
import time

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

# --- AI 분석 함수 (초기 성공 버전 프롬프트 및 파싱 로직 복원) ---
def analyze_paper_with_gemini(api_key, title, abstract, product_name):
    if not abstract:
        return {"translated_title": "분석 불가", "comment": "Abstract 미등록에 따른 분석 불가"}
    
    genai.configure(api_key=api_key)
    # 초기에 가장 잘 돌아갔던 2.5-flash 모델로 세팅합니다.
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # 초기에 성공했던 오리지널 프롬프트 구조 그대로 복원
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
        # 무차별 다량 호출로 인한 API 차단(429 에러) 방지용 안심 버퍼
        time.sleep(1.5)
        
        response = model.generate_content(prompt)
        # 초기에 성공했던 문자열 치환 가공 처리 방식 복원
        result_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(result_text)
    except Exception as e:
        # 오류 발생 시 시스템이 멈추지 않도록 안전하게 원문 매핑
        return {"translated_title": title, "comment": "분석 처리 중 오류가 발생하여 원문으로 대체합니다."}

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

    # 0건 제거 및 건수 많은 순 정렬 시스템 유지
    active_results = sorted([res for res in search_results if len(res['papers']) > 0], key=lambda x: len(x['papers']), reverse=True)

    if not active_results: st.info("업데이트된 논문이 없습니다.")
    else:
        st.subheader("📈 논문 업데이트 현황")
        for res in active_results:
            # 외부 파일 아이콘 옆에는 한국어 키워드 유지
            with st.expander(f"📂 {res['item']['kor']} ({len(res['papers'])}건)"):
                # 가로 3열 배치 시스템 유지
                for i in range(0, len(res['papers']), 3):
                    row_papers = res['papers'][i : i + 3]
                    cols = st.columns(3)
                    for idx, paper in enumerate(row_papers):
                        with cols[idx]:
                            with st.container(border=True):
                                analysis = analyze_paper_with_gemini(gemini_key, paper['title'], paper['abstract'], selected_product)
                                
                                # 문헌 종류 옆 배지 내부에는 영어 키워드 출력 유지
                                st.markdown(f"**[{paper['pub_type']}]** <span style='background-color:#d1ecf1; color:#0c5460; padding:3px 8px; border-radius:5px; font-size:0.85em; font-weight:bold;'>{res['item']['eng']}</span>", unsafe_allow_html=True)
                                st.markdown(f"**{paper['title']}** [[🔗PubMed]](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)")
                                st.markdown("---")
                                st.markdown(f"🔖 {analysis.get('translated_title')}")
                                st.markdown(f"💡 {analysis.get('comment')}")
