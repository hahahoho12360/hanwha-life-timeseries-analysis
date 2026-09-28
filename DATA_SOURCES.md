# 데이터 출처·수집 방법·이용 주의

이 문서는 `analysis.py`가 어떤 자료를 어떤 단위로 가져오는지 재현할 수 있도록 기록한다. 자동 수집 자료도 제출 전에 원 제공처의 최신 이용약관과 표본 값을 다시 확인한다.

## 핵심 월별 변수

| 변수 | 코드·식별자 | 원 출처/접근 경로 | 월별 변환 | 이용 주의 |
|---|---|---|---|---|
| 한화생명 종가 | 088350 | 네이버 금융 자료를 FinanceDataReader로 접근 | 마지막 거래일 종가 | 수정주가·배당 반영 여부를 실행 시점 문서와 표본 대조 |
| KOSPI | KS11 / KRX 1001 | 한국거래소 계열 자료를 FinanceDataReader로 접근 | 마지막 거래일 종가 | 제공처 점검·개편 때 일시 오류 가능 |
| 보험업 시장 계열 | KRX 1025 우선 / KODEX 보험 140700 대체 | 내용이 있는 수동 KRX CSV 또는 pykrx 인증 수집을 우선한다. 불가능하면 삼성자산운용이 KRX 보험지수 추종 상품으로 명시한 ETF 가격을 대용변수로 쓴다. | 마지막 거래일 종가 | ETF 보수·분배금·추적오차 때문에 원지수와 같지 않다. `source_manifest.json`에서 실제 사용 계열 확인 |
| 한국 10년물 | FRED IRLTLT01KRM156N | OECD → FRED 공식 CSV | 월자료 그대로 사용 | %, 비계절조정, 10년 기준물 |
| 원/달러 | FRED DEXKOUS | 미국 연준 H.10 → FRED 공식 CSV | 일별값의 월평균 | 1달러당 원화, 뉴욕 정오 매입환율 |
| 미국 10년물 | FRED DGS10 | 미국 연준 H.15 → FRED 공식 CSV | 일별값의 월평균 | %, 10년 만기 일정만기 금리 |

## 보조 분기 변수

| 변수 | 코드·경로 | 처리 |
|---|---|---|
| 한국 실질 GDP | FRED NGDPRSAXDCKRQ, 원 출처 IMF IFS | 계절조정 실질 GDP 수준에서 전기 대비·전년 동기 대비 성장률 계산 |
| 한화생명 영업이익 | 우선 `data/manual/hanwha_operating_profit.csv`; 비어 있으면 `NAVER/FINSTATE-2Q/088350` 자동 시도 | 분기값에서 전년 동기 대비 증가율 계산 |

영업이익은 보험회사의 회계표시가 일반 제조업과 다르고 2023년 IFRS 17 도입 전후 비교 가능성도 낮다. 따라서 다음 우선순위를 권장한다.

1. 한화생명 IR의 연결 손익계산서 또는 금융감독원 공시 원문에서 분기 영업이익을 확인한다.
2. 누적액으로 표시된 반기·3분기·연간 자료는 해당 분기 단독액과 혼동하지 않는다.
3. `quarter`는 `2015Q1` 형식, `operating_profit_krw_100m`은 억 원 단위로 통일한다.
4. 각 행의 `source_url`에 근거 문서 주소를 기록한다.

## 직접 확인할 링크

- FinanceDataReader 공식 저장소: https://github.com/FinanceData/FinanceDataReader
- pykrx 공식 저장소: https://github.com/sharebook-kr/pykrx
- 한국거래소 데이터 마켓플레이스: https://data.krx.co.kr/
- 삼성자산운용 KODEX 보험의 KRX 보험지수 추종 공지: https://www.samsungfund.com/etf/lounge/notice-view.do?no=76573
- 한화생명 IR: https://www.hanwhalife.com/company/ir/main/main.do
- 금융감독원 전자공시: https://dart.fss.or.kr/
- FRED 한국 10년물: https://fred.stlouisfed.org/series/IRLTLT01KRM156N
- FRED 원/달러: https://fred.stlouisfed.org/series/DEXKOUS
- FRED 미국 10년물: https://fred.stlouisfed.org/series/DGS10
- FRED 한국 실질 GDP: https://fred.stlouisfed.org/series/NGDPRSAXDCKRQ

## 수집·정제 재현 순서

1. `analysis.py --source live`가 원자료를 `data/raw`에 CSV로 저장한다.
2. 주가·지수는 월말 종가, 일별 금리·환율은 월평균으로 집계한다.
3. 주가·지수·환율은 `pct_change() * 100`, 금리는 `diff()`로 바꾼다.
4. 같은 월말 날짜로 병합하고 핵심 변수가 결측인 달만 제외한다.
5. 이상치는 MAD robust z-score 3.5 초과로 표시하되 삭제하지 않는다.
6. 처리 결과는 `data/processed/monthly_analysis.csv`와 `outputs/data_quality_profile.csv`에 기록한다.
7. 첫 완전관측 월·2020년 3월·마지막 월을 원자료 수준값으로 다시 계산해 `outputs/cross_check_points.csv`에 기록한다.
8. 처리 CSV의 핵심 수치를 `metrics.json` 및 `REPORT.md` 표시값과 비교해 `outputs/metric_cross_check.csv`에 기록한다.

## 라이선스·인용 주의

- FRED는 각 시계열의 원 제공기관과 저작권 조건이 다르다. 각 시계열 페이지의 Suggested Citation과 Notes를 보고서에 인용한다.
- IMF·OECD 자료는 출처 표기가 필요한 자료일 수 있다. 원자료 전체를 재배포하기보다 분석에 필요한 범위와 수집 방법을 명시한다.
- KRX·네이버 자료의 저작권과 서비스 약관을 준수한다. 상업적 재배포를 전제로 하지 않는다.
- pykrx 공식 문서도 자료가 공식값과 다를 수 있으며 과도한 호출을 자제하라고 안내한다.
- GitHub에는 계정 비밀번호나 API 키를 올리지 않는다. `.env`는 `.gitignore` 대상이다.

## 제출 전 표본 검산

다음 세 날짜를 원 제공처 화면과 대조해 기록하면 AI 코드 검증 근거가 강해진다.

- 분석 첫 달의 한화생명·KOSPI·보험업지수 값
- 코로나 충격기(예: 2020년 3월)의 값
- 분석 마지막 완료 월의 값

오차가 있으면 단위, 수정주가, 월말/월평균, 휴장일, 환율 방향(원/달러인지 달러/원인지)을 먼저 확인한다.
