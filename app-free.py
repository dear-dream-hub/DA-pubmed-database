import streamlit as st
import pandas as pd
from Bio import Entrez
import json

# --- 기본 설정 ---
st.set_page_config(page_title="Weekly Update 대시보드 (무제한 버전)", layout="wide")
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
        
    if pub_types:
        return 5, str(pub_types[0])
    return 0, "Journal Article"

# --- 검색 함수 (최대 50건 풀 확보) ---
def search_pubmed(keyword, days=7, max_results=50):
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

# --- 사이드바 (🔑 API Key 입력란 완전 제거) ---
with st.sidebar:
    st.header("⚙️ 대시보드 설정")
    df_kor, df_eng = load_data()
    selected_team = st.selectbox("1. 팀", df_kor['팀'].dropna().unique())
    selected_part = st.selectbox("2. 파트", df_kor[df_kor['팀'] == selected_team]['파트'].dropna().unique())
    selected_product = st.selectbox("3. 품목", df_kor[(df_kor['팀'] == selected_team) & (df_kor['파트'] == selected_part)]['품목'].dropna().unique())
    selected_period = st.selectbox("4. 기간", ["최근 일주일", "최근 한 달"])

# --- 메인 로직 ---
st.title(f"📊 {selected_product} Weekly Update (무제한)")

if st.button("🚀 논문 업데이트 시작", type="primary"):
    keyword_mapping = []
    for col in ['관련질환', '경쟁성분', '관련계열', '관련품목', '기타']:
        if col in df_eng.columns:
            for e, k in zip(df_eng[(df_eng['팀'] == selected_team) & (df_eng['파트'] == selected_part) & (df_eng['품목'] == selected_product)][col].dropna(), 
                            df_kor[(df_kor['팀'] == selected_team) & (df_kor['파트'] == selected_part) & (df_kor['품목'] == selected_product)][col].dropna()):
                keyword_mapping.append({'category': col, 'kor': k, 'eng': e})
    
    search_results = []
    with st.spinner("PubMed 데이터 수집 및 신뢰도 분석 중..."):
        for item in keyword_mapping:
            papers = search_pubmed(item['eng'], days=7 if selected_period=="최근 일주일" else 30, max_results=50)
            search_results.append({'item': item, 'papers': papers})

    # 고유 PMID 기준 논문 중복 제거 및 검색 매핑
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
        
        # 근거 수준 점수 기준 내림차순 정렬
        papers_in_group.sort(key=lambda x: x['evidence_score'], reverse=True)
        
        total_count = len(papers_in_group)
        display_papers = papers_in_group[:9] # 상위 9건만 슬라이싱
        
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
        
    # 중첩 키워드 수 순서로 정렬
    active_results = sorted(processed_groups, key=lambda x: (x['overlap_count'], len(x['display_papers'])), reverse=True)

    if not active_results: st.info("업데이트된 논문이 없습니다.")
    else:
        st.subheader("📈 논문 업데이트 현황")
        for res in active_results:
            
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
                                # 디자인 시스템 완벽 유지 (AI 번역 및 요약 란만 컴팩트하게 제거)
                                st.markdown(f"**[{paper['pub_type']}]** <span style='background-color:#d1ecf1; color:#0c5460; padding:3px 8px; border-radius:5px; font-size:0.85em; font-weight:bold;'>{res['eng_title']}</span>", unsafe_allow_html=True)
                                st.markdown(f"**{paper['title']}** [[🔗PubMed]](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)")
