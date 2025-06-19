import streamlit as st
import requests
from urllib.parse import unquote_plus
import xml.etree.ElementTree as ET # XML 파싱을 위한 라이브러리

st.title("한국전력공사 전기차 충전소 정보 조회")

# *** 여기에 공공데이터포털에서 발급받은 본인의 실제 인증키를 입력하세요 ***
service_key_encoded = "hZalObjCkg3OXWiB7Chzokw7mj3Wo3ZsGHlnSqu4ZdKoRWK8ikwQq0rtewTN1adSxdsvCz6utA5fDXzht4doSA%3D%3D" # 이 값은 예시입니다. 실제 키로 교체하세요!

# 사용자 입력 받기
search_address = st.text_input("검색할 주소 (예: 서울특별시)", "서울특별시")
page_no = st.number_input("페이지 번호", min_value=1, value=1)
num_of_rows = st.number_input("한 페이지당 결과 수", min_value=1, value=10)

if st.button("충전소 정보 조회"):
    url = "http://openapi.kepco.co.kr/service/EvInfoServiceV2/getEvSearchList" # 공공데이터포털 예시는 http를 사용합니다.

    params = {
        "ServiceKey": unquote_plus(service_key_encoded),
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "addr": search_address
    }

    try:
        with st.spinner('정보를 불러오는 중...'):
            response = requests.get(url, params=params, timeout=10) # 타임아웃 설정
            response.raise_for_status() # HTTP 오류 발생 시 예외 발생

            st.subheader("API 호출 결과:")

            # XML 파싱
            root = ET.fromstring(response.text)
            items = root.find('body/items')

            if items is not None:
                if items.findall('item'):
                    for item in items.findall('item'):
                        # 예시로 몇 가지 정보만 추출하여 표시
                        st.write(f"---")
                        st.write(f"**충전소명:** {item.find('cpName').text if item.find('cpName') is not None else 'N/A'}")
                        st.write(f"**주소:** {item.find('addr').text if item.find('addr') is not None else 'N/A'}")
                        st.write(f"**충전기 상태:** {item.find('cpStat').text if item.find('cpStat') is not None else 'N/A'}") # cpStat 값에 따라 의미 해석 필요 (공공데이터포털 문서 참고)
                        st.write(f"**충전 방식:** {item.find('chargeTp').text if item.find('chargeTp') is not None else 'N/A'}") # chargeTp 값에 따라 의미 해석 필요 (공공데이터포털 문서 참고)
                else:
                    st.warning("조회된 충전소 정보가 없습니다.")
            else:
                st.warning("응답에서 'items' 섹션을 찾을 수 없습니다.")

            # 전체 응답 확인용 (디버깅 목적)
            with st.expander("전체 XML 응답 보기"):
                st.code(response.text, language='xml')

    except requests.exceptions.RequestException as e:
        st.error(f"API 호출 중 오류 발생: {e}")
        if response is not None:
            st.error(f"Error Response Body: {response.text}")
    except ET.ParseError as e:
        st.error(f"XML 파싱 오류: {e}. 응답이 유효한 XML이 아닐 수 있습니다.")