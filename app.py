import streamlit as st
import pandas as pd
from Bio import Entrez
import google.generativeai as genai
import json
import re
import time  # API 호출 속도 조절을 위해 추가됨

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

# --- AI 분석 함수 (API 한도 방어 및 파싱 오류 해결) ---
def analyze_paper_with_gemini(api_key, title, abstract, product_name):
    if not abstract: 
        return {"translated_title": "[초록 미등록] " + title, "comment": "Abstract 미등록에 따른 분석 불가"}
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    
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
        # [핵심] API 호출이 너무 빨라 차단(429 Error)되는 것을 막기 위한 1.5초 대기
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
                
        # 한글(가-힣) 포함 여부 꼼꼼히 체크 (여전히 영문일 경우 대비)
        if not translated_title or not re.search(r'[가-힣]', translated_title):
            time.sleep(1.0) # 백업 호출 전 추가 대기
            backup_model = genai.GenerativeModel('gemini-2.0-flash')
            backup_prompt = f"다음 의학 논문 제목을 무조건 한국어(한글)로만 번역하세요. 부가 설명 없이 한글 제목만 출력하세요:\n{title}"
            backup_res = backup_model.generate_content(backup_prompt, safety_settings=safety_settings)
            translated_title = backup_res.text.strip(" \n\"'[]")
            
        return {
            "translated_title": translated_title if translated_title else title,
            "comment": comment if comment else "요약 실패"
        }
    except Exception as e:
        # 에러 발생 시, 뭉뚱그리지 않고 실제 원인을 출력하여 대응할 수 있게 함
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

if st.button("🚀 분석 시작
