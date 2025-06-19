import streamlit as st
import pandas as pd
import numpy as np
import requests
import xml.etree.ElementTree as ET
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import time # RateLimiter 사용 시 필요할 수 있음

# ------------------ 거리 계산 함수 ------------------
# 위도(lat)와 경도(lon)를 이용하여 두 지점 간의 거리를 km 단위로 계산합니다 (Haversine 공식).
def haversine_np(lon1, lat1, lon2, lat2):
    R = 6371  # 지구 반지름 (km)
    # 위도와 경도를 라디안 단위로 변환합니다.
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    
    # 위도 및 경도 차이 계산
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    
    # Haversine 공식 적용
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))

# ------------------ KEPCO API 호출 함수 ------------------
# @st.cache_data 데코레이터를 사용하여 API 호출 결과를 캐시합니다 (성능 개선 및 API 트래픽 관리).
# 데이터는 1시간(3600초) 동안 캐시됩니다.
@st.cache_data(ttl=3600) 
def fetch_ev_data_from_api(service_key: str) -> pd.DataFrame:
    st.write("📡 한국전력공사 전기차 충전소 데이터를 불러오는 중...")
    
    # API End Point (공공데이터포털 문서를 기반으로 HTTP 사용으로 변경)
    base_url = "http://openapi.kepco.co.kr/service/EvInfoServiceV2/getEvSearchList" # HTTPS -> HTTP로 변경
    
    # requests.get의 params 인자를 사용하여 파라미터를 전달합니다.
    # 이 방식은 파라미터 값의 URL 인코딩을 requests 라이브러리가 자동으로 처리합니다.
    params = {
        "serviceKey": service_key,
        "pageNo": 1,
        "numOfRows": 1000, # 한 번에 최대 1000개의 데이터 요청 (API 정책에 따라 조정 가능)
        "addr": "" # 'addr' 파라미터는 필수 아니지만, 명시적으로 빈 문자열로 보내 오류 방지
    }

    try:
        # API 호출 (타임아웃 10초 설정)
        response = requests.get(base_url, params=params, timeout=10)
        # HTTP 오류 (4xx, 5xx) 발생 시 예외 발생
        response.raise_for_status() 

        # XML 응답 파싱 및 API 응답 헤더 확인
        root = ET.fromstring(response.content)
        header = root.find("header")
        result_code = header.findtext("resultCode", "N/A")
        result_msg = header.findtext("resultMsg", "N/A")

        # API 응답 코드가 '00' (정상)이 아닌 경우 오류 메시지 표시
        if result_code != "00":
            st.error(f"❌ API 응답 오류 (코드: {result_code}): {result_msg}")
            st.code(response.text[:1000], language="xml") # 오류 응답의 일부를 보여줌
            return pd.DataFrame()

        # 'body/items' 태그에서 충전소 데이터 추출
        items = root.find("body/items")
        if items is None:
            # resultCode가 '00'이지만 items가 없는 경우 (데이터 없음 또는 예상치 못한 구조)
            st.warning("⚠️ API 응답에 유효한 <items> 태그가 없습니다. (데이터 없음 또는 응답 구조 변화 가능성)")
            st.code(response.text[:1000], language="xml")
            return pd.DataFrame()

        data = []
        for item in items.findall("item"):
            try:
                # findtext 사용 시 기본값 ""을 주어 None 대신 빈 문자열 반환
                data.append({
                    "충전소명": item.findtext("csNm", ""),
                    "주소": item.findtext("addr", ""),
                    # float() 변환 시 None 대신 0을 기본값으로 사용 (유효하지 않은 좌표 처리)
                    "위도": float(item.findtext("lat") or 0),
                    "경도": float(item.findtext("longi") or 0),
                    "이용가능여부": item.findtext("useTime", "정보없음"),
                    "운영기관": item.findtext("busiNm", "정보없음"),
                    "충전기타입": item.findtext("cpTp", "정보없음"), # 충전기 타입 코드 (API 문서 참고)
                    "충전기상태": item.findtext("cpStat", "정보없음") # 충전기 상태 코드 (API 문서 참고)
                })
            except Exception as e:
                # 개별 아이템 파싱 중 오류 발생 시 경고 및 해당 아이템 건너뛰기
                st.warning(f"데이터 파싱 중 오류 발생: {e} - 일부 충전소 데이터가 누락될 수 있습니다.")
                continue

        df = pd.DataFrame(data)
        # 위도/경도가 0인 데이터는 유효하지 않은 좌표로 간주하고 필터링합니다.
        df = df[(df['위도'] != 0) | (df['경도'] != 0)]
        st.success(f"✅ 총 {len(df)}개의 충전소 데이터를 성공적으로 불러왔습니다.")
        return df

    except requests.exceptions.RequestException as e:
        # API 호출 중 네트워크 또는 HTTP 오류 발생 시 처리
        st.error(f"❌ API 호출 중 네트워크 또는 HTTP 오류 발생: {e}")
        st.write("API 요청 URL:", response.url if 'response' in locals() else base_url)
        st.code(response.text if 'response' in locals() else "응답 없음", language="xml")
        return pd.DataFrame()
    except ET.ParseError as e:
        # XML 파싱 오류 발생 시 처리 (API 응답이 올바른 XML 형식이 아닐 경우)
        st.error(f"❌ XML 파싱 실패: {e}. API 응답이 올바른 XML 형식이 아닐 수 있습니다.")
        st.code(response.text if 'response' in locals() else "응답 없음", language="xml")
        return pd.DataFrame()
    except Exception as e:
        # 예상치 못한 기타 오류 발생 시 처리
        st.error(f"❌ 예상치 못한 오류 발생: {e}")
        return pd.DataFrame()

