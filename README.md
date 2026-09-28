# 금리·환율·보험업 시장환경과 한화생명 주가의 관계

> 부제: 한국 국고채 10년물, 원/달러 환율, KOSPI 및 보험업지수와 한화생명 월간 수익률의 동행성 분석

이 폴더는 **2015년 1월부터 실행 시점의 직전 완료 월까지** 자료를 월 단위로 모아, 한화생명 월간 주가수익률과 시장환경 변수의 관계를 분석하는 실행 가능한 Python 프로젝트다. 초보자도 순서대로 따라 할 수 있도록 설치부터 GitHub·Streamlit 배포까지 설명한다.

실제 업로드·배포만 빠르게 따라 하려면 [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md), 원본 평가기준 최종 판정은 [FINAL_AUDIT.md](FINAL_AUDIT.md)를 먼저 연다.

> **아주 중요한 주의:** `--source sample`은 코드가 돌아가는지 연습하는 가짜 자료다. 평가용 최종 보고서는 반드시 `--source live`로 다시 만들어야 한다. 상관관계는 인과관계를 뜻하지 않으며, 이 프로젝트는 투자 권유가 아니다.

## 0. 이 프로젝트가 하는 일

핵심 종속변수는 **한화생명 월간 주가수익률**이다. 다음 설명변수와 같은 달에 함께 움직였는지를 살핀다.

| 구분 | 변수 | 계산 방법 |
|---|---|---|
| 핵심 | 보험업 시장 계열 월간 수익률 | KRX 보험업지수 우선, 접근 제한 시 공식 추종 ETF의 월말 가격 변화율(%) |
| 핵심 | KOSPI 월간 수익률 | 월말 지수의 전월 대비 변화율(%) |
| 핵심 | 한국 국고채 10년물 금리 변화 | 이번 달 금리 - 지난달 금리(%p) |
| 핵심 | 원/달러 환율 변화율 | 월평균 환율의 전월 대비 변화율(%) |
| 선택 | 미국 국채 10년물 금리 변화 | 이번 달 금리 - 지난달 금리(%p) |
| 보조 | 한화생명 분기 영업이익 증가율 | 전년 같은 분기 대비 변화율(%) |
| 보조 | 한국 실질 GDP 성장률 | 전기 대비 및 전년 동기 대비 변화율(%) |

전체 흐름은 아래와 같다.

```text
원자료 수집 → 날짜·단위 통일 → 결측·이상치 점검 → 월간 변화율 계산
→ 그래프·상관·이동상관·국면 비교 → 간단 예측 → REPORT.md 생성
→ Streamlit 대시보드 확인 → GitHub 업로드 → 공개 URL 제출
```

## 1. 준비물

다음 네 가지를 설치하거나 가입한다.

1. Python 3.11: <https://www.python.org/downloads/>
2. Visual Studio Code: <https://code.visualstudio.com/>
3. Git: <https://git-scm.com/downloads>
4. GitHub 계정과 Streamlit Community Cloud 계정

Python 설치 화면에서는 **Add Python to PATH**를 체크한다. Python 3.12에서도 동작할 수 있지만, 자료수집 라이브러리 호환성을 위해 이 안내서는 3.11을 권장한다.

## 2. 처음 한 번만 하는 설치 — Windows PowerShell

### 2-1. 프로젝트 폴더 열기

1. 받은 ZIP 파일의 압축을 푼다.
2. Visual Studio Code를 연다.
3. `File → Open Folder`를 누른다.
4. 압축을 푼 `hanwha-life-timeseries-analysis` 폴더를 선택한다.
5. 위 메뉴에서 `Terminal → New Terminal`을 누른다.

터미널 줄 끝에 현재 폴더 이름이 `hanwha-life-timeseries-analysis`인지 확인한다.

### 2-2. Python 버전 확인

```powershell
py --version
```

`Python 3.11.x`가 보이면 정상이다. 여러 버전이 설치되어 있어도 아래 명령의 `-3.11`이 3.11을 선택한다.

### 2-3. 프로젝트 전용 가상환경 만들기

```powershell
py -3.11 -m venv .venv
```

가상환경은 이 프로젝트만의 작은 Python 상자라고 생각하면 된다. 다른 프로젝트와 라이브러리 버전이 섞이지 않는다.

### 2-4. 가상환경 켜기

