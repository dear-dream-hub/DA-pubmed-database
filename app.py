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

# --- AI 분석 함수 (가장 강력하고 안정적인 버전 적용) ---
def analyze_paper_with_gemini(api_key, title, abstract, product_name):
    if not abstract: 
        return {"translated_title": "[초록 미등록] " + title, "comment": "Abstract 미등록에 따른 분석 불가"}
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    # 의학 용어로 인한 안전 필터 차단 방지
    safety_settings = {
        'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
        'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
        'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
        'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'
    }
    
    prompt = f"""
    당신은 의학 논문 번역가입니다. 아래 영어 논문 제목과 초록을 읽고, 반드시 '한국어(한글)'로 번역 및 요약하세요.
    영어 원문을 그대로 복사하지 마세요.
    
    논문 제목(영어): {title}
    초록(영어): {abstract}

    반드시 아래 포맷에 맞춰서 텍스트로만 답변하세요. 다른 부연 설명은 절대 쓰지 마세요.
    ===
    번역제목: [한국어(한글)로 매끄럽게 번역된 제목]
    요약내용: [자사 품목 '{product_name}' 관점에서의 임상적 의미 한국어 1줄 요약]
    ===
    """
    try:
        # API 과부하 차단 방지 버퍼
        time.sleep(1.5) 
        
        response = model.generate_content(prompt, safety_settings=safety_settings)
        raw_text = response.text.strip()
        
        translated_title = ""
        comment = ""
        
        # 텍스트 안전 파싱
        for line in raw_text.split('\n'):
            line = line.strip()
            if line.startswith("번역제목:"):
                translated_title = line.replace("번역제목:", "").strip(" []\"'")
            elif line.startswith("요약내용:"):
                comment = line.replace("요약내용:", "").strip(" []\"'")
                
        # 한글 검증 2차 방어선 (영문 그대로 출력 시 강제 재요청)
        if not translated_title or not re.search(r'[가-힣]', translated_title):
            time.sleep(1.0) 
            backup_model = genai.GenerativeModel('gemini-2.0-flash')
            backup_prompt = f"다음 의학 논문 제목을 무조건 한국어(한글)로만 번역하세요. 부가 설명 없이 한글 제목만 출력하세요:\n{title}"
            backup_res = backup_model.generate_content(backup_prompt, safety_settings=safety_settings)
            translated_title = backup_res.text.strip(" \n\"'[]")
            
        return {
            "translated_title": translated_title if translated_title else title,
            "comment": comment if comment else "요약 실패"
        }
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota" in error_msg or "exhausted" in error_msg.lower():
            return {"translated_title": "⚠️ API 한도 초과", "comment": "1분당 API 호출 제한(15건)에 도달했습니다. 1~2분 뒤 다시 시도해주세요."}
        else:
            return {"translated_title": "분석 오류", "comment": f"에러 원인: {error_msg[:40]}"}

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

    # [핵심 기능] 고유 PMID 기준 논문 중복 제거 및 검색 매핑
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
        
    # 출력 구조용 데이터 가공
    processed_groups = []
    for combo_key, paper_list in combo_groups.items():
        papers_in_group = [pmid_to_paper[pmid] for pmid, _ in paper_list]
        sorted_items = paper_list[0][1]
        
        # 중첩 키워드 명칭 연결 (예: A키워드 & B키워드)
        kor_title = " & ".join([k['kor'] for k in sorted_items])
        eng_title = " & ".join([k['eng'] for k in sorted_items])
        
        processed_groups.append({
            'kor_title': kor_title,
            'eng_title': eng_title,
            'papers': papers_in_group,
            'overlap_count': len(sorted_items)
        })
        
    # 정렬 기준 우선순위: 1단계 - 중첩 키워드 개수가 많을수록 상단 배치 / 2단계 - 동률일 경우 논문 개수가 많을수록 상단
    active_results = sorted(processed_groups, key=lambda x: (x['overlap_count'], len(x['papers'])), reverse=True)

    if not active_results: st.info("업데이트된 논문이 없습니다.")
    else:
        st.subheader("📈 논문 업데이트 현황")
        for res in active_results:
            # 파일 아이콘 옆 배치: 한국어 조합 이름 적용
            with st.expander(f"📂 {res['kor_title']} ({len(res['papers'])}건)"):
                for i in range(0, len(res['papers']), 3):
                    row_papers = res['papers'][i : i + 3]
                    cols = st.columns(3)
                    for idx, paper in enumerate(row_papers):
                        with cols[idx]:
                            with st.container(border=True):
                                analysis = analyze_paper_with_gemini(gemini_key, paper['title'], paper['abstract'], selected_product)
                                
                                # 문헌 종류 옆 태그 내부 배치: 영어 조합 이름 적용 (구조/디자인 불변)
                                st.markdown(f"**[{paper['pub_type']}]** <span style='background-color:#d1ecf1; color:#0c5460; padding:3px 8px; border-radius:5px; font-size:0.85em; font-weight:bold;'>{res['eng_title']}</span>", unsafe_allow_html=True)
                                st.markdown(f"**{paper['title']}** [[🔗PubMed]](https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/)")
                                st.markdown("---")
                                st.markdown(f"🔖 {analysis.get('translated_title')}")
                                st.markdown(f"💡 {analysis.get('comment')}")