# ------------------ 주소 → 좌표 변환 함수 ------------------
# @st.cache_data 데코레이터를 사용하여 주소-좌표 변환 결과를 캐시합니다 (성능 개선).
# 주소-좌표 변환 결과는 24시간(86400초) 동안 캐시됩니다.
@st.cache_data(ttl=86400) 
def get_coordinates(address):
    # Nominatim을 사용하여 주소를 좌표로 변환 (user_agent는 필수)
    geolocator = Nominatim(user_agent="ev_charger_locator_app_streamlit") 
    # RateLimiter를 사용하여 API 요청 간 최소 지연 시간을 설정 (API 정책 준수)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.5) 
    
    try:
        # 주소 변환 (타임아웃 10초 설정)
        location = geocode(address, timeout=10) 
        if location:
            st.success(f"✅ '{address}'에 대한 좌표: 위도 {location.latitude}, 경도 {location.longitude}")
            return location.latitude, location.longitude
        st.error(f"❌ '{address}'에 대한 좌표를 찾을 수 없습니다. 주소를 다시 확인해주세요.")
        return None, None
    except Exception as e:
        st.error(f"❌ 주소-좌표 변환 중 오류 발생: {e}. 주소가 정확한지 확인하거나 네트워크 연결을 확인하세요.")
        return None, None

# ------------------ Streamlit 앱 시작 ------------------
# 페이지 설정: 넓은 레이아웃 사용, 페이지 제목 설정
st.set_page_config(layout="wide", page_title="EV 충전소 탐색기")

st.title("🔌 한국전력 전기차 충전소 위치 탐색기")
st.markdown("내 위치 주변의 한국전력 전기차 충전소를 찾아보세요!")

# Streamlit secrets에서 API 키 불러오기
# secrets.toml 파일에 kepco_api_key = "YOUR_API_KEY_HERE" 형태로 저장해야 합니다.
try:
    SERVICE_KEY = st.secrets["kepco_api_key"]
    if not SERVICE_KEY:
        st.error("⚠️ Streamlit secrets에 'kepco_api_key'가 설정되지 않았습니다. `.streamlit/secrets.toml` 파일을 확인해주세요.")
        st.stop() # 키가 없으면 앱 실행 중단