```powershell
.\.venv\Scripts\Activate.ps1
```

앞에 `(.venv)`가 보이면 성공이다. 실행 정책 오류가 날 때만 아래 두 줄을 순서대로 실행한다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 2-5. 필요한 라이브러리 설치

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

설치가 끝나면 실제 설치 버전을 기록한다.

```powershell
python -m pip freeze > requirements-lock.txt
```

### macOS를 쓰는 경우

`py -3.11` 대신 `python3.11`, 활성화 명령 대신 `source .venv/bin/activate`를 사용하고 나머지는 같다.

## 3. KRX 계정정보가 있을 때만 안전하게 설정하기

2026년부터 일부 KRX 장기지수 호출에는 로그인이 필요할 수 있다. KRX 계정이 있고 원지수(1025)를 자동 수집하려는 경우에만 `.env.example`을 복사해 `.env`를 만든다.

```powershell
Copy-Item .env.example .env
```

Visual Studio Code에서 `.env`를 열어 본인의 값을 넣는다.

```text
KRX_ID=본인의_KRX_아이디
KRX_PW=본인의_KRX_비밀번호
```

- `.env`는 이미 `.gitignore`에 들어 있어 GitHub에 올라가지 않는다.
- 비밀번호를 Python 파일, README, 보고서, 화면 캡처에 적지 않는다.
- KRX 계정이 없으면 코드는 중단하지 않고 `KODEX 보험(140700)`을 보험업 시장 대용변수로 사용한다. 삼성자산운용이 이 상품의 KRX 보험지수 추종 사실을 명시하지만, 보수·분배금·추적오차 때문에 원지수와 완전히 같지는 않다.
- 정확한 KRX 원지수가 필요하면 6장의 수동 CSV 방법을 쓴다.

## 4. 먼저 연습 자료로 전체 작동 확인하기

아래 명령은 인터넷 자료 대신 재현 가능한 가짜 자료를 만든다.

```powershell
python analysis.py --source sample --start 2015-01-01 --end 2026-08-31
```

마지막에 `완료되었습니다`가 보이면 성공이다. 이어서 자동검사를 실행한다.

```powershell
python -m unittest discover -s tests -v
```

일곱 항목 모두 `ok`이고 마지막에 `OK`가 나오면 정상이다.

> `sample` 보고서의 숫자와 결론은 제출하면 안 된다. 이 단계의 목적은 설치·코드·그래프 저장이 정상인지 확인하는 것이다.

## 5. 실제 자료로 분석하기

2026년 8월까지 고정해서 재현하려면 다음을 실행한다.

```powershell
python analysis.py --source live --start 2015-01-01 --end 2026-08-31
```

이 명령을 다시 실행해도 `REPORT.md`의 실제 GitHub·Streamlit 주소는 기본값으로 보존된다. 주소가 바뀐 경우에만 `--github-url 새주소 --dashboard-url 새주소`를 뒤에 붙인다.

현재 시점의 직전 완료 월까지 자동으로 분석하려면 `--end`를 빼도 된다.

```powershell
python analysis.py --source live --start 2015-01-01
```

일부 공개 자료는 발표가 늦어 마지막 달이 비어 있을 수 있다. 코드는 **모든 핵심 변수가 존재하는 완전한 월**만 최종 분석표에 남긴다. 2015년부터 2026년까지라면 100개를 충분히 넘어야 한다. 실행 후 `REPORT.md`의 관측 월 수와 `VERIFICATION.md`의 3시점 검산 결과를 확인한다. FRED 자료는 어댑터 오류를 피하기 위해 FRED 공식 CSV를 직접 내려받는다.

### 왜 월 단위인가?

- 일별 자료는 금리·GDP·분기 실적과 주기가 맞지 않고 단기 잡음이 매우 크다.
- 분기 단위는 2015~2026년에 표본이 약 46개뿐이라 100개 기준을 만족하지 못한다.
- 월 단위는 핵심 시장 자료를 같은 달로 맞추면서 100개 이상의 관측치를 확보하는 절충안이다.

### 왜 월말과 월평균을 섞는가?

- 주가·지수는 투자자가 실제로 관찰한 월 마지막 거래일 종가를 쓴다.
- 일별 환율·미국 금리는 한 날짜의 우연한 급등락 영향을 줄이기 위해 월평균을 쓴다.
- 한국 10년물은 원자료가 월별이므로 그대로 쓴다.

