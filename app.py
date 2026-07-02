import streamlit as st
import pandas as pd
from Bio import Entrez
import google.generativeai as genai
import json
import os

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

# --- 분석 함수 ---
def analyze_paper_with_gemini(api_key, title, abstract, product_name):
    if not abstract: return {"translated_title": "분석 불가", "comment": "Abstract 미등록"}
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    prompt = f"논문 제목: {title}\n초록: {abstract}\n'{product_name}' 관점 분석. JSON 응답: {{\"translated_title\": \"...\", \"comment\": \"...\"}}"
    try:
        response = model.generate_content(prompt)
        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except: return {"translated_title": "분석 실패", "comment": "오류 발생"}

# --- 사이드바 및 UI ---
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
    if not gemini_key: st.error("⚠️ API Key가 없습니다!"); st.stop()
    
    # 데이터 매핑
    keyword_mapping = []
    for col in ['관련질환', '경쟁성분', '관련계열', '관련품목', '기타']:
        if col in df_eng.columns:
            for e, k in zip(df_eng[(df_eng['팀'] == selected_team) & (df_eng['파트'] == selected_part) & (df_eng['품목'] == selected_product)][col].dropna(), 
                            df_kor[(df_kor['팀'] == selected_team) & (df_kor['파트'] == selected_part) & (df_kor['품목'] == selected_product)][col].dropna()):
                keyword_mapping.append({'category': col, 'kor': k, 'eng': e})

    search_results = []
    with st.spinner("PubMed 데이터 수집 및 분석 중..."):
        for item in keyword_mapping:
            # 검색 후 결과 리스트 반환 (생략된 검색 로직은 이전과 동일하게 유지)
            # (이곳에 기존 search_pubmed 함수 내용을 포함하세요)
            papers = search_pubmed(item['eng'], days=7 if selected_period=="최근 일주일" else 30)
            search_results.append({'item': item, 'papers': papers})

    # [수정] 0건 제거 및 건수 기준 내림차순 정렬
    active_results = sorted([res for res in search_results if len(res['papers']) > 0], key=lambda x: len(x['papers']), reverse=True)

    if not active_results: st.info("업데이트된 논문이 없습니다.")
    else:
        st.subheader("📈 논문 업데이트 현황")
        for res in active_results:
            # 펼치기 전까지는 제목과 건수만 표시
            with st.expander(f"📂 {res['item']['kor']} ({len(res['papers'])}건)"):
                # [수정] 가로 3열 나열 (3개씩 끊어서 행 생성)
                cols_per_row = 3
                for i in range(0, len(res['papers']), cols_per_row):
                    row_papers = res['papers'][i : i + cols_per_row]
                    cols = st.columns(cols_per_row)
                    for idx, paper in enumerate(row_papers):
                        with cols[idx]:
                            with st.container(border=True):
                                analysis = analyze_paper_with_gemini(gemini_key, paper['title'], paper['abstract'], selected_product)
                                # [수정] 기존 디자인 복원
                                st.markdown(f"**[{paper.get('pub_type', 'Article')}]** <span style='background-color:#d1ecf1; color:#0c5460; padding:3px 8px; border-radius:5px; font-size:0.85em; font-weight:bold;'>{res['item']['kor']}</span>", unsafe_allow_html=True)
                                st.markdown(f"**{paper['title']}** [[🔗PubMed]](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)")
                                st.markdown("---")
                                st.markdown(f"🔖 {analysis.get('translated_title')}")
                                st.markdown(f"💡 {analysis.get('comment')}")