except FileNotFoundError:
    st.error("⚠️ `.streamlit/secrets.toml` 파일을 찾을 수 없습니다. API 키를 설정해주세요.")
    st.stop()
except KeyError:
    st.error("⚠️ `.streamlit/secrets.toml` 파일에 `kepco_api_key`가 정의되지 않았습니다. 올바른 키를 추가해주세요.")
    st.stop()


# 충전소 데이터 로드 (캐시된 데이터를 먼저 시도)
with st.spinner("충전소 데이터 불러오는 중... 잠시만 기다려 주세요."):
    df = fetch_ev_data_from_api(SERVICE_KEY)

# 데이터프레임이 비어있으면 앱 실행 중단 (API 호출 실패 시)
if df.empty:
    st.warning("⚠️ API에서 데이터를 불러올 수 없습니다. 인증키 또는 서비스 상태를 확인하세요. (위의 오류 메시지를 참조하세요)")
    st.stop()

# Streamlit 세션 상태 초기화 (앱의 첫 실행 시 또는 캐시/상태 초기화 시)
if 'searched' not in st.session_state:
    st.session_state['searched'] = False
    st.session_state['nearby'] = pd.DataFrame()
    st.session_state['user_lat'] = 37.5665 # 서울 시청 위도 (기본값)
    st.session_state['user_lng'] = 126.9780 # 서울 시청 경도 (기본값)
    st.session_state['radius'] = 1.0 # 기본 검색 반경

# UI 레이아웃을 위한 컬럼 분할
col1, col2 = st.columns([1, 2])

with col1: # 왼쪽 컬럼: 위치 설정 및 검색 컨트롤
    st.subheader("📍 위치 및 반경 설정")
    # 위치 입력 방식 선택 (주소 입력 또는 직접 좌표 입력)
    option = st.radio("위치 입력 방식", ['주소 입력', '직접 좌표 입력'], key="location_option")

    user_address_input = "서울 중구 세종대로 110" # 주소 입력 필드의 초기값
    if option == '주소 입력':
        address = st.text_input("주소", user_address_input, key="address_input")
    else:
        # 직접 좌표 입력 시 현재 세션 상태의 값을 기본값으로 사용
        lat_in = st.number_input("위도", value=st.session_state['user_lat'], format="%.6f", key="lat_input")
        lng_in = st.number_input("경도", value=st.session_state['user_lng'], format="%.6f", key="lng_input")

    # 검색 반경 슬라이더
    radius = st.slider("검색 반경 (km)", 0.1, 10.0, st.session_state['radius'], step=0.1, key="radius_slider")

    # 검색 버튼 클릭 시 동작
    if st.button("🔍 충전소 검색", key="search_button"):
        user_lat, user_lng = None, None
        if option == '주소 입력':
            # 주소 입력 시 좌표 변환 함수 호출
            user_lat, user_lng = get_coordinates(address)
            if user_lat is None: # 좌표 변환 실패 시
                st.session_state['searched'] = False # 검색 상태 초기화
                st.stop() # 앱 실행 중단 또는 경고 메시지 표시 후 대기
        else:
            user_lat, user_lng = lat_in, lng_in

        # 유효한 좌표가 있을 때만 거리 계산 및 세션 상태 업데이트
        if user_lat is not None and user_lng is not None:
            # DataFrame 복사본을 만들어 원본 데이터 보호
            df_copy = df.copy()
            
            # 모든 충전소와 사용자 위치 간의 거리 계산
            dists = haversine_np(
                df_copy['경도'].values, df_copy['위도'].values, # 충전소 경도/위도
                np.full(len(df_copy), user_lng), np.full(len(df_copy), user_lat) # 사용자 경도/위도 배열
            )
            df_copy['거리_km'] = dists
            
            # 검색 반경 내 충전소 필터링 및 거리 순 정렬
            nearby = df_copy[df_copy['거리_km'] <= radius].sort_values('거리_km')

            # 검색 결과 및 사용자 위치 정보를 세션 상태에 저장
            st.session_state.update({
                'searched': True,
                'nearby': nearby,
                'user_lat': user_lat,
                'user_lng': user_lng,
                'radius': radius
            })
            st.rerun() # 검색 결과 바로 반영을 위해 앱 다시 실행 (Streamlit의 특징)

    # 캐시 및 상태 초기화 버튼
    if st.button("🧹 캐시 및 상태 초기화", key="clear_cache_button"):
        st.cache_data.clear() # 모든 `@st.cache_data` 캐시 초기화
        st.session_state.clear() # 모든 `st.session_state` 변수 초기화
        st.success("✅ 캐시 및 상태 초기화 완료. 앱을 새로고침합니다.")
        st.rerun() # 앱 새로고침