## 6. 자동 수집이 막힐 때 수동 자료 넣기

### 6-1. KOSPI 보험업지수 원자료를 직접 쓰고 싶을 때

`data/manual/kospi_insurance.csv`를 열고 다음 모양으로 채운다.

```csv
date,close
2015-01-30,12345.67
2015-02-27,12510.12
```

- `date`: 각 월의 마지막 거래일
- `close`: KOSPI 보험업지수 종가
- 날짜는 오래된 순서로 넣는다.
- 2015년 1월 수익률까지 필요하면 기준값인 **2014년 12월 행도 함께** 넣는다.
- KRX 데이터 마켓에서 지수 코드 1025를 조회하고, 첫 달·2020년 3월·마지막 달 값 세 개를 원 화면과 대조한다.
- 파일이 헤더만 있거나 숫자 행이 없으면 코드는 이를 유효한 자료로 오인하지 않고 KODEX 보험 ETF 대용변수로 전환한다.

### 6-2. 한화생명 분기 영업이익

현재 `data/manual/hanwha_operating_profit.csv`에는 DART 연결 포괄손익계산서로 검증한 2025년 2분기~2026년 2분기 값이 들어 있다. 이후 분기를 추가하거나 값을 교체할 때 아래 모양을 지킨다.

```csv
quarter,operating_profit_krw_100m,source_url,derivation
2026Q1,4807.82,https://dart.fss.or.kr/공시주소,반기 누적액에서 2분기 단독액 차감 후 억원으로 변환
2026Q2,6267.82,https://dart.fss.or.kr/공시주소,3개월 영업이익을 억원으로 변환
```

- `quarter`: `연도Q분기` 형식
- `operating_profit_krw_100m`: **억 원** 단위
- `source_url`: 한화생명 IR 또는 DART 원문 주소
- `derivation`: 공시의 직접 3개월 값인지, 누적액끼리 차감한 값인지와 단위 변환식을 기록
- 반기·3분기 공시의 누적액과 해당 분기 단독액을 혼동하지 않는다.
- 2023년 IFRS 17 도입 전후에는 회계기준 변화 때문에 단순 비교를 조심한다.
- 공식 검증 CSV가 비어 있으면 코드는 영업이익 보조 분석을 제외하며, 비공식 자동 스냅샷으로 조용히 대체하지 않는다.

저장한 뒤 5장의 실제 자료 명령을 다시 실행한다.

## 7. 코드가 자료를 검사하는 기준

### 결측치

1. 모든 시계열을 같은 월말 달력에 맞춘다.
2. 미래 값을 과거에 넣는 보간은 하지 않는다.
3. 핵심 변수 중 하나라도 없는 달은 핵심 분석에서 제외한다.
4. 제외 전후 행 수와 변수별 결측 수를 `outputs/data_quality_profile.csv`에 남긴다.
5. 12개월 이동통계의 첫 11개 결측은 창이 채워지기 전의 **구조적 준비구간 결측**이므로 오류로 보간하거나 삭제하지 않는다. 100개 이상 완전관측치 판정은 핵심 6개 변수에 적용한다.

이 기준은 존재하지 않는 금융자료를 임의로 만들어 상관관계를 왜곡하지 않기 위해서다.

### 이상치

각 수익률·변화량의 중앙값에서 얼마나 멀리 있는지 MAD robust z-score로 계산하고, 절댓값이 3.5를 넘으면 표시한다. 금융위기나 코로나 충격은 분석해야 할 실제 사건일 수 있으므로 **표시는 하지만 자동 삭제하지 않는다**.

## 8. 분석 질문과 시계열 기법

보고서는 적어도 다음 질문에 답한다.

1. 한화생명 수익률은 보험업지수·KOSPI 중 어느 쪽과 더 강하게 움직였는가?
2. 한국 10년물 금리가 오르거나 내린 달에 한화생명 평균 수익률이 달랐는가?
3. 원/달러가 오른 원화 약세 달과 내린 원화 강세 달에 수익률 차이가 있었는가?
4. 관계가 전 기간에 고정되었는가, 12개월 이동상관으로 달라졌는가?
5. 최근 3개월 수익률만 쓰는 단순 예측이 과거평균 예측보다 나았는가?

