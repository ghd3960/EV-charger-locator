import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from folium.plugins import MarkerCluster

# ------------------ 기본 위치 설정 ------------------
DEFAULT_LAT = 37.5665
DEFAULT_LNG = 126.9780

# ------------------ 데이터 로딩 ------------------
@st.cache_data
def load_data(xlsx_path: str) -> pd.DataFrame:
    df = pd.read_excel(xlsx_path, engine="openpyxl")
    if "위도경도" in df.columns:
        df[["위도", "경도"]] = df["위도경도"].str.split(",", expand=True).astype(float)
    df = (
        df[[
            "충전소명", "주소", "위도", "경도", "충전기타입", "운영기관(대)",
            "이용자제한", "시설구분(소)", "충전속도"
        ]]
        .rename(columns={
            "운영기관(대)": "운영기관",
            "이용자제한": "이용가능여부",
            "시설구분(소)": "장소유형",
        })
        .dropna(subset=["위도", "경도"])
    )
    return df

# ------------------ 거리 계산 ------------------
def haversine_np(lon1, lat1, lon2, lat2):
    R = 6371
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
    return 2 * R * np.arcsin(np.sqrt(a))

# ------------------ 주소 → 좌표 ------------------
def address_to_coords(address: str):
    geolocator = Nominatim(user_agent="ev_locator")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
    loc = geocode(address)
    return (loc.latitude, loc.longitude) if loc else (None, None)

# ------------------ 앱 설정 ------------------
st.set_page_config(page_title="EV 충전소 탐색기", layout="wide")
st.title("🔌 전기차 충전소 위치 탐색기 (CSV 기반)")

XLSX_PATH = "한국환경공단_전기차 충전소 위치 및 운영정보.xlsx"
df_raw = load_data(XLSX_PATH)

# ------------------ 필터 UI ------------------
with st.sidebar:
    st.header("🔍 필터")
    selected_connectors = st.multiselect("커넥터 타입 선택", ["전체"] + sorted(df_raw["충전기타입"].dropna().unique()), default=["전체"])
    if "전체" in selected_connectors:
        selected_connectors = df_raw["충전기타입"].dropna().unique()

    selected_operators = st.multiselect("운영기관 선택", ["전체"] + sorted(df_raw["운영기관"].dropna().unique()), default=["전체"])
    if "전체" in selected_operators:
        selected_operators = df_raw["운영기관"].dropna().unique()

    selected_places = st.multiselect("장소유형 선택", ["전체"] + sorted(df_raw["장소유형"].dropna().unique()), default=["전체"])
    if "전체" in selected_places:
        selected_places = df_raw["장소유형"].dropna().unique()

    selected_access = st.multiselect("외부인 개방 여부 선택", ["전체"] + sorted(df_raw["이용가능여부"].dropna().unique()), default=["전체"])
    if "전체" in selected_access:
        selected_access = df_raw["이용가능여부"].dropna().unique()

    selected_speeds = st.multiselect("충전 속도 선택", ["전체"] + sorted(df_raw["충전속도"].dropna().unique()), default=["전체"])
    if "전체" in selected_speeds:
        selected_speeds = df_raw["충전속도"].dropna().unique()

# ------------------ 위치 설정 ------------------
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("📍 위치 및 반경 설정")
    mode = st.radio("위치 입력 방식", ["주소 입력", "직접 좌표 입력"])

    if mode == "주소 입력":
        address_in = st.text_input("주소", "서울 중구 세종대로 110")
        if st.button("📍 주소 검색"):
            lat, lon = address_to_coords(address_in)
            if lat is not None:
                st.session_state["center_lat"] = lat
                st.session_state["center_lon"] = lon
                st.success("주소를 기준으로 내 위치가 갱신되었습니다.")
                st.rerun()
            else:
                st.error("주소를 찾을 수 없습니다.")
        lat = st.session_state.get("center_lat", DEFAULT_LAT)
        lon = st.session_state.get("center_lon", DEFAULT_LNG)
    else:
        lat = st.number_input("위도", value=st.session_state.get("center_lat", DEFAULT_LAT), format="%.6f")
        lon = st.number_input("경도", value=st.session_state.get("center_lon", DEFAULT_LNG), format="%.6f")
        st.session_state["center_lat"] = lat
        st.session_state["center_lon"] = lon

    radius_km = st.slider("검색 반경 (km)", 0.1, 10.0, 1.0, step=0.1)

    if st.button("🔍 충전소 검색"):
        df = df_raw.copy()
        df["거리_km"] = haversine_np(df["경도"], df["위도"], lon, lat)
        df = df[
            (df["운영기관"].isin(selected_operators)) &
            (df["장소유형"].isin(selected_places)) &
            (df["이용가능여부"].isin(selected_access)) &
            (df["충전기타입"].isin(selected_connectors)) &
            (df["충전속도"].isin(selected_speeds)) &
            (df["거리_km"] <= radius_km)
        ].sort_values("거리_km")

        st.session_state.update(
            searched=True,
            results=df,
            center_lat=lat,
            center_lon=lon,
            radius=radius_km,
        )

with col2:
    lat = st.session_state.get("center_lat", DEFAULT_LAT)
    lon = st.session_state.get("center_lon", DEFAULT_LNG)
    df = st.session_state.get("results", pd.DataFrame())

    m = folium.Map(location=[lat, lon], zoom_start=13)
    marker_cluster = MarkerCluster().add_to(m)

    for _, r in df.iterrows():
        color = "green" if r["이용가능여부"] == "이용가능" else "orange" if r["이용가능여부"] == "이용자제한" else "red"
        kakao_link = f"https://map.kakao.com/link/to/{r['충전소명']},{r['위도']},{r['경도']}"
        naver_link = f"https://map.naver.com/v5/directions/{lat},{lon}/{r['위도']},{r['경도']}"
        html = (
            f"<b>{r['충전소명']}</b><br>{r['주소']}<br>"
            f"⚡ 타입: {r['충전기타입']}<br>"
            f"⚡ 속도: {r['충전속도']}<br>"
            f"🏢 운영기관: {r['운영기관']}<br>"
            f"🗺 장소유형: {r['장소유형']}<br>"
            f"📍 거리: {r['거리_km']:.2f} km<br>"
            f"✅ 상태: {r['이용가능여부']}<br><br>"
            f"<a href='{kakao_link}' target='_blank'>🧭 카카오 길찾기</a><br>"
            f"<a href='{naver_link}' target='_blank'>🧭 네이버 길찾기</a>"
        )
        folium.Marker(
            [r["위도"], r["경도"]],
            tooltip=r["충전소명"],
            popup=folium.Popup(html, max_width=300),
            icon=folium.Icon(color=color, icon="bolt", prefix="fa")
        ).add_to(marker_cluster)

    # 내 위치 마커 표시
    folium.Marker(
        [lat, lon],
        tooltip="내 위치",
        icon=folium.Icon(color="blue", icon="star")
    ).add_to(m)

    map_data = st_folium(m, width=800, height=600, returned_objects=["last_clicked"])
    if map_data and map_data.get("last_clicked"):
        st.session_state["last_clicked"] = map_data["last_clicked"]
        st.session_state["center_lat"] = map_data["last_clicked"]["lat"]
        st.session_state["center_lon"] = map_data["last_clicked"]["lng"]
        st.success(f"📍 지도 클릭으로 위치 이동됨: 위도 {map_data['last_clicked']['lat']:.6f}, 경도 {map_data['last_clicked']['lng']:.6f}")