with col2: # 오른쪽 컬럼: 지도 및 충전소 목록 표시
    # 검색이 완료되었고 주변 충전소가 있을 경우
    if st.session_state.get('searched') and not st.session_state['nearby'].empty:
        nearby = st.session_state['nearby']
        user_lat = st.session_state['user_lat']
        user_lng = st.session_state['user_lng']
        radius = st.session_state['radius']

        st.subheader(f"🔍 반경 {radius:.1f}km 내 {len(nearby)}개 충전소")

        # Folium 지도 초기화 (사용자 위치를 중심으로 설정)
        m = folium.Map(location=[user_lat, user_lng], zoom_start=13)

        # 사용자 위치 마커 추가
        folium.Marker(
            [user_lat, user_lng],
            tooltip='내 위치',
            icon=folium.Icon(color='blue', icon='user', prefix='fa') # 파란색 사용자 아이콘
        ).add_to(m)

        # 검색 반경을 원으로 표시 (km를 미터로 변환하여 Folium에 전달)
        folium.Circle(
            location=[user_lat, user_lng],
            radius=radius * 1000, 
            color='blue',
            fill=True,
            fill_color='blue',
            fill_opacity=0.1,
            tooltip=f"{radius:.1f} km 반경"
        ).add_to(m)

        # 주변 충전소 마커 추가
        for idx, row in nearby.iterrows():
            # 팝업 HTML 내용 구성
            popup_html = (
                f"<b>{row['충전소명']}</b><br>{row['주소']}<br>"
                f"⚡ 타입: {row['충전기타입']}<br>" # 충전기 타입 표시
                f"🏢 운영기관: {row['운영기관']}<br>"
                f"🕒 이용시간: {row['이용가능여부']}<br>"
                f"🔌 상태: {row['충전기상태']}<br>" # 충전기 상태 표시
                f"📍 거리: {row['거리_km']:.2f} km"
            )
            folium.Marker(
                [row['위도'], row['경도']],
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=row['충전소명'],
                icon=folium.Icon(color='green', icon='bolt', prefix='fa') # 초록색 번개 아이콘
            ).add_to(m)

        # Streamlit에 Folium 맵 렌더링
        st_folium(m, width=800, height=550)

        st.subheader("📋 충전소 목록")
        # 표시할 컬럼 선택 및 컬럼명 변경 후 데이터프레임 표시
        display_df = nearby[['충전소명', '주소', '거리_km', '이용가능여부', '운영기관', '충전기타입', '충전기상태']].copy()
        display_df.rename(columns={'거리_km': '거리(km)'}, inplace=True)
        st.dataframe(display_df, use_container_width=True)

    # 검색 결과가 없거나 아직 검색하지 않은 경우 메시지 표시
    elif st.session_state.get('searched') and st.session_state['nearby'].empty:
        st.warning("해당 반경 내 충전소가 없습니다. 검색 반경을 늘려보세요.")
    else:
        st.info("왼쪽 패널에서 위치를 설정하고 '충전소 검색' 버튼을 눌러 주변 충전소를 찾아보세요.")