사용 기법은 다음과 같다.

| 기법 | 무엇을 보려는가 | 결과를 읽는 법 |
|---|---|---|
| 월간 변화율·금리차분 | 서로 단위가 다른 수준값 대신 같은 달의 움직임 비교 | 양수는 상승, 음수는 하락 |
| 전체 Pearson 상관 | 두 변수가 평균적으로 같은 방향으로 움직였는지 확인 | +1에 가까울수록 같은 방향, -1은 반대 방향 |
| 12개월 이동평균·변동성·이동상관 | 시간에 따라 평균·위험·관계가 바뀌는지 확인 | 선이 크게 움직이면 단일 평균만으로 설명하기 어려움 |
| 금리·환율 국면 비교 | 상승/하락 조건별 한화생명 평균수익률 차이 확인 | 표본 수와 평균을 함께 확인 |
| 12개월 중심 이동평균과 잔차 | 장기 흐름(추세 대용)과 단기 잡음 구분 | 부드러운 선은 추세 대용, 원계열과의 차이는 잡음 대용 |

여기서 중심 이동평균은 완전한 계절분해가 아니라 **추세를 눈으로 구분하기 위한 대용치**다. 월수익률에 계절성이 있다고 단정하지 않는다.

## 9. 보너스 과제 B — 간단 예측

`analysis.py`는 한화생명의 과거 1·2·3개월 수익률을 입력으로 쓰는 **AR(3) Ridge 회귀**를 만든다.

1. 마지막 6~12개월은 학습에 쓰지 않고 검증 구간으로 남긴다.
2. 모델의 MAE와 단순 과거평균 예측의 MAE를 비교한다.
3. 전체 자료를 다시 학습해 다음 3개월을 순차 예측한다.
4. 학습 잔차 표준편차로 근사 95% 구간을 표시한다.

예측 그림은 `outputs/figures/06_baseline_forecast.png`, 숫자는 `outputs/forecast.csv`, 검증 지표는 `outputs/metrics.json`에 저장된다.

**가정과 한계:** 과거 3개월 패턴이 짧은 미래에도 이어진다고 가정한다. 공시, 정책, 배당, 규제, 구조적 단절을 모르며 95% 구간도 엄밀한 확률모형 구간이 아니다. 따라서 정확한 투자 예측이 아니라 비교 가능한 교육용 기준선이다.

## 10. 로컬 웹 대시보드 보기

실제 자료 분석이 끝난 뒤 다음을 실행한다.

```powershell
streamlit run dashboard.py
```

브라우저가 열리면 왼쪽에서 기간, 이동상관 개월 수, 비교 변수, 금리·환율 조건을 바꿔 본다. 멈추려면 터미널을 한 번 클릭하고 `Ctrl+C`를 누른다.

## 11. GitHub에 올리기

공개 저장소는 <https://github.com/hahahoho12360/hanwha-life-timeseries-analysis>에 배포되어 있다. 같은 프로젝트를 새 계정에 다시 올릴 때는 아래 명령에서 계정명만 바꾼다.

```powershell
git init
git add .
git status
git commit -m "Add Hanwha Life monthly time-series analysis"
git branch -M main
git remote add origin https://github.com/hahahoho12360/hanwha-life-timeseries-analysis.git
git push -u origin main
```

`git status`에서 `.env`가 보이면 **커밋하지 말고 즉시 멈춘다**. `.env`는 비밀번호가 든 파일이다.

GitHub 화면에서 다음이 실제로 보이는지 확인한다.

- `analysis.py`, `dashboard.py`, `requirements.txt`, `requirements-lock.txt`
- `README.md`, `REPORT.md`, `DATA_SOURCES.md`
- `data/processed/monthly_analysis.csv`
- `outputs/source_manifest.json`, `outputs/forecast.csv`, `outputs/metrics.json`, `outputs/figures/*.png`
- `tests/test_analysis.py`

## 12. 보너스 과제 A — Streamlit 공개 URL 만들기

