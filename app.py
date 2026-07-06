import streamlit as st
import pandas as pd
from Bio import Entrez
import google.generativeai as genai
import json
import re
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

# --- 근거 수준(Hierarchy of Evidence) 스코어링 함수 ---
def get_evidence_score(pub_types, title, abstract):
    text = (title + " " + abstract).lower()
    pub_types_lower = [str(pt).lower() for pt in pub_types]
    
    # 1. 3차/권고 문헌 (최우선 순위)
    if any(pt in pub_types_lower for pt in ['practice guideline', 'guideline', 'consensus development conference']):
        return 90, "Guideline/Consensus"
    if 'guideline' in text or 'consensus' in text:
        return 85, "Guideline/Consensus"
        
    # 2. 2차 문헌
    if any('meta-analysis' in pt for pt in pub_types_lower):
        return 80, "Meta-Analysis"
    if any('systematic review' in pt for pt in pub_types_lower):
        return 75, "Systematic Review"
    if 'meta-analysis' in text or 'systematic review' in text:
        return 70, "Review/Meta-Analysis"
        
    # 3. 1차 문헌
    if any('randomized controlled trial' in pt for pt in pub_types_lower):
        return 60, "RCT"
    if 'randomized controlled trial' in text or 'rct' in text.split():
        return 55, "RCT"
        
    if any('cohort' in pt for pt in pub_types_lower) or 'cohort' in text:
        return 50, "Cohort Study"
        
    if 'case-control' in text:
        return 40, "Case-Control"
        
    if any('observational study' in pt for pt in pub_types_lower) or 'observational' in text or 'retrospective' in text:
        return 30, "Observational Study"
        
    if 'case series' in text:
        return 20, "Case Series"
        
    if any('case report' in pt for pt in pub_types_lower) or 'case report' in text:
        return 10, "Case Report"
        
    # Default (기타 문헌)
    if pub_types:
        return 5, str(pub_types[0])
    return 0, "Journal Article"

# --- 검색 함수 ---
def search_pubmed(keyword, days=7, max_results=50): # 정렬 풀(pool)을 확보하기 위해 내부 검색량을 50건으로 확장
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
                
                pub_types = []
                if 'PublicationTypeList' in article['MedlineCitation']['Article']:
                    pub_types = article['MedlineCitation']['Article']['PublicationTypeList']
                
                # 점수 및 출판물 유형 추출
                score, display_type = get_evidence_score(pub_types, title, abstract)
                
                papers.append({
                    'title': title, 
                    'pmid': pmid, 
                    'abstract': abstract, 
                    'pub_type': display_type,
                    'evidence_score': score
                })
        return papers
    except: return []

# --- AI 분석 함수 (가장 안정적이었던 초기 오리지널 프롬프트 복원) ---
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
        time.sleep(1.5) # API 429 에러 방지 안심 버퍼
        response = model.generate_content(prompt)
        result_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(result_text)
    except Exception as e:
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
    with st.spinner("PubMed 데이터 수집 중... (최대 50건 확보 및 신뢰도 분석)"):
        for item in keyword_mapping:
            # 넉넉하게 50건을 검색해서 신뢰도 순으로 거릅니다.
            papers = search_pubmed(item['eng'], days=7 if selected_period=="최근 일주일" else 30, max_results=50)
            search_results.append({'item': item, 'papers': papers})

    # [핵심] 고유 PMID 기준 논문 중복 제거 및 검색 매핑
    pmid_to_paper = {}
    pmid_to_keywords = {}
    
    for res in search_results:
        item = res['item']
        for paper in res['papers']:
            pmid = paper['pmid']
            if pmid not in pmid_to_paper:
                pmid_to_paper[pmid] = paper
            if pmid not in pmid_to_keywords:
                pmid_to_keywords[pmid] = []
            pmid_to_keywords[pmid].append(item)
            
    # 동일한 키워드 세트를 가진 논문끼리 완벽 그룹화
    from collections import defaultdict
    combo_groups = defaultdict(list)
    
    for pmid, keywords in pmid_to_keywords.items():
        sorted_keywords = sorted(keywords, key=lambda x: x['kor'])
        combo_key = tuple(k['kor'] for k in sorted_keywords)
        combo_groups[combo_key].append((pmid, sorted_keywords))
        
    # 출력 구조용 데이터 가공 (신뢰도 정렬 및 Top 9 슬라이싱)
    processed_groups = []
    for combo_key, paper_list in combo_groups.items():
        papers_in_group = [pmid_to_paper[pmid] for pmid, _ in paper_list]
        
        # 1. 해당 조합 그룹 내에서 '신뢰도 점수(evidence_score)' 최상위 순으로 정렬
        papers_in_group.sort(key=lambda x: x['evidence_score'], reverse=True)
        
        total_count = len(papers_in_group)
        # 2. 최대 9건만 잘라서 노출 데이터로 확정
        display_papers = papers_in_group[:9] 
        
        sorted_items = paper_list[0][1]
        kor_title = " & ".join([k['kor'] for k in sorted_items])
        eng_title = " & ".join([k['eng'] for k in sorted_items])
        
        processed_groups.append({
            'kor_title': kor_title,
            'eng_title': eng_title,
            'total_count': total_count,
            'display_papers': display_papers,
            'overlap_count': len(sorted_items)
        })
        
    # 조합별 정렬 우선순위: 1단계 - 중첩 키워드 / 2단계 - 노출 논문 수
    active_results = sorted(processed_groups, key=lambda x: (x['overlap_count'], len(x['display_papers'])), reverse=True)

    if not active_results: st.info("업데이트된 논문이 없습니다.")
    else:
        st.subheader("📈 논문 업데이트 현황")
        for res in active_results:
            
            # (9건+a) 표기 로직 적용
            if res['total_count'] > 9:
                count_label = f"상위 9건+a (총 {res['total_count']}건 검색됨)"
            else:
                count_label = f"{res['total_count']}건"
                
            with st.expander(f"📂 {res['kor_title']} ({count_label})"):
                for i in range(0, len(res['display_papers']), 3):
                    row_papers = res['display_papers'][i : i + 3]
                    cols = st.columns(3)
                    for idx, paper in enumerate(row_papers):
                        with cols[idx]:
                            with st.container(border=True):
                                analysis = analyze_paper_with_gemini(gemini_key, paper['title'], paper['abstract'], selected_product)
                                
                                # 문헌 종류를 새롭게 부여한 신뢰도 뱃지 이름(paper['pub_type'])으로 표기
                                st.markdown(f"**[{paper['pub_type']}]** <span style='background-color:#d1ecf1; color:#0c5460; padding:3px 8px; border-radius:5px; font-size:0.85em; font-weight:bold;'>{res['eng_title']}</span>", unsafe_allow_html=True)
                                st.markdown(f"**{paper['title']}** [[🔗PubMed]](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)")
                                st.markdown("---")
                                st.markdown(f"🔖 {analysis.get('translated_title')}")
                                st.markdown(f"💡 {analysis.get('comment')}")
