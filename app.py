import streamlit as st
import pandas as pd
import gspread
from datetime import datetime
import os
import re

# --- 1. 보안 및 데이터 호출 엔진 (PowerShell 우선 인증 방식) ---
@st.cache_resource
def get_gc():
    try:
        # [우선순위 1] 로컬 credentials.json 파일 확인 (PowerShell 실행용)
        if os.path.exists('credentials.json'):
            return gspread.service_account(filename='credentials.json')
        
        # [우선순위 2] 로컬 파일이 없을 때만 클라우드 Secrets 확인 (배포용)
        # st.secrets에 접근하기 전 키 존재 여부를 확인하여 시스템 경고 방지
        if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
            creds = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds:
                # 비밀키 내의 \n 문자열을 실제 줄바꿈으로 변환
                pk = creds["private_key"].replace("\\n", "\n").strip()
                # 불필요한 따옴표나 괄호 제거
                pk = re.sub(r'^["\'\(]+|["\'\)]+$', '', pk)
                creds["private_key"] = pk
            return gspread.service_account_from_dict(creds)
            
        st.error("❌ 인증 정보를 찾을 수 없습니다. (credentials.json 파일이 없거나 Secrets가 설정되지 않음)")
        return None
        
    except Exception as e:
        st.error(f"⚠️ 인증 엔진 가동 실패: {e}")
        return None

def fetch_museum_data(sheet_key, tab_name):
    gc = get_gc()
    if not gc: return pd.DataFrame(), None
    try:
        spreadsheet = gc.open_by_key(sheet_key)
        sheet = spreadsheet.worksheet(tab_name)
        raw_data = sheet.get_all_values()
        if not raw_data or len(raw_data) < 2: return pd.DataFrame(), spreadsheet
        
        # 첫 번째 행을 컬럼명으로 사용
        df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
        return df, spreadsheet
    except Exception as e:
        st.error(f"❌ 데이터 로드 실패: {e}")
        return pd.DataFrame(), None

# --- 2. 대분류 명칭 정규화 엔진 ---
def normalize_j(name):
    name = str(name).replace(" ", "")
    if '세그니' in name: return '세그니모시展: Move & Draw'
    if '창의에꼴' in name: return '1101 창의에꼴'
    return name if name else "기타 분류"

# --- 3. 메인 분석 대시보드 UI ---
st.set_page_config(page_title="1101 MUSEUM 통합 OS", layout="wide")
st.title("📊 1101 MUSEUM 이용완료 매출/인원 현황")

SHEET_KEY = "1QKH40pM5BIK1q8cy0pgUrRhnVJTyZo5WpImpqgkozbw"
ORIGINAL_TAB = "완료"
TARGET_TAB = "시트2"

try:
    df_raw, spreadsheet = fetch_museum_data(SHEET_KEY, ORIGINAL_TAB)
    
    if not df_raw.empty:
        # 데이터 매핑 (A:상태, J:대분류, N:소분류, O:금액, Z:날짜)
        cols = df_raw.columns.tolist()
        col_a, col_j, col_n, col_o, col_z = cols[0], cols[9], cols[13], cols[14], cols[25]

        # "이용완료" 데이터 필터링
        df = df_raw[df_raw[col_a].astype(str).str.contains("이용완료", na=False)].copy()
        
        # 데이터 정제
        df[col_o] = pd.to_numeric(df[col_o].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        df['날짜_정제'] = pd.to_datetime(df[col_z], errors='coerce', format='mixed')
        df['대분류_정제'] = df[col_j].apply(normalize_j)
        df = df.dropna(subset=['날짜_정제'])
        df['연월'] = df['날짜_정제'].dt.to_period('M').astype(str)

        # UI: 조회 기준 선택
        view_mode = st.radio("📅 조회 기준 선택", ["일별 상세 현황", "월별 통합 합계"], horizontal=True)
        if view_mode == "일별 상세 현황":
            target_date = st.date_input("날짜 선택", datetime.now())
            display_df = df[df['날짜_정제'].dt.date == target_date]
        else:
            available_months = sorted(df['연월'].unique(), reverse=True)
            target_month = st.selectbox("월 선택", available_months) if available_months else None
            display_df = df[df['연월'] == target_month] if target_month else pd.DataFrame()

        # 집계
        summary = display_df.groupby(['대분류_정제', col_n])[col_o].agg(['sum', 'count']).reset_index()
        summary.columns = ['대분류(J)', '소분류(N)', '매출합계(O)', '인원수(행)']

        # 상단 지표
        m1, m2, m3 = st.columns(3)
        total_rev, total_ppl = summary['매출합계(O)'].sum(), summary['인원수(행)'].sum()
        m1.metric("💰 전체 매출 합계", f"{total_rev:,.0f} 원")
        m2.metric("👥 전체 인원 합계", f"{total_ppl:,.0f} 명")
        m3.metric("🎫 평균 객단가", f"{(total_rev/total_ppl if total_ppl > 0 else 0):,.0f} 원")

        st.divider()

        # 결과 출력
        if not summary.empty:
            for main_cat in summary['대분류(J)'].unique():
                cat_df = summary[summary['대분류(J)'] == main_cat]
                header_text = f"📌 {main_cat} — [ 총 매출: {cat_df['매출합계(O)'].sum():,.0f}원 | 총 인원: {cat_df['인원수(행)'].sum():,.0f}명 ]"
                with st.expander(header_text, expanded=True):
                    st.table(cat_df[['소분류(N)', '매출합계(O)', '인원수(행)']])
            
            if st.button("💾 분석 결과를 '시트2'에 저장하기"):
                try:
                    try: target_sheet = spreadsheet.worksheet(TARGET_TAB)
                    except: target_sheet = spreadsheet.add_worksheet(title=TARGET_TAB, rows="100", cols="20")
                    target_sheet.clear()
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    header_info = [["분석 실행 시간", timestamp], ["모드", view_mode], [], summary.columns.tolist()]
                    target_sheet.update('A1', header_info + summary.values.tolist())
                    st.success(f"✅ '{TARGET_TAB}'에 저장되었습니다.")
                except Exception as ex:
                    st.error(f"시트 저장 실패: {ex}")
        else:
            st.info("해당 기간의 데이터가 없습니다.")

except Exception as e:
    st.error(f"시스템 오류: {e}")