1. <https://share.streamlit.io/>에 GitHub 계정으로 로그인한다.
2. `Create app` 또는 `New app`을 누른다.
3. Repository에 `hahahoho12360/hanwha-life-timeseries-analysis`를 고른다.
4. Branch는 `main`을 고른다.
5. Main file path에는 `dashboard.py`를 적는다.
6. `Deploy`를 누르고 설치가 끝날 때까지 기다린다.
7. 배포된 주소는 <https://hanwha-life-timeseries-analysis-3kcrxnzdhpt9e9e9jb8ckm.streamlit.app/>이다.
8. 시크릿 브라우저에서 주소를 열어 그래프가 보이는지 확인한다.
9. 아래 두 주소를 README와 REPORT에 동일하게 기록하고 다시 커밋·푸시한다.

```text
README 공개 대시보드 URL: https://hanwha-life-timeseries-analysis-3kcrxnzdhpt9e9e9jb8ckm.streamlit.app/
REPORT 공개 대시보드 URL: https://hanwha-life-timeseries-analysis-3kcrxnzdhpt9e9e9jb8ckm.streamlit.app/
```

수정 후 업로드:

```powershell
git add README.md REPORT.md
git commit -m "Add deployed dashboard URL"
git push
```

대시보드는 배포 서버에서 원자료를 다시 수집하지 않고 GitHub의 `data/processed/monthly_analysis.csv`를 읽는다. 따라서 KRX 비밀번호를 Streamlit에 넣을 필요가 없다.

## 13. 산출물 폴더 읽는 법

```text
analysis.py                         전체 수집·정제·분석·예측·보고서 생성
dashboard.py                        Streamlit 대시보드
REPORT.md                           자동 생성 최종 분석 보고서
DATA_SOURCES.md                     출처·수집·라이선스·검산법
VERIFICATION.md                     실데이터 실행·3시점·핵심 수치 교차검산 기록
requirements.txt                    설치할 라이브러리 범위
requirements-lock.txt               실제 설치 버전
data/raw/                           실행 때 내려받은 원자료
data/manual/                        수동 입력 템플릿
data/processed/monthly_analysis.csv 월별 최종 분석표
outputs/data_quality_profile.csv    결측·이상치 점검표
outputs/source_manifest.json        실제 사용 출처·대체경로 공개 명세
outputs/cross_check_points.csv      원자료 수준값 3개 시점 재계산 검산표
outputs/metric_cross_check.csv      REPORT·JSON 핵심 수치 교차검산표
outputs/metrics.json                핵심 숫자와 예측 성능
outputs/forecast.csv                향후 3개월 예측값과 구간
outputs/figures/                    제출용 그래프 6개 이상
tests/test_analysis.py              자동검사
```

---

# **2. 최종 결과물 — 제출 직전 가장 중요**

> **아래는 연습 파일이 아니라 `--source live` 실행 결과로 제출한다. 하나라도 빠지면 제출하지 않는다.**

## **필수 제출 묶음**

1. **`REPORT.md`**
   - 주제와 3개 이상의 분석 질문
   - 자료 출처·수집 기간·변수·월 집계 기준
   - 결측치·이상치 점검과 판단 이유
   - 2개 이상의 시계열 기법과 각 기법의 목적
   - 3개 이상의 그래프
   - 수치와 기간을 근거로 한 3개 이상의 인사이트
   - 관찰 사실과 해석 가설의 분리
   - 반례, 결론, 한계, 다음에 모을 자료
   - AI 사용 작업·이유·사람의 검증 방법

2. **Python 스크립트**
   - **`analysis.py`**: 수집 → 정제 → 분석 → 시각화 → 예측 → 보고서 자동 생성
   - **`dashboard.py`**: 기간·비교 변수·시장 조건을 바꿀 수 있는 웹 대시보드
   - 노트북만 제출하지 않고 `.py` 파일을 제출한다.

3. **시각화 파일 3개 이상**
   - 이 프로젝트는 `outputs/figures/`에 6개 이상을 만든다.
   - 예측 그래프 `06_baseline_forecast.png`를 반드시 포함한다.

4. **재현 자료**
   - `requirements.txt`, 가능하면 `requirements-lock.txt`
   - `README.md` 실행 방법
   - `DATA_SOURCES.md` 출처·수집·라이선스와 `outputs/source_manifest.json` 실제 사용 출처 명세
   - `data/processed/monthly_analysis.csv`

5. **제출 링크 2개**
   - GitHub 저장소 URL 1개: <https://github.com/hahahoho12360/hanwha-life-timeseries-analysis>
   - **실제로 접속되는 웹 대시보드 URL 1개**: <https://hanwha-life-timeseries-analysis-3kcrxnzdhpt9e9e9jb8ckm.streamlit.app/>

6. **보너스 두 가지 모두**
   - **웹 대시보드**: 기간·조건을 사용자가 바꾸고 공개 URL로 접속 가능
   - **(B) 간단 예측**: AR(3) Ridge, 검증구간·기준선 MAE 비교, 3개월 예측 그림, 가정·한계 설명

## **최종 제출 전 30초 확인**

- [x] `REPORT.md` 첫 부분이 실자료라고 표시되고 ‘연습용 가상자료’ 경고가 없다.
- [x] 월별 완전 관측치가 100개 이상이다.
- [x] 그래프가 3개 이상 열리고 숫자가 서로 모순되지 않는다.
- [x] `REPORT.md`의 숫자 3개를 CSV나 `metrics.json`으로 직접 다시 계산했다.
- [x] GitHub 공개 URL에서 저장소와 30개 파일을 확인했다.
- [x] Streamlit 공개 URL에서 140개 관측치·필터·그래프·예측·CSV 다운로드 영역을 확인했다.
- [x] `.env`, KRX 아이디·비밀번호, 개인 API 키가 GitHub에 없다.
- [x] 표와 문장에 ‘원인’이라고 단정하지 않고 ‘동행·상관·가능성’으로 썼다.

---

## 14. 평가문항 17개 전체 대응표

아래 문장을 하나씩 소리 내어 읽고 체크한다. 자동 생성되는 `REPORT.md`에도 같은 대응표가 들어간다.

| 번호 | 평가문항 | 이 프로젝트의 증거 |
|---:|---|---|
| 1 | 시계열 데이터가 100개 이상의 관측치를 포함하는가? | 실행 검증 `assert`, 보고서 관측 월 수, 월별 CSV |
| 2 | 데이터로 답할 수 있는 명확한 분석 질문이 3개 이상인가? | 보고서에 질문 6개 |
| 3 | 시계열 분석 기법을 2개 이상 적용하고 보고서에 설명했는가? | 변화율, 상관, 이동통계, 국면 비교, 추세 대용 |
| 4 | 요구된 시각화를 2개 이상 만들었는가? | 가격 흐름·상관 히트맵 등 |
| 5 | 권장 시각화를 추가해 총 3개 이상 만들었는가? | `outputs/figures/`에 6개 이상 |
| 6 | 수치·기간 근거가 있는 인사이트를 3개 이상 제시했는가? | 보고서 자동 생성 인사이트 4개 이상 |
| 7 | GitHub에 코드·보고서·실행 방법·데이터 출처가 모두 있는가? | `.py`, `REPORT.md`, `README.md`, `DATA_SOURCES.md` |
| 8 | 데이터 불러오기→정제→분석→시각화 흐름을 설명할 수 있는가? | 이 README 0장과 `analysis.py` 함수 순서 |
| 9 | 결측치·이상치 처리 기준과 그 이유를 설명할 수 있는가? | README 7장과 품질 점검 CSV |
| 10 | 시간 단위로 어떻게 집계했고 왜 그 단위를 골랐는지 설명할 수 있는가? | README 5장: 월말·월평균·월 단위 이유 |
| 11 | 각 시계열 기법으로 무엇을 보려 했는지 설명할 수 있는가? | README 8장 표와 보고서 방법 절 |
| 12 | 추세·계절성·잡음 중 하나 이상을 그래프에서 어떻게 구분했는가? | 12개월 중심 이동평균=추세 대용, 잔차=단기 잡음 대용 |
| 13 | AI가 만든 코드와 해석을 어떻게 검증했는지 설명할 수 있는가? | 단위검사, sample 실행, 원자료 3시점 대조, AI 로그 |
| 14 | 인사이트 하나 이상을 Fact→Why→Action 구조로 설명했는가? | 보고서 인사이트 절에서 관찰→가설→행동 순서 |
| 15 | 분석 결론과 다른 반례를 하나 이상 제시했는가? | 보험업지수 상승·한화생명 하락 월 비율과 시기 |
| 16 | 분석의 한계와 다음에 더 수집·검증할 자료를 제시했는가? | IFRS 17, 인과 한계, CSM·K-ICS·수급·공시 이벤트 |
| 17 | AI 없이 결론을 재구성할 수 있도록 AI 사용 이유와 검증 로그가 충분한가? | 원자료→처리 CSV→지표 JSON→그래프 재계산 경로 기록 |

## 15. 발표할 때 쓸 쉬운 설명

다음 순서로 말하면 된다.

1. **Fact(관찰):** “2015년부터 2026년까지 월별 자료를 모았고, 한화생명과 보험업지수의 상관계수는 보고서에 나온 값이었다.”
2. **Why(가설):** “같은 보험업의 공통 금리·규제·투자심리 영향을 받았을 가능성이 있다. 하지만 상관만으로 원인이라고 말할 수 없다.”
3. **Action(행동):** “이동상관이 약해진 시기를 따로 보고, 공시·CSM·K-ICS·외국인 수급을 추가해 확인하겠다.”
4. **반례:** “보험업지수는 올랐지만 한화생명은 내린 달도 있었고, 그 비율과 날짜를 함께 제시했다.”
5. **예측 한계:** “AR(3)은 과거 3개월만 보는 기준선이므로 정책·공시 충격은 예측하지 못한다.”

실제 발표에서는 위 문장의 ‘보고서에 나온 값’을 `REPORT.md`의 숫자로 바꾼다.

## 16. 오류가 날 때

### `py` 또는 `python`을 찾을 수 없음

Python 3.11을 다시 설치하면서 `Add Python to PATH`를 체크하고 Visual Studio Code를 완전히 껐다 켠다.

### PowerShell에서 스크립트를 실행할 수 없음

현재 터미널에만 적용되는 다음 명령을 실행하고 다시 활성화한다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### `ModuleNotFoundError`

터미널 앞에 `(.venv)`가 있는지 확인하고 다시 설치한다.

```powershell
python -m pip install -r requirements.txt
```

### KRX 로그인·보험업지수 수집 실패

`.env`의 아이디와 비밀번호, KRX 사이트 로그인을 확인한다. 계속 실패하면 6-1의 수동 CSV를 채운다. 짧은 시간에 반복 실행하지 않는다.

### 100개 미만 오류

`outputs/data_quality_profile.csv`에서 어느 변수가 많이 비었는지 확인한다. 종료일을 억지로 미래로 늘리지 말고, 보험업지수 수동 CSV와 자료 코드·날짜·단위를 먼저 점검한다.

### Streamlit에서 데이터가 없다고 나옴

`python analysis.py --source live ...`를 먼저 실행하고 `data/processed/monthly_analysis.csv`를 GitHub에 커밋했는지 확인한다.

### 글자가 네모로 보임

그래프 숫자와 선은 정상일 수 있다. 운영체제에 `Noto Sans CJK KR` 또는 `맑은 고딕`을 설치한 뒤 다시 실행한다.

## 17. 핵심 자료 출처

세부 코드·단위·이용 주의는 [DATA_SOURCES.md](DATA_SOURCES.md)에 있다.

- FinanceDataReader: <https://github.com/FinanceData/FinanceDataReader>
- pykrx: <https://github.com/sharebook-kr/pykrx>
- KRX 데이터 마켓플레이스: <https://data.krx.co.kr/>
- 한화생명 IR: <https://www.hanwhalife.com/company/ir/main/main.do>
- 금융감독원 DART: <https://dart.fss.or.kr/>
- FRED 한국 10년물: <https://fred.stlouisfed.org/series/IRLTLT01KRM156N>
- FRED 원/달러: <https://fred.stlouisfed.org/series/DEXKOUS>
- FRED 미국 10년물: <https://fred.stlouisfed.org/series/DGS10>
- FRED 한국 실질 GDP: <https://fred.stlouisfed.org/series/NGDPRSAXDCKRQ>

## 18. 제출 URL 기록란

- GitHub 저장소 URL: <https://github.com/hahahoho12360/hanwha-life-timeseries-analysis>
- 공개 대시보드 URL: <https://hanwha-life-timeseries-analysis-3kcrxnzdhpt9e9e9jb8ckm.streamlit.app/>

두 주소는 `analysis.py`의 기본값과 `REPORT.md`에도 동일하게 기록되어 있어 재실행해도 유지된다. 주소가 바뀌면 실행 옵션과 README를 함께 갱신한다.
