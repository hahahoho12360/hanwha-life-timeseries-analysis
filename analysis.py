"""한화생명과 금리·환율·보험업 시장환경의 관계를 분석하는 실행 스크립트.

실행 예시
---------
1) 인터넷 없이 구조부터 확인:
   python analysis.py --source sample

2) 실제 자료 수집·분석:
   python analysis.py --source live --start 2015-01-01

이 스크립트는 원자료/정제자료/그래프/REPORT.md/예측 결과를 한 번에 만든다.
투자 권유 도구가 아니라 교육용 탐색 분석 도구다.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import font_manager
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


PROJECT_ROOT = Path(__file__).resolve().parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
MANUAL_DIR = PROJECT_ROOT / "data" / "manual"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
FIGURE_DIR = OUTPUT_DIR / "figures"
DEFAULT_GITHUB_URL = "https://github.com/hahahoho12360/hanwha-life-timeseries-analysis"
DEFAULT_DASHBOARD_URL = (
    "https://hanwha-life-timeseries-analysis-3kcrxnzdhpt9e9e9jb8ckm.streamlit.app/"
)


@dataclass(frozen=True)
class Config:
    start: pd.Timestamp
    end: pd.Timestamp
    source: str
    rolling_window: int = 12
    forecast_horizon: int = 3
    minimum_points: int = 100
    github_url: str = DEFAULT_GITHUB_URL
    dashboard_url: str = DEFAULT_DASHBOARD_URL


def ensure_directories() -> None:
    for path in (RAW_DIR, MANUAL_DIR, PROCESSED_DIR, OUTPUT_DIR, FIGURE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def write_source_manifests(source_manifest: list[dict[str, str]], config: Config) -> None:
    """원자료 경로와 실제 대체경로를 로컬·공개 명세에 함께 기록한다.

    ``data/raw``는 재배포 주의 때문에 Git에서 제외한다. 따라서 같은 명세를
    비밀정보 없이 ``outputs/source_manifest.json``에도 저장해 평가자가 실제로
    사용된 계열과 대체경로를 저장소에서 확인할 수 있게 한다.
    """
    payload = {
        "source_mode": config.source,
        "analysis_period": {
            "requested_start": config.start.strftime("%Y-%m-%d"),
            "requested_end": config.end.strftime("%Y-%m-%d"),
        },
        "generated_at_utc": pd.Timestamp.now(tz="UTC").floor("s").isoformat(),
        "raw_data_policy": (
            "data/raw is generated locally and excluded from Git; this public manifest "
            "contains only source metadata and no credentials."
        ),
        "sources": source_manifest,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    (RAW_DIR / "source_manifest.json").write_text(serialized, encoding="utf-8")
    (OUTPUT_DIR / "source_manifest.json").write_text(serialized, encoding="utf-8")


def last_complete_month_end(today: date | None = None) -> pd.Timestamp:
    """진행 중인 달을 제외한 직전 월말을 반환한다."""
    now = pd.Timestamp(today or date.today())
    first_day_this_month = now.replace(day=1).normalize()
    return first_day_this_month - timedelta(days=1)


def configure_plot_style() -> None:
    """가능하면 한글 글꼴을 쓰고, 없으면 영문 라벨로도 깨지지 않게 설정한다."""
    candidates = [
        "Malgun Gothic",
        "AppleGothic",
        "NanumGothic",
        "Noto Sans CJK KR",
        "Noto Sans KR",
    ]
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in candidates:
        if candidate in installed:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False
    sns.set_theme(style="whitegrid")


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        warnings.warn(
            "python-dotenv가 없어 .env를 읽지 못했습니다. "
            "실자료 모드라면 pip install -r requirements.txt를 먼저 실행하세요."
        )


def clean_numeric(value: Any) -> float:
    """'1,234', '(200)', '-', '3.5%' 같은 값을 숫자로 바꾼다."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "-", "--", "N/A", "nan", "None"}:
        return np.nan
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        number = float(text)
    except ValueError:
        return np.nan
    return -number if negative else number


def select_numeric_series(frame: pd.DataFrame, preferred: Iterable[str] = ()) -> pd.Series:
    """데이터 제공처마다 다른 열 이름 중 분석할 숫자열 하나를 안전하게 고른다."""
    if frame is None or frame.empty:
        raise ValueError("가져온 데이터가 비어 있습니다.")
    data = frame.copy()
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data.loc[~data.index.isna()].sort_index()
    for name in preferred:
        if name in data.columns:
            return pd.to_numeric(data[name], errors="coerce").dropna()
    for column in data.columns:
        series = pd.to_numeric(data[column], errors="coerce")
        if series.notna().sum() > 0:
            return series.dropna()
    raise ValueError(f"숫자 열을 찾지 못했습니다. 열 목록: {list(data.columns)}")


def month_end_last(series: pd.Series) -> pd.Series:
    """주가·지수처럼 '월말 현재값'이 의미 있는 자료를 월말값으로 집계한다."""
    series = series.copy().sort_index()
    series.index = pd.to_datetime(series.index)
    return series.resample("ME").last().dropna()


def month_end_mean(series: pd.Series) -> pd.Series:
    """금리·환율처럼 일별 변동이 큰 자료를 월평균으로 집계한다."""
    series = series.copy().sort_index()
    series.index = pd.to_datetime(series.index)
    return series.resample("ME").mean().dropna()


def quarter_end(series: pd.Series) -> pd.Series:
    series = series.copy().sort_index()
    series.index = pd.to_datetime(series.index)
    return series.resample("QE").last().dropna()


def save_raw_series(series: pd.Series, filename: str, column_name: str) -> None:
    series.rename(column_name).to_csv(RAW_DIR / filename, encoding="utf-8-sig")


def fetch_fdr_series(fdr: Any, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    frame = fdr.DataReader(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    short_symbol = symbol.split(":")[-1]
    return select_numeric_series(frame, preferred=("Close", "Adj Close", "종가", short_symbol))


def fetch_fred_official(series_id: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """FRED가 제공하는 공식 CSV를 재시도와 함께 직접 읽는다.

    FinanceDataReader의 FRED 어댑터가 간헐적으로 연결을 끊는 환경에서도 같은
    FRED 원자료를 재현할 수 있도록 둔 명시적 대체 경로다.
    """
    import requests

    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    params = {
        "id": series_id,
        "cosd": start.strftime("%Y-%m-%d"),
        "coed": end.strftime("%Y-%m-%d"),
    }
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": "hanwha-life-timeseries-education/1.0"},
                timeout=45,
            )
            response.raise_for_status()
            frame = pd.read_csv(io.StringIO(response.text))
            if frame.empty or len(frame.columns) < 2:
                raise ValueError(f"FRED {series_id} CSV가 비어 있습니다.")
            dates = pd.to_datetime(frame.iloc[:, 0], errors="coerce")
            values = pd.to_numeric(frame[series_id], errors="coerce")
            series = pd.Series(values.to_numpy(), index=dates, name=series_id).dropna()
            series = series.loc[~series.index.isna()].sort_index()
            if series.empty:
                raise ValueError(f"FRED {series_id}에서 숫자 관측치를 찾지 못했습니다.")
            return series
        except Exception as exc:  # 네트워크 일시 오류만 짧게 재시도
            last_error = exc
            if attempt < 3:
                time.sleep(attempt)
    raise RuntimeError(f"FRED 공식 CSV 수집 실패({series_id}): {last_error!r}") from last_error


def fetch_insurance_index_pykrx(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """KRX KOSPI 보험 지수(1025)의 월별 종가를 가져온다."""
    from pykrx import stock

    start_text = start.strftime("%Y%m%d")
    end_text = end.strftime("%Y%m%d")
    if hasattr(stock, "get_index_ohlcv"):
        frame = stock.get_index_ohlcv(start_text, end_text, "1025", "m")
    else:  # 구버전 호환
        frame = stock.get_index_ohlcv_by_date(start_text, end_text, "1025", freq="m")
    series = select_numeric_series(frame, preferred=("종가", "Close"))
    # 월별 API가 월초 문자열을 돌려주는 경우에도 공통 월말축으로 변환한다.
    series.index = series.index.to_period("M").to_timestamp("M")
    return series[~series.index.duplicated(keep="last")].sort_index()


def load_manual_insurance_index() -> pd.Series | None:
    """내용이 실제로 있는 수동 KRX 보험업지수 파일만 읽는다."""
    path = MANUAL_DIR / "kospi_insurance.csv"
    if not path.exists() or path.stat().st_size == 0:
        return None
    frame = pd.read_csv(path)
    if frame.empty or not {"date", "close"}.issubset(frame.columns):
        return None
    dates = pd.to_datetime(frame["date"], errors="coerce")
    values = pd.to_numeric(frame["close"], errors="coerce")
    series = pd.Series(values.to_numpy(), index=dates, name="insurance_close").dropna()
    series = series.loc[~series.index.isna()]
    if series.empty:
        return None
    series.index = series.index.to_period("M").to_timestamp("M")
    return series[~series.index.duplicated(keep="last")].sort_index()


def parse_finstate_operating_profit(
    finstate: pd.DataFrame, end: pd.Timestamp | None = None
) -> pd.Series:
    """FinanceDataReader의 네이버 분기 재무제표에서 영업이익 행을 찾는다.

    제공처 화면 구조가 바뀔 수 있으므로 여러 형태를 허용하고, 해석에 실패하면
    조용히 틀린 값을 만들지 않고 명확한 오류를 낸다.
    """
    if finstate is None or finstate.empty:
        raise ValueError("분기 재무제표가 비어 있습니다.")
    table = finstate.copy()

    # 현재 FinanceDataReader 스냅샷은 날짜가 행, 계정명이 열인 형태다.
    if "영업이익" in table.columns:
        dates = pd.to_datetime(table.index, errors="coerce")
        values = pd.to_numeric(table["영업이익"], errors="coerce")
        series = pd.Series(values.to_numpy(), index=dates).dropna()
        series = series.loc[~series.index.isna()]
        series.index = series.index.to_period("Q").to_timestamp("Q")
        series = series[~series.index.duplicated(keep="last")].sort_index()
        if end is not None:
            series = series.loc[series.index <= end]
        if len(series) < 4:
            raise ValueError("영업이익 실제 분기값을 4개 이상 찾지 못했습니다.")
        return series.rename("operating_profit_krw_100m")

    candidate_rows: list[pd.Series] = []
    for idx in table.index:
        if "영업이익" in str(idx) and "률" not in str(idx):
            candidate_rows.append(table.loc[idx])
    if not candidate_rows:
        text_columns = [c for c in table.columns if table[c].dtype == "object"]
        for column in text_columns:
            mask = table[column].astype(str).str.contains("영업이익", na=False)
            if mask.any():
                candidate_rows.append(table.loc[mask].iloc[0])
                break
    if not candidate_rows:
        raise ValueError("분기 재무제표에서 '영업이익' 행을 찾지 못했습니다.")

    row = candidate_rows[0]
    records: dict[pd.Timestamp, float] = {}
    for label, value in row.items():
        match = re.search(r"(20\d{2})[^0-9]?(0?[1-9]|1[0-2])", str(label))
        if not match:
            continue
        year, month = int(match.group(1)), int(match.group(2))
        if month not in {3, 6, 9, 12}:
            continue
        amount = clean_numeric(value)
        if np.isfinite(amount):
            records[pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)] = amount
    if len(records) < 4:
        raise ValueError(
            "영업이익 분기값을 4개 이상 해석하지 못했습니다. "
            "data/manual/hanwha_operating_profit.csv를 직접 채워 주세요."
        )
    return pd.Series(records, name="operating_profit_krw_100m").sort_index()


def load_manual_operating_profit() -> pd.Series | None:
    path = MANUAL_DIR / "hanwha_operating_profit.csv"
    if not path.exists() or path.stat().st_size == 0:
        return None
    frame = pd.read_csv(path)
    required = {"quarter", "operating_profit_krw_100m"}
    if not required.issubset(frame.columns) or frame.empty:
        return None
    dates = pd.PeriodIndex(frame["quarter"].astype(str), freq="Q").to_timestamp("Q")
    values = pd.to_numeric(frame["operating_profit_krw_100m"], errors="coerce")
    series = pd.Series(values.to_numpy(), index=dates, name="operating_profit_krw_100m")
    return series.dropna().sort_index()


def collect_live_data(config: Config) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """실제 공개자료를 수집한다. 반환값은 월별 수준값, 분기 보조자료, 경고 목록이다."""
    load_dotenv_if_available()
    try:
        import FinanceDataReader as fdr
    except ImportError as exc:
        raise RuntimeError(
            "FinanceDataReader가 없습니다. 먼저 pip install -r requirements.txt를 실행하세요."
        ) from exc

    messages: list[str] = []
    source_manifest: list[dict[str, str]] = []
    # 분석 시작월의 수익률·금리차를 계산하려면 직전 달 수준값이 한 달 더 필요하다.
    history_start = config.start.to_period("M").to_timestamp() - pd.DateOffset(months=1)

    print("[1/7] 한화생명 주가 수집")
    hanwha_daily = fetch_fdr_series(fdr, "NAVER:088350", history_start, config.end)
    save_raw_series(hanwha_daily, "hanwha_daily.csv", "hanwha_close")
    source_manifest.append(
        {
            "variable": "hanwha_close",
            "series": "한화생명 088350",
            "access": "FinanceDataReader NAVER:088350",
            "url": "https://finance.naver.com/item/main.naver?code=088350",
            "raw_file": "data/raw/hanwha_daily.csv",
        }
    )

    print("[2/7] KOSPI 지수 수집")
    kospi_daily = fetch_fdr_series(fdr, "KS11", history_start, config.end)
    save_raw_series(kospi_daily, "kospi_daily.csv", "kospi_close")
    source_manifest.append(
        {
            "variable": "kospi_close",
            "series": "KOSPI",
            "access": "FinanceDataReader KS11",
            "url": "https://data.krx.co.kr/",
            "raw_file": "data/raw/kospi_daily.csv",
        }
    )

    print("[3/7] 보험업 시장 계열 수집")
    manual_insurance = load_manual_insurance_index()
    insurance_access = ""
    insurance_url = ""
    if manual_insurance is not None:
        insurance_monthly = manual_insurance
        insurance_access = "수동 검증 CSV(KRX 보험업지수 1025)"
        insurance_url = "https://data.krx.co.kr/"
        messages.append("내용이 있는 수동 CSV에서 KRX 보험업지수(1025)를 사용했습니다.")
    elif os.getenv("KRX_ID") and os.getenv("KRX_PW"):
        try:
            insurance_monthly = fetch_insurance_index_pykrx(history_start, config.end)
            insurance_access = "pykrx KRX 보험업지수 1025"
            insurance_url = "https://data.krx.co.kr/"
            messages.append("KRX 보험업지수(1025)를 사용했습니다.")
        except Exception as exc:
            insurance_daily = fetch_fdr_series(fdr, "NAVER:140700", history_start, config.end)
            save_raw_series(
                insurance_daily, "kodex_insurance_140700_daily.csv", "insurance_proxy_close"
            )
            insurance_monthly = month_end_last(insurance_daily)
            insurance_access = "FinanceDataReader NAVER:140700 (KODEX 보험 ETF 대용변수)"
            insurance_url = "https://www.samsungfund.com/etf/lounge/notice-view.do?no=76573"
            messages.append(
                "KRX 보험업지수(1025) 자동 수집이 실패하여, 삼성자산운용이 KRX 보험지수 "
                f"추종 상품으로 명시한 KODEX 보험 ETF(140700)를 대용변수로 사용했습니다. 원인: {type(exc).__name__}"
            )
    else:
        insurance_daily = fetch_fdr_series(fdr, "NAVER:140700", history_start, config.end)
        save_raw_series(
            insurance_daily, "kodex_insurance_140700_daily.csv", "insurance_proxy_close"
        )
        insurance_monthly = month_end_last(insurance_daily)
        insurance_access = "FinanceDataReader NAVER:140700 (KODEX 보험 ETF 대용변수)"
        insurance_url = "https://www.samsungfund.com/etf/lounge/notice-view.do?no=76573"
        messages.append(
            "KRX 장기지수 호출에 계정 인증이 필요한 환경이라, 삼성자산운용이 KRX 보험지수 "
            "추종 상품으로 명시한 KODEX 보험 ETF(140700)를 보험업 시장 대용변수로 사용했습니다. "
            "ETF 보수·분배금·추적오차 때문에 원지수와 완전히 같지는 않습니다."
        )
    save_raw_series(insurance_monthly, "kospi_insurance_monthly.csv", "insurance_close")
    source_manifest.append(
        {
            "variable": "insurance_close",
            "series": "보험업 시장 계열",
            "access": insurance_access,
            "url": insurance_url,
            "raw_file": "data/raw/kospi_insurance_monthly.csv",
        }
    )

    print("[4/7] 한국 10년물·원/달러·미국 10년물 수집")
    kr10y = fetch_fred_official("IRLTLT01KRM156N", history_start, config.end)
    usdkrw = fetch_fred_official("DEXKOUS", history_start, config.end)
    us10y = fetch_fred_official("DGS10", history_start, config.end)
    save_raw_series(kr10y, "fred_korea_10y.csv", "kr10y_pct")
    save_raw_series(usdkrw, "fred_usdkrw.csv", "usdkrw")
    save_raw_series(us10y, "fred_us_10y.csv", "us10y_pct")
    source_manifest.extend(
        [
            {
                "variable": "kr10y_pct",
                "series": "FRED IRLTLT01KRM156N",
                "access": "FRED 공식 CSV",
                "url": "https://fred.stlouisfed.org/series/IRLTLT01KRM156N",
                "raw_file": "data/raw/fred_korea_10y.csv",
            },
            {
                "variable": "usdkrw",
                "series": "FRED DEXKOUS",
                "access": "FRED 공식 CSV",
                "url": "https://fred.stlouisfed.org/series/DEXKOUS",
                "raw_file": "data/raw/fred_usdkrw.csv",
            },
            {
                "variable": "us10y_pct",
                "series": "FRED DGS10",
                "access": "FRED 공식 CSV",
                "url": "https://fred.stlouisfed.org/series/DGS10",
                "raw_file": "data/raw/fred_us_10y.csv",
            },
        ]
    )

    monthly_levels = pd.concat(
        [
            month_end_last(hanwha_daily).rename("hanwha_close"),
            month_end_last(kospi_daily).rename("kospi_close"),
            insurance_monthly.rename("insurance_close"),
            month_end_mean(kr10y).rename("kr10y_pct"),
            month_end_mean(usdkrw).rename("usdkrw"),
            month_end_mean(us10y).rename("us10y_pct"),
        ],
        axis=1,
    ).sort_index()

    print("[5/7] 한국 실질 GDP 수집")
    gdp_level = fetch_fred_official("NGDPRSAXDCKRQ", config.start, config.end)
    gdp_level = quarter_end(gdp_level).rename("real_gdp_level")
    save_raw_series(gdp_level, "fred_korea_real_gdp_quarterly.csv", "real_gdp_level")

    print("[6/7] 한화생명 분기 영업이익 공식 검증자료 확인")
    operating_profit = load_manual_operating_profit()
    if operating_profit is None:
        operating_profit = pd.Series(dtype=float, name="operating_profit_krw_100m")
        operating_profit_access = "공식 검증 CSV 미제공: 보조 분석에서 제외"
        operating_profit_url = "https://dart.fss.or.kr/"
        messages.append(
            "공식 출처로 검증된 분기 영업이익 CSV가 비어 있어 보조 분석에서 제외했습니다. "
            "오해 가능성이 있는 비공식 자동 스냅샷으로 대체하지 않습니다."
        )
    else:
        operating_profit = operating_profit.loc[operating_profit.index <= config.end]
        operating_profit_access = "수동 검증 CSV(DART 연결 포괄손익계산서)"
        operating_profit_url = (
            "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260831001232"
        )
        messages.append(
            "한화생명 분기 영업이익은 DART 연결 포괄손익계산서로 검증한 "
            f"{len(operating_profit)}개 분기 CSV를 사용했습니다. 직접값과 누적액 차감식은 "
            "data/manual/hanwha_operating_profit.csv에 기록했습니다."
        )

    source_manifest.extend(
        [
            {
                "variable": "real_gdp_level",
                "series": "FRED NGDPRSAXDCKRQ",
                "access": "FRED 공식 CSV",
                "url": "https://fred.stlouisfed.org/series/NGDPRSAXDCKRQ",
                "raw_file": "data/raw/fred_korea_real_gdp_quarterly.csv",
            },
            {
                "variable": "operating_profit_krw_100m",
                "series": "한화생명 분기 영업이익(보조)",
                "access": operating_profit_access,
                "url": operating_profit_url,
                "raw_file": "data/manual/hanwha_operating_profit.csv",
            },
        ]
    )
    write_source_manifests(source_manifest, config)

    quarterly_aux = pd.concat(
        [gdp_level, operating_profit.rename("operating_profit_krw_100m")], axis=1
    ).sort_index()
    print("[7/7] 실제 자료 수집 완료")
    return monthly_levels, quarterly_aux, messages


def collect_sample_data(config: Config) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """인터넷 없이 전체 파이프라인을 시험할 수 있는 가상 자료를 만든다."""
    rng = np.random.default_rng(20260920)
    index = pd.date_range(config.start, config.end, freq="ME")
    n = len(index)
    market_return = rng.normal(0.45, 4.2, n)
    insurance_return = 0.75 * market_return + rng.normal(0.05, 2.8, n)
    kr10y_change = rng.normal(0.0, 0.14, n)
    us10y_change = 0.35 * kr10y_change + rng.normal(0.0, 0.12, n)
    fx_return = -0.25 * market_return + rng.normal(0.1, 2.0, n)
    hanwha_return = (
        0.62 * insurance_return
        + 0.10 * market_return
        - 0.20 * fx_return
        - 1.4 * kr10y_change
        + rng.normal(0.0, 4.8, n)
    )

    def price_path(base: float, returns: np.ndarray) -> np.ndarray:
        return base * np.cumprod(1.0 + returns / 100.0)

    monthly_levels = pd.DataFrame(
        {
            "hanwha_close": price_path(8_000, hanwha_return),
            "kospi_close": price_path(1_900, market_return),
            "insurance_close": price_path(14_000, insurance_return),
            "kr10y_pct": 2.2 + np.cumsum(kr10y_change),
            "usdkrw": price_path(1_100, fx_return),
            "us10y_pct": 2.0 + np.cumsum(us10y_change),
        },
        index=index,
    )

    q_index = pd.date_range(config.start, config.end, freq="QE")
    qn = len(q_index)
    gdp_growth = rng.normal(0.55, 0.75, qn)
    op_growth = rng.normal(3.0, 18.0, qn)
    quarterly_aux = pd.DataFrame(
        {
            "real_gdp_level": 450_000_000 * np.cumprod(1 + gdp_growth / 100),
            "operating_profit_krw_100m": 2_000 * np.cumprod(1 + op_growth / 100),
        },
        index=q_index,
    )
    messages = [
        "현재 결과는 연습용 가상자료입니다. 그래프·숫자·REPORT.md를 최종 제출하면 안 됩니다."
    ]
    return monthly_levels, quarterly_aux, messages


def robust_outlier_flags(series: pd.Series, threshold: float = 3.5) -> pd.Series:
    """중앙값 절대편차(MAD) 기반 이상치 표시. 실제 관측값은 삭제하지 않는다."""
    values = pd.to_numeric(series, errors="coerce")
    median = values.median()
    mad = (values - median).abs().median()
    if not np.isfinite(mad) or mad == 0:
        return pd.Series(False, index=values.index)
    robust_z = 0.6745 * (values - median) / mad
    return robust_z.abs() > threshold


def profile_frame(frame: pd.DataFrame, stage: str) -> pd.DataFrame:
    rows = []
    for column in frame.columns:
        series = frame[column]
        rows.append(
            {
                "stage": stage,
                "column": column,
                "rows": len(series),
                "non_null": int(series.notna().sum()),
                "missing": int(series.isna().sum()),
                "missing_pct": round(float(series.isna().mean() * 100), 3),
                "start": str(series.dropna().index.min().date()) if series.notna().any() else "",
                "end": str(series.dropna().index.max().date()) if series.notna().any() else "",
            }
        )
    return pd.DataFrame(rows)


def process_monthly(monthly_levels: pd.DataFrame, config: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    levels = monthly_levels.copy()
    levels.index = pd.to_datetime(levels.index).to_period("M").to_timestamp("M")
    levels = levels[~levels.index.duplicated(keep="last")].sort_index()
    levels = levels.loc[levels.index <= config.end]
    before_profile = profile_frame(
        levels.loc[levels.index >= config.start], "before_transform"
    )

    result = levels.copy()
    # 가격·지수·환율은 비율변화(%), 금리는 수준차(%p)로 변환한다.
    result["hanwha_return_pct"] = result["hanwha_close"].pct_change(fill_method=None) * 100
    result["insurance_return_pct"] = result["insurance_close"].pct_change(fill_method=None) * 100
    result["kospi_return_pct"] = result["kospi_close"].pct_change(fill_method=None) * 100
    result["usdkrw_change_pct"] = result["usdkrw"].pct_change(fill_method=None) * 100
    result["kr10y_change_pp"] = result["kr10y_pct"].diff()
    result["us10y_change_pp"] = result["us10y_pct"].diff()
    # 앞 달은 계산에만 쓰고 최종 분석표는 사용자가 지정한 시작월부터 남긴다.
    result = result.loc[(result.index >= config.start) & (result.index <= config.end)]

    core = [
        "hanwha_return_pct",
        "insurance_return_pct",
        "kospi_return_pct",
        "kr10y_change_pp",
        "usdkrw_change_pct",
        "us10y_change_pp",
    ]
    # 서로 다른 출처를 같은 월로 맞춘 뒤, 핵심 변수 중 하나라도 없는 달만 제외한다.
    result = result.dropna(subset=core).copy()
    if len(result) < config.minimum_points:
        raise ValueError(
            f"완성된 월별 관측치가 {len(result)}개로, 최소 {config.minimum_points}개보다 적습니다. "
            "시작일·자료수집 오류·결측치를 확인하세요."
        )

    for column in core:
        result[f"outlier_{column}"] = robust_outlier_flags(result[column])

    window = config.rolling_window
    result["hanwha_return_12m_mean"] = result["hanwha_return_pct"].rolling(window).mean()
    result["hanwha_return_12m_vol"] = result["hanwha_return_pct"].rolling(window).std(ddof=1)
    for column in core[1:]:
        result[f"rolling_corr_{column}"] = result["hanwha_return_pct"].rolling(window).corr(
            result[column]
        )

    after_profile = profile_frame(result, "after_transform_and_core_drop")
    profile = pd.concat([before_profile, after_profile], ignore_index=True)
    profile.to_csv(OUTPUT_DIR / "data_quality_profile.csv", index=False, encoding="utf-8-sig")
    result.to_csv(PROCESSED_DIR / "monthly_analysis.csv", encoding="utf-8-sig", index_label="date")
    return result, profile


def process_quarterly(
    quarterly_aux: pd.DataFrame, monthly: pd.DataFrame
) -> pd.DataFrame:
    aux = quarterly_aux.copy()
    if aux.empty:
        return aux
    aux.index = pd.to_datetime(aux.index).to_period("Q").to_timestamp("Q")
    aux = aux[~aux.index.duplicated(keep="last")].sort_index()
    if "real_gdp_level" in aux:
        aux["gdp_qoq_pct"] = aux["real_gdp_level"].pct_change(fill_method=None) * 100
        aux["gdp_yoy_pct"] = aux["real_gdp_level"].pct_change(4, fill_method=None) * 100
    if "operating_profit_krw_100m" in aux:
        aux["operating_profit_yoy_pct"] = aux["operating_profit_krw_100m"].pct_change(
            4, fill_method=None
        ) * 100

    quarter_prices = monthly["hanwha_close"].resample("QE").last()
    aux["hanwha_quarterly_return_pct"] = quarter_prices.pct_change(fill_method=None) * 100
    aux.to_csv(PROCESSED_DIR / "quarterly_auxiliary.csv", encoding="utf-8-sig", index_label="date")
    return aux


def build_lagged_frame(series: pd.Series, lags: int = 3) -> pd.DataFrame:
    frame = pd.DataFrame({"target": series})
    for lag in range(1, lags + 1):
        frame[f"lag_{lag}"] = series.shift(lag)
    return frame.dropna()


def run_baseline_forecast(
    monthly: pd.DataFrame, horizon: int
) -> tuple[pd.DataFrame, dict[str, float]]:
    """AR(3) Ridge와 과거평균 베이스라인을 시간순서대로 비교하고 3개월 예측한다."""
    returns = monthly["hanwha_return_pct"].dropna()
    supervised = build_lagged_frame(returns, lags=3)
    holdout = min(12, max(6, len(supervised) // 8))
    train = supervised.iloc[:-holdout]
    test = supervised.iloc[-holdout:]
    features = ["lag_1", "lag_2", "lag_3"]

    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    model.fit(train[features], train["target"])
    test_prediction = model.predict(test[features])
    baseline_prediction = np.repeat(train["target"].mean(), len(test))
    model_mae = float(mean_absolute_error(test["target"], test_prediction))
    baseline_mae = float(mean_absolute_error(test["target"], baseline_prediction))

    train_fit = model.predict(train[features])
    residual_std = float(np.std(train["target"].to_numpy() - train_fit, ddof=1))
    history = returns.tolist()
    future_values: list[float] = []
    for _ in range(horizon):
        row = pd.DataFrame(
            [[history[-1], history[-2], history[-3]]], columns=features
        )
        prediction = float(model.predict(row)[0])
        future_values.append(prediction)
        history.append(prediction)

    future_dates = pd.date_range(returns.index[-1] + pd.offsets.MonthEnd(1), periods=horizon, freq="ME")
    forecast = pd.DataFrame(
        {
            "predicted_return_pct": future_values,
            "lower_95_pct": np.array(future_values) - 1.96 * residual_std,
            "upper_95_pct": np.array(future_values) + 1.96 * residual_std,
        },
        index=future_dates,
    )
    forecast.to_csv(OUTPUT_DIR / "forecast.csv", encoding="utf-8-sig", index_label="date")
    metrics = {
        "holdout_months": float(holdout),
        "model_mae_pct_point": model_mae,
        "historical_mean_baseline_mae_pct_point": baseline_mae,
        "residual_std_pct_point": residual_std,
    }
    return forecast, metrics


def save_figure(fig: plt.Figure, filename: str) -> None:
    fig.tight_layout()
    fig.savefig(FIGURE_DIR / filename, dpi=180, bbox_inches="tight")
    plt.close(fig)


def make_figures(
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    forecast: pd.DataFrame,
    config: Config,
) -> list[str]:
    paths: list[str] = []

    prices = monthly[["hanwha_close", "insurance_close", "kospi_close"]].dropna()
    rebased = prices.div(prices.iloc[0]).mul(100)
    fig, ax = plt.subplots(figsize=(12, 6))
    rebased.rename(
        columns={
            "hanwha_close": "Hanwha Life",
            "insurance_close": "Insurance market proxy",
            "kospi_close": "KOSPI",
        }
    ).plot(ax=ax, linewidth=1.8)
    ax.set(title="Rebased Price Indices (First Month = 100)", xlabel="Month", ylabel="Index")
    save_figure(fig, "01_rebased_prices.png")
    paths.append("outputs/figures/01_rebased_prices.png")

    variables = [
        "hanwha_return_pct",
        "insurance_return_pct",
        "kospi_return_pct",
        "kr10y_change_pp",
        "usdkrw_change_pct",
        "us10y_change_pp",
    ]
    corr = monthly[variables].corr()
    labels = ["Hanwha", "Insurance proxy", "KOSPI", "KR 10Y Δ", "USD/KRW Δ%", "US 10Y Δ"]
    fig, ax = plt.subplots(figsize=(9, 7))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0, vmin=-1, vmax=1, ax=ax)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.set_yticklabels(labels, rotation=0)
    ax.set_title("Contemporaneous Monthly Correlations")
    save_figure(fig, "02_correlation_heatmap.png")
    paths.append("outputs/figures/02_correlation_heatmap.png")

    rolling_columns = {
        "rolling_corr_insurance_return_pct": "Insurance proxy",
        "rolling_corr_kospi_return_pct": "KOSPI",
        "rolling_corr_kr10y_change_pp": "KR 10Y change",
        "rolling_corr_usdkrw_change_pct": "USD/KRW change",
        "rolling_corr_us10y_change_pp": "US 10Y change",
    }
    fig, ax = plt.subplots(figsize=(12, 6))
    monthly[list(rolling_columns)].rename(columns=rolling_columns).plot(ax=ax, linewidth=1.4)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set(
        title=f"{config.rolling_window}-Month Rolling Correlation with Hanwha Life Return",
        xlabel="Month",
        ylabel="Correlation",
        ylim=(-1, 1),
    )
    save_figure(fig, "03_rolling_correlations.png")
    paths.append("outputs/figures/03_rolling_correlations.png")

    log_price = np.log(monthly["hanwha_close"])
    trend = log_price.rolling(config.rolling_window, center=True, min_periods=6).mean()
    residual = log_price - trend
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(log_price.index, log_price, label="Log price", linewidth=1.2)
    axes[0].plot(trend.index, trend, label=f"{config.rolling_window}M centered mean (trend proxy)", linewidth=2)
    axes[0].set_title("Trend Proxy and Short-Run Deviation")
    axes[0].legend()
    axes[1].bar(residual.index, residual, width=20, color=np.where(residual >= 0, "#2b8cbe", "#de2d26"))
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_ylabel("Log price - trend proxy")
    axes[1].set_xlabel("Month")
    save_figure(fig, "04_trend_and_noise.png")
    paths.append("outputs/figures/04_trend_and_noise.png")

    regime = pd.DataFrame(
        {
            "Hanwha return": monthly["hanwha_return_pct"],
            "KR 10Y regime": np.where(monthly["kr10y_change_pp"] >= 0, "Rate up/flat", "Rate down"),
            "FX regime": np.where(monthly["usdkrw_change_pct"] >= 0, "KRW weaker", "KRW stronger"),
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    sns.boxplot(data=regime, x="KR 10Y regime", y="Hanwha return", ax=axes[0], hue="KR 10Y regime", legend=False)
    sns.boxplot(data=regime, x="FX regime", y="Hanwha return", ax=axes[1], hue="FX regime", legend=False)
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[0].set_title("Return by Korean 10Y Regime")
    axes[1].set_title("Return by USD/KRW Regime")
    save_figure(fig, "05_regime_comparison.png")
    paths.append("outputs/figures/05_regime_comparison.png")

    actual = monthly["hanwha_return_pct"].tail(36)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(actual.index, actual, marker="o", markersize=3, label="Actual monthly return")
    ax.plot(forecast.index, forecast["predicted_return_pct"], marker="o", linestyle="--", label="AR(3) Ridge forecast")
    ax.fill_between(
        forecast.index,
        forecast["lower_95_pct"],
        forecast["upper_95_pct"],
        alpha=0.2,
        label="Approx. 95% interval",
    )
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set(title="Short-Horizon Baseline Forecast", xlabel="Month", ylabel="Return (%)")
    ax.legend()
    save_figure(fig, "06_baseline_forecast.png")
    paths.append("outputs/figures/06_baseline_forecast.png")

    needed = {
        "gdp_qoq_pct",
        "operating_profit_krw_100m",
        "operating_profit_yoy_pct",
        "hanwha_quarterly_return_pct",
    }
    if not quarterly.empty and needed.issubset(quarterly.columns):
        plot_data = quarterly[list(needed)].dropna(how="all")
        if not plot_data.empty:
            fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=False)
            q_return = plot_data["hanwha_quarterly_return_pct"].dropna()
            axes[0].bar(q_return.index, q_return.values, width=55, color="#3182bd")
            axes[0].set_title("Hanwha Life Quarterly Return (%)")

            op_level = plot_data["operating_profit_krw_100m"].dropna()
            axes[1].bar(op_level.index, op_level.values, width=55, color="#31a354")
            op_yoy = plot_data["operating_profit_yoy_pct"].dropna()
            yoy_note = (
                f"; latest YoY {op_yoy.iloc[-1]:.1f}% (only {len(op_yoy)} computable point)"
                if not op_yoy.empty
                else ""
            )
            axes[1].set_title(f"Operating Profit (KRW 100 million, recent actual quarters){yoy_note}")

            gdp = plot_data["gdp_qoq_pct"].dropna()
            axes[2].bar(gdp.index, gdp.values, width=55, color="#756bb1")
            axes[2].set_title("Korea Real GDP QoQ (%)")
            for ax in (axes[0], axes[2]):
                locator = mdates.AutoDateLocator(minticks=4, maxticks=10)
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
            axes[1].set_xticks(op_level.index)
            axes[1].set_xticklabels(
                [f"{timestamp.year} Q{timestamp.quarter}" for timestamp in op_level.index]
            )
            for ax in axes:
                ax.axhline(0, color="black", linewidth=0.7)
                ax.set_xlabel("")
            save_figure(fig, "07_quarterly_auxiliary.png")
            paths.append("outputs/figures/07_quarterly_auxiliary.png")

    return paths


def markdown_table(frame: pd.DataFrame, digits: int = 3) -> str:
    printable = frame.copy()
    for column in printable.select_dtypes(include=[np.number]).columns:
        printable[column] = printable[column].round(digits)
    try:
        return printable.to_markdown(index=True)
    except ImportError:
        return "```text\n" + printable.to_string() + "\n```"


def relationship_summary(monthly: pd.DataFrame) -> dict[str, Any]:
    explanatory = [
        "insurance_return_pct",
        "kospi_return_pct",
        "kr10y_change_pp",
        "usdkrw_change_pct",
        "us10y_change_pp",
    ]
    correlations = monthly[["hanwha_return_pct", *explanatory]].corr()["hanwha_return_pct"].drop(
        "hanwha_return_pct"
    )
    strongest = correlations.abs().idxmax()
    rate_up = monthly.loc[monthly["kr10y_change_pp"] >= 0, "hanwha_return_pct"].mean()
    rate_down = monthly.loc[monthly["kr10y_change_pp"] < 0, "hanwha_return_pct"].mean()
    fx_up = monthly.loc[monthly["usdkrw_change_pct"] >= 0, "hanwha_return_pct"].mean()
    fx_down = monthly.loc[monthly["usdkrw_change_pct"] < 0, "hanwha_return_pct"].mean()
    disagreement = (
        (monthly["insurance_return_pct"] > 0) & (monthly["hanwha_return_pct"] < 0)
    ).mean() * 100
    rolling = monthly[f"rolling_corr_{strongest}"].dropna()
    return {
        "correlations": correlations,
        "strongest_variable": strongest,
        "strongest_correlation": float(correlations[strongest]),
        "rate_up_mean": float(rate_up),
        "rate_down_mean": float(rate_down),
        "fx_up_mean": float(fx_up),
        "fx_down_mean": float(fx_down),
        "disagreement_pct": float(disagreement),
        "rolling_min": float(rolling.min()),
        "rolling_max": float(rolling.max()),
    }


def build_report(
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    forecast_metrics: dict[str, float],
    messages: list[str],
    config: Config,
    figure_paths: list[str],
) -> str:
    summary = relationship_summary(monthly)
    correlations: pd.Series = summary["correlations"]
    uses_insurance_proxy = any("KODEX 보험 ETF" in message for message in messages)
    insurance_label = (
        "KODEX 보험 ETF(140700) 월간 수익률(보험업지수 대용)"
        if uses_insurance_proxy
        else "KOSPI 보험업지수 월간 수익률"
    )
    insurance_level_description = (
        "KODEX 보험 ETF(140700): KRX 보험지수를 추종하는 공식 상품의 각 달 마지막 거래일 종가를 "
        "보험업 시장 대용변수로 사용했다. ETF 보수·분배금·추적오차 때문에 원지수와 동일하지 않다."
        if uses_insurance_proxy
        else "KOSPI 보험 지수(1025): 각 달의 마지막 거래일 종가를 사용했다."
    )
    variable_labels = {
        "insurance_return_pct": insurance_label,
        "kospi_return_pct": "KOSPI 월간 수익률",
        "kr10y_change_pp": "한국 10년물 금리 변화(%p)",
        "usdkrw_change_pct": "원/달러 환율 변화율",
        "us10y_change_pp": "미국 10년물 금리 변화(%p)",
    }
    strongest_name = variable_labels[summary["strongest_variable"]]
    data_kind = "실제 공개자료" if config.source == "live" else "연습용 가상자료"
    mae_gap = (
        forecast_metrics["model_mae_pct_point"]
        - forecast_metrics["historical_mean_baseline_mae_pct_point"]
    )
    forecast_judgment = (
        f"AR(3) Ridge가 과거평균보다 MAE를 {abs(mae_gap):.2f}%p 낮췄다."
        if mae_gap < 0
        else f"AR(3) Ridge의 MAE가 과거평균보다 {mae_gap:.2f}%p 높아 기준선을 개선하지 못했다."
    )
    warning_banner = (
        "> [!CAUTION]\n> 이 보고서는 연습용 가상자료로 생성되었습니다. **최종 제출 금지**. "
        "실자료 모드로 다시 실행하세요.\n\n"
        if config.source == "sample"
        else ""
    )

    corr_table = correlations.rename("한화생명과의 상관계수").to_frame()
    outlier_columns = [c for c in monthly.columns if c.startswith("outlier_")]
    outlier_counts = monthly[outlier_columns].sum().rename("표시 건수").to_frame()
    source_warnings = "\n".join(f"- {message}" for message in messages) or "- 특이 경고 없음"
    images = "\n\n".join(f"![{Path(path).stem}]({path})" for path in figure_paths)

    quarterly_text = ""
    if not quarterly.empty:
        available = [
            c
            for c in [
                "hanwha_quarterly_return_pct",
                "operating_profit_yoy_pct",
                "gdp_qoq_pct",
                "gdp_yoy_pct",
            ]
            if c in quarterly.columns and quarterly[c].notna().sum() >= 4
        ]
        qcorr = quarterly[available].corr() if len(available) >= 2 else pd.DataFrame()
        op_level_count = int(quarterly.get("operating_profit_krw_100m", pd.Series(dtype=float)).notna().sum())
        op_yoy_count = int(quarterly.get("operating_profit_yoy_pct", pd.Series(dtype=float)).notna().sum())
        if config.source == "live" and op_level_count:
            operating_profit_note = (
                "영업이익은 DART 연결 포괄손익계산서의 3개월 값 또는 누적액 차감식으로 "
                f"검증한 최근 {op_level_count}개 분기다. "
            )
        elif config.source == "live":
            operating_profit_note = "공식 검증 영업이익이 없어 이 변수는 제외했다. "
        else:
            operating_profit_note = (
                f"연습용 가상 영업이익은 {op_level_count}개 분기이며 제출용 수치가 아니다. "
            )
        quarterly_text = (
            "### 보조 분기 분석\n\n"
            "분기 영업이익은 2023년 IFRS 17 도입 전후의 회계기준 변화 영향을 받을 수 있으므로 "
            "월별 핵심모형과 분리했다. GDP는 계절조정 실질 GDP 수준에서 전기 대비 성장률을 계산했다. "
            f"{operating_profit_note}전년동기 증가율은 "
            f"{op_yoy_count}개만 계산되어, 영업이익 상관계수는 표본 부족으로 제시하지 않는다.\n\n"
            + (markdown_table(qcorr) if not qcorr.empty else "비교 가능한 분기값이 충분하지 않다.")
        )

    evaluation_rows = [
        (1, "시계열 데이터가 100개 이상의 데이터 포인트를 포함하는가?", f"월별 완전관측치 {len(monthly)}개"),
        (2, "분석 질문이 3개 이상 명확하게 정의되어 있는가?", "아래 분석 질문 6개"),
        (3, "시계열 분석 기법 2가지 이상 결과가 리포트에 포함되어 있는가?", "변화율·12개월 이동통계·구간통계·상관"),
        (4, "시각화가 필수 2개 이상 포함되어 있는가?", f"총 {len(figure_paths)}개"),
        (5, "권장 시각화 1개를 추가해 총 3개 이상을 구성했는가?", "총 3개 이상 및 예측 그래프 포함"),
        (6, "인사이트가 3개 이상이며 각 인사이트에 관찰 근거가 포함되어 있는가?", "인사이트 1~4의 수치 근거"),
        (7, "GitHub 저장소에 코드·리포트·실행/데이터 출처 정보가 제공되는가?", "analysis.py, dashboard.py, REPORT.md, README.md, DATA_SOURCES.md"),
        (8, "데이터 로딩·정제·분석·시각화 흐름을 단계적으로 설명할 수 있는가?", "README의 실행 흐름 및 본 보고서 방법"),
        (9, "결측치·이상치 처리 기준을 왜 그렇게 정했는지 설명할 수 있는가?", "결측/이상치 원칙 절"),
        (10, "시각화의 집계 단위와 그 선택 이유를 설명할 수 있는가?", "월별 집계 이유 절"),
        (11, "적용한 시계열 기법이 무엇을 보려는 것인지 설명할 수 있는가?", "분석 방법 절"),
        (12, "트렌드·계절성·노이즈 중 최소 1개를 그래프에서 어떻게 구분했는지 설명할 수 있는가?", "그림 4의 이동평균 추세와 잔차"),
        (13, "AI가 만든 코드·해석을 어떤 방식으로 검증했는지 설명할 수 있는가?", "AI 사용 로그와 검증 절"),
        (14, "인사이트 1개를 관찰(Fact)→원인(Why)→행동(Action) 흐름으로 설명할 수 있는가?", "인사이트 1"),
        (15, "분석 결과가 달라질 수 있는 반례를 1개 이상 제시할 수 있는가?", "반례·민감도 절"),
        (16, "분석 한계와 다음 단계에서 추가 수집·검증할 데이터를 제안할 수 있는가?", "결론과 한계 절"),
        (17, "AI 사용 로그의 이유·검증 방법을 근거로 AI 없이도 핵심 결론을 재구성할 수 있는가?", "데이터·수식·검증 파일 및 AI 사용 로그"),
    ]
    evaluation = pd.DataFrame(evaluation_rows, columns=["번호", "평가문항", "대응 근거"]).set_index("번호")

    report = f"""# 금리·환율·보험업 시장환경과 한화생명 주가의 관계

## 2015~2026년 월별 시계열 분석

{warning_banner}**데이터 유형:** {data_kind}  
**분석 기간:** {monthly.index.min().date()} ~ {monthly.index.max().date()}  
**핵심 완전관측치:** {len(monthly)}개(최소 100개 기준 충족)  
**주의:** 본 결과는 상관·탐색 분석이며 인과관계나 투자수익을 보장하지 않는다.

## 1. 분석 주제와 질문

1. 한화생명 월간 수익률은 {insurance_label}과 같은 방향으로 움직이는가?
2. KOSPI 전체 시장을 통제하기 전의 단순 동행성은 어느 정도인가?
3. 한국 10년물 금리 변화와 원/달러 환율 변화가 한화생명 수익률과 어떤 관계를 보이는가?
4. 미국 10년물 금리 변화는 선택변수로서 추가 설명력을 암시하는가?
5. 관계가 전 기간에 안정적인가, 아니면 12개월 구간별로 달라지는가?
6. 보조적으로 한화생명 영업이익 증가율과 한국 GDP 성장률이 분기 주가수익률과 동행하는가?

## 2. 데이터 설명과 월별 집계 이유

- 한화생명(088350)·KOSPI: 각 달의 마지막 거래일 종가를 사용했다.
- {insurance_level_description}
- 한국·미국 10년물 및 원/달러: 일별 흔들림과 국가별 휴장일 차이를 줄이기 위해 월평균을 사용했다.
- 주가·지수·환율: 단위가 서로 다르므로 월간 변화율(%)로 바꿨다.
- 금리: 이미 % 수준이므로 비율변화가 아니라 전월 대비 차이(%p)를 사용했다.
- 월 단위를 택한 이유: 일별 잡음을 줄이고, 2015년 이후 100개 이상 관측치를 유지하면서 분기 실적보다 빠른 시장 반응을 살피기 위해서다.

## 3. 결측치·이상치 원칙

- 결측치는 값이 없는 달을 숫자로 꾸며내지 않기 위해 보간하지 않았다. 서로 다른 출처를 월말축으로 맞춘 뒤 핵심 변수 중 하나라도 없는 달만 제외했다.
- 첫 달의 수익률·차분은 이전 달이 없어서 계산할 수 없으므로 제외했다.
- 12개월 이동평균·이동변동성·이동상관의 첫 11개월 결측은 12개 월 창이 아직 채워지지 않아 생기는 **구조적 준비구간 결측**이다. 오류나 원자료 누락이 아니므로 보간·삭제하지 않았고, {len(monthly)}개 완전관측치 판정은 핵심 6개 변수에만 적용했다.
- 이상치는 중앙값 절대편차(MAD) 기준 robust z-score 절댓값 3.5 초과로 **표시만** 했다. 금융위기·코로나 같은 실제 충격일 수 있어 본 분석에서는 삭제하지 않았다.
- 이상치 제거 여부가 결론을 바꾸는지는 후속 민감도 분석 대상으로 남겼다.

이상치 표시 건수:

{markdown_table(outlier_counts)}

## 4. 분석 방법: 무엇을 보려는가

1. **월간 변화율/금리차:** 단위가 다른 수준값을 같은 변화 개념으로 비교한다.
2. **상관계수:** 같은 달에 두 변수가 함께 오르내리는 정도를 -1~1로 요약한다. 인과관계는 아니다.
3. **12개월 이동상관:** 관계가 시기별로 강해지거나 약해지는지 확인한다.
4. **상승·하락 구간 통계:** 금리·환율 방향에 따라 한화생명 평균수익률 분포가 달랐는지 비교한다.
5. **추세 대용치와 잔차:** 12개월 중심 이동평균을 완만한 추세 대용치로 두고, 실제 로그주가와의 차이를 단기 변동(잔차)으로 본다. 잔차가 순수한 통계적 노이즈라는 뜻은 아니다.
6. **간단 예측(B 보너스):** 과거 3개월 수익률만 쓰는 AR(3) Ridge를 시간순서로 검증하고 과거평균 베이스라인과 MAE를 비교한다.

## 5. 분석 결과 및 시각화

{images}

### 전 기간 상관계수

{markdown_table(corr_table)}

{quarterly_text}

## 6. 근거가 있는 인사이트

### 인사이트 1 - Fact → Why → Action

- **관찰(Fact):** 절댓값 기준 가장 큰 동행 변수는 **{strongest_name}**이며 상관계수는 **{summary['strongest_correlation']:.3f}**이다.
- **가능한 원인(Why·가설):** 한화생명도 보험업 공통의 금리·자본규제·투자자 심리 영향을 받기 때문일 수 있다. 그러나 공통 시장충격 때문에 함께 움직였을 가능성도 있다.
- **행동(Action):** 같은 달 상관만으로 매매 결론을 내리지 말고, KOSPI 통제 회귀와 시차변수·회사 고유 공시 이벤트를 추가해 가설을 검증한다.

### 인사이트 2 - 한국 10년물 방향별 차이

- **관찰:** 한국 10년물 금리가 상승·보합한 달의 한화생명 평균수익률은 **{summary['rate_up_mean']:.2f}%**, 하락한 달은 **{summary['rate_down_mean']:.2f}%**였다.
- **해석 가설:** 금리 변화는 운용수익 기대와 채권평가손익·부채할인율을 동시에 움직이므로 방향 하나만으로 보험사 가치가 결정되지 않는다.
- **행동:** 금리 수준, 장단기금리차, IFRS 17 이후 CSM·K-ICS 지표를 함께 붙여 재검증한다.

### 인사이트 3 - 환율 국면별 차이

- **관찰:** 원/달러가 상승(원화 약세)한 달의 평균수익률은 **{summary['fx_up_mean']:.2f}%**, 하락한 달은 **{summary['fx_down_mean']:.2f}%**였다.
- **해석 가설:** 해외자산 환산효과와 위험회피 심리가 서로 반대 방향으로 작용할 수 있다.
- **행동:** 해외투자자산 비중·환헤지 비율·외국인 수급을 추가해 환율 경로를 나눈다.

### 인사이트 4 - 관계의 시간가변성

- **관찰:** 가장 강한 변수와의 12개월 이동상관 범위는 **{summary['rolling_min']:.3f}~{summary['rolling_max']:.3f}**였다.
- **해석:** 전 기간 평균 상관 하나가 모든 시기에 그대로 적용되지 않는다.
- **행동:** 2020년 충격, 2022년 금리상승, 2023년 IFRS 17 도입 전후로 구간을 나눠 민감도를 비교한다.

## 7. 반례와 민감도

- 보험업 시장 계열이 오른 달인데 한화생명 수익률이 음수였던 비율은 전체 월의 **{summary['disagreement_pct']:.1f}%**다. 즉 업종 동행성이 있어도 회사 고유 요인 때문에 반대로 움직이는 반례가 존재한다.
- 월말 종가 대신 월평균 가격을 쓰거나, 동월이 아니라 1개월 시차를 주면 상관계수가 달라질 수 있다.
- 이상치를 제거하면 코로나·급격한 금리전환기의 정보가 사라질 수 있으므로, 원자료 유지 결과와 이상치 제외 결과를 나란히 비교하는 것이 바람직하다.

## 8. 보너스 B - 간단 예측 결과

- 검증구간: 최근 {int(forecast_metrics['holdout_months'])}개월
- AR(3) Ridge MAE: **{forecast_metrics['model_mae_pct_point']:.2f}%p**
- 과거평균 베이스라인 MAE: **{forecast_metrics['historical_mean_baseline_mae_pct_point']:.2f}%p**
- 검증 판단: **{forecast_judgment}** 따라서 예측값보다 기준선 비교와 한계 설명이 더 중요하다.
- 가정: 과거 3개월 수익률과 오차 분산의 관계가 짧은 미래에도 크게 변하지 않는다.
- 한계: 주가수익률은 잡음이 크고 구조변화·공시·정책충격을 모형이 모른다. 예측구간은 근사치이며 투자판단에 사용하지 않는다.

## 9. 결론과 한계

이 분석은 한화생명 수익률이 보험업·시장·금리·환율과 함께 움직인 정도와 그 관계의 시간변화를 보여준다. 가장 중요한 결론은 상관이 인과가 아니며, 전 기간 평균만으로 개별 시기를 설명할 수 없다는 점이다.

한계는 다음과 같다.

- 배당을 완전히 반영한 총수익률 여부를 제공처별로 다시 확인해야 한다.
- 보험업 ETF 대용변수를 쓴 경우 보수·분배금·추적오차로 KRX 보험업 원지수와 차이가 날 수 있다.
- 2026년은 완결된 연도가 아니며 마지막 완료 월까지만 사용했다.
- IFRS 17 도입으로 2023년 전후 영업이익 비교 가능성이 낮아질 수 있다.
- 회사 고유 변수(CSM, K-ICS, 신계약가치, 지급여력, 배당, 자사주)와 규제·공시 이벤트를 포함하지 않았다.
- 다음 단계에서는 외국인 수급, 장단기금리차, 보험부채 듀레이션, 공시 이벤트 더미를 수집하고 시차회귀·구간별 회귀로 검증한다.

## 10. AI 사용 로그와 검증

| 사용 작업 | 사용 이유 | 사람이 확인할 검증 방법 |
|---|---|---|
| 변수 정의·분석 질문·코드 구조 초안 | 빠르게 대안을 비교하고 누락을 줄이기 위해 | PDF 요구사항 17문항과 함수·산출물을 일대일 대조 |
| 수집·정제·그래프·예측 코드 작성 보조 | 반복 코드를 줄이기 위해 | sample 모드 전체 실행, 행 수·날짜·단위 assert, 원자료 첫/끝 5행 대조 |
| 인사이트 문장 초안 | 관찰·가설·행동을 분리하기 위해 | REPORT 숫자를 processed CSV로 재계산하고, 인과 표현을 상관 표현으로 교정 |

AI 없이 핵심 결론을 재구성하려면 먼저 `outputs/source_manifest.json`에서 실제 사용 출처와 대체경로를 확인한다. 그다음 `python analysis.py --source live ...`로 Git에서 제외된 `data/raw`를 다시 만들고, `data/raw` → `data/processed/monthly_analysis.csv` → `outputs/metrics.json` → 그래프 순서로 확인한다. 상관계수는 pandas `corr()`, 수익률은 `pct_change()*100`, 금리변화는 `diff()`로 직접 재계산할 수 있다.

## 11. 데이터 출처·수집 경고

{source_warnings}

상세 출처·라이선스·직접 링크는 [DATA_SOURCES.md](DATA_SOURCES.md)에 정리했다.

## 12. 17개 평가문항 대응표

{markdown_table(evaluation, digits=0)}

## 13. 제출 링크

- GitHub 저장소 URL: <{config.github_url}>
- 공개 웹 대시보드 URL: <{config.dashboard_url}>

두 주소는 로그아웃 또는 시크릿 브라우저에서도 열리는지 확인한다. 기본값은 현재 공개 주소이며,
저장소나 앱 주소가 바뀌면 `--github-url`과 `--dashboard-url` 옵션으로 안전하게 갱신할 수 있다.
"""
    report_path = PROJECT_ROOT / "REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    return report


def save_metrics(
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    forecast_metrics: dict[str, float],
    config: Config,
) -> None:
    summary = relationship_summary(monthly)
    payload = {
        "source_mode": config.source,
        "period": {"start": str(monthly.index.min().date()), "end": str(monthly.index.max().date())},
        "monthly_complete_observations": len(monthly),
        "quarterly_rows": len(quarterly),
        "correlations_with_hanwha": {
            key: float(value) for key, value in summary["correlations"].items()
        },
        "regime_means": {
            "kr10y_up_or_flat": summary["rate_up_mean"],
            "kr10y_down": summary["rate_down_mean"],
            "usdkrw_up": summary["fx_up_mean"],
            "usdkrw_down": summary["fx_down_mean"],
        },
        "counterexample_insurance_up_hanwha_down_pct": summary["disagreement_pct"],
        "forecast": forecast_metrics,
    }
    (OUTPUT_DIR / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_verification_artifacts(
    monthly_levels: pd.DataFrame,
    monthly: pd.DataFrame,
    forecast_metrics: dict[str, float],
    messages: list[str],
    config: Config,
) -> None:
    """원자료 3개 시점과 REPORT/JSON 핵심 수치를 독립 수식으로 대조한다."""
    levels = monthly_levels.copy()
    levels.index = pd.to_datetime(levels.index).to_period("M").to_timestamp("M")
    levels = levels[~levels.index.duplicated(keep="last")].sort_index()

    shock_target = pd.Timestamp("2020-03-31")
    if shock_target not in monthly.index:
        shock_position = monthly.index.get_indexer([shock_target], method="nearest")[0]
        shock_target = monthly.index[shock_position]
    check_dates = list(dict.fromkeys([monthly.index.min(), shock_target, monthly.index.max()]))
    formulas = {
        "hanwha_return_pct": ("hanwha_close", "pct"),
        "insurance_return_pct": ("insurance_close", "pct"),
        "kospi_return_pct": ("kospi_close", "pct"),
        "usdkrw_change_pct": ("usdkrw", "pct"),
        "kr10y_change_pp": ("kr10y_pct", "diff"),
        "us10y_change_pp": ("us10y_pct", "diff"),
    }
    raw_rows: list[dict[str, Any]] = []
    for check_date in check_dates:
        previous_date = check_date - pd.offsets.MonthEnd(1)
        for output_name, (level_name, method) in formulas.items():
            current = float(levels.at[check_date, level_name])
            previous = float(levels.at[previous_date, level_name])
            recalculated = (
                (current / previous - 1.0) * 100.0 if method == "pct" else current - previous
            )
            processed = float(monthly.at[check_date, output_name])
            difference = abs(recalculated - processed)
            raw_rows.append(
                {
                    "date": str(check_date.date()),
                    "variable": output_name,
                    "previous_month_level": previous,
                    "current_month_level": current,
                    "recalculated_change": recalculated,
                    "processed_change": processed,
                    "absolute_difference": difference,
                    "passed": difference <= 1e-10,
                }
            )
    raw_check = pd.DataFrame(raw_rows)
    raw_check.to_csv(OUTPUT_DIR / "cross_check_points.csv", index=False, encoding="utf-8-sig")

    summary = relationship_summary(monthly)
    metrics_payload = json.loads((OUTPUT_DIR / "metrics.json").read_text(encoding="utf-8"))
    strongest = summary["strongest_variable"]
    rolling_range = f"**{summary['rolling_min']:.3f}~{summary['rolling_max']:.3f}**"
    metric_specs = [
        (
            "monthly_complete_observations",
            float(len(monthly)),
            float(metrics_payload["monthly_complete_observations"]),
            f"**핵심 완전관측치:** {len(monthly)}개",
        ),
        (
            "strongest_correlation",
            float(summary["strongest_correlation"]),
            float(metrics_payload["correlations_with_hanwha"][strongest]),
            f"상관계수는 **{summary['strongest_correlation']:.3f}**",
        ),
        (
            "kr10y_up_or_flat_mean",
            float(summary["rate_up_mean"]),
            float(metrics_payload["regime_means"]["kr10y_up_or_flat"]),
            f"평균수익률은 **{summary['rate_up_mean']:.2f}%**",
        ),
        (
            "kr10y_down_mean",
            float(summary["rate_down_mean"]),
            float(metrics_payload["regime_means"]["kr10y_down"]),
            f"하락한 달은 **{summary['rate_down_mean']:.2f}%**",
        ),
        (
            "usdkrw_up_mean",
            float(summary["fx_up_mean"]),
            float(metrics_payload["regime_means"]["usdkrw_up"]),
            f"상승(원화 약세)한 달의 평균수익률은 **{summary['fx_up_mean']:.2f}%**",
        ),
        (
            "usdkrw_down_mean",
            float(summary["fx_down_mean"]),
            float(metrics_payload["regime_means"]["usdkrw_down"]),
            f"하락한 달은 **{summary['fx_down_mean']:.2f}%**",
        ),
        (
            "counterexample_pct",
            float(summary["disagreement_pct"]),
            float(metrics_payload["counterexample_insurance_up_hanwha_down_pct"]),
            f"전체 월의 **{summary['disagreement_pct']:.1f}%**",
        ),
        (
            "rolling_correlation_min",
            float(summary["rolling_min"]),
            None,
            rolling_range,
        ),
        (
            "rolling_correlation_max",
            float(summary["rolling_max"]),
            None,
            rolling_range,
        ),
        (
            "forecast_model_mae",
            float(forecast_metrics["model_mae_pct_point"]),
            float(metrics_payload["forecast"]["model_mae_pct_point"]),
            f"AR(3) Ridge MAE: **{forecast_metrics['model_mae_pct_point']:.2f}%p**",
        ),
        (
            "forecast_baseline_mae",
            float(forecast_metrics["historical_mean_baseline_mae_pct_point"]),
            float(metrics_payload["forecast"]["historical_mean_baseline_mae_pct_point"]),
            "과거평균 베이스라인 MAE: "
            f"**{forecast_metrics['historical_mean_baseline_mae_pct_point']:.2f}%p**",
        ),
    ]
    report_text = (PROJECT_ROOT / "REPORT.md").read_text(encoding="utf-8")
    metric_rows: list[dict[str, Any]] = []
    for name, recalculated, json_value, report_needle in metric_specs:
        json_difference = (
            abs(recalculated - json_value) if json_value is not None else np.nan
        )
        json_passed = json_value is None or json_difference <= 1e-12
        report_passed = report_needle in report_text
        metric_rows.append(
            {
                "metric": name,
                "recalculated_full_precision": recalculated,
                "json_value": json_value,
                "json_absolute_difference": json_difference,
                "report_display_text": report_needle,
                "report_text_found": report_passed,
                "passed": bool(json_passed and report_passed),
            }
        )
    metric_check = pd.DataFrame(metric_rows)
    metric_check.to_csv(OUTPUT_DIR / "metric_cross_check.csv", index=False, encoding="utf-8-sig")

    raw_passed = bool(raw_check["passed"].all())
    metric_passed = bool(metric_check["passed"].all())
    source_notes = "\n".join(f"- {message}" for message in messages) or "- 특이 경고 없음"
    verification = f"""# 실행·교차검산 기록

## 검증 환경

- 검증일: {date.today().isoformat()}
- Python: {sys.version.split()[0]}
- 실행 명령: `python analysis.py --source {config.source} --start {config.start.date()} --end {config.end.date()}`
- 최종 완전관측치: {len(monthly)}개 ({monthly.index.min().date()}~{monthly.index.max().date()})

## 자동검산 결과

- 원자료 수준값으로 3개 시점의 변화율·금리차를 다시 계산: **{'통과' if raw_passed else '실패'}**
- 처리 CSV 재계산값과 `metrics.json`·`REPORT.md` 핵심 수치 대조: **{'통과' if metric_passed else '실패'}**
- 상세 CSV: `outputs/cross_check_points.csv`, `outputs/metric_cross_check.csv`

## 원자료 3개 시점

검산일은 첫 완전관측 월, 코로나 충격기 2020년 3월, 마지막 완전관측 월이다.
각 변화율은 `(현재/전월-1)×100`, 금리 변화는 `현재-전월`로 독립 재계산했다.

{markdown_table(raw_check.set_index(['date', 'variable']), digits=10)}

## 보고서·JSON 핵심 수치

{markdown_table(metric_check.set_index('metric'), digits=12)}

## 수집 경고와 대체자료

{source_notes}

## 사람이 마지막으로 확인할 항목

- 공개 GitHub URL과 Streamlit URL은 계정 소유자가 배포한 뒤 시크릿 창에서 확인한다.
- 보험업 ETF 대용변수는 KRX 보험업 원지수와 완전히 같지 않으므로 결과표와 발표에서 ‘대용변수’라고 말한다.
- 상관관계를 원인이나 투자수익 보장으로 표현하지 않는다.
"""
    (PROJECT_ROOT / "VERIFICATION.md").write_text(verification, encoding="utf-8")

    if not raw_passed or not metric_passed:
        raise AssertionError("교차검산 실패: outputs의 상세 검산 CSV를 확인하세요.")


def validate_outputs(monthly: pd.DataFrame, figure_paths: list[str], config: Config) -> None:
    required_columns = {
        "hanwha_return_pct",
        "insurance_return_pct",
        "kospi_return_pct",
        "kr10y_change_pp",
        "usdkrw_change_pct",
        "us10y_change_pp",
    }
    missing = required_columns - set(monthly.columns)
    assert not missing, f"필수 분석열 누락: {sorted(missing)}"
    assert len(monthly) >= config.minimum_points, "100개 이상 관측치 기준 미충족"
    assert monthly.index.is_monotonic_increasing, "날짜 정렬 오류"
    assert monthly.index.is_unique, "월 중복 오류"
    assert len(figure_paths) >= 3, "시각화 3개 이상 기준 미충족"
    for relative_path in figure_paths:
        path = PROJECT_ROOT / relative_path
        assert path.exists() and path.stat().st_size > 10_000, f"그래프 파일 오류: {path}"
    assert (PROJECT_ROOT / "REPORT.md").exists(), "REPORT.md 생성 실패"
    assert (PROCESSED_DIR / "monthly_analysis.csv").exists(), "정제 CSV 생성 실패"
    assert (OUTPUT_DIR / "cross_check_points.csv").exists(), "3시점 원자료 검산표 생성 실패"
    assert (OUTPUT_DIR / "metric_cross_check.csv").exists(), "핵심 수치 검산표 생성 실패"
    if config.source == "live":
        assert (OUTPUT_DIR / "source_manifest.json").exists(), "공개 출처 명세 생성 실패"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="한화생명·보험업지수·금리·환율의 2015~2026 월별 관계 분석"
    )
    parser.add_argument("--source", choices=("live", "sample"), default="sample")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument(
        "--end",
        default=None,
        help="기본값은 직전 완료 월의 말일. 예: 2026-08-31",
    )
    parser.add_argument("--rolling-window", type=int, default=12)
    parser.add_argument("--forecast-horizon", type=int, default=3)
    parser.add_argument(
        "--github-url",
        default=DEFAULT_GITHUB_URL,
        help="REPORT.md에 보존할 공개 GitHub 저장소 URL",
    )
    parser.add_argument(
        "--dashboard-url",
        default=DEFAULT_DASHBOARD_URL,
        help="REPORT.md에 보존할 공개 Streamlit 대시보드 URL",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_directories()
    configure_plot_style()
    end = pd.Timestamp(args.end) if args.end else last_complete_month_end()
    config = Config(
        start=pd.Timestamp(args.start),
        end=end,
        source=args.source,
        rolling_window=args.rolling_window,
        forecast_horizon=args.forecast_horizon,
        github_url=args.github_url,
        dashboard_url=args.dashboard_url,
    )
    if config.start >= config.end:
        raise ValueError("시작일은 종료일보다 빨라야 합니다.")
    print(f"분석 모드: {config.source} | 기간: {config.start.date()} ~ {config.end.date()}")

    if config.source == "live":
        levels, auxiliary, messages = collect_live_data(config)
    else:
        levels, auxiliary, messages = collect_sample_data(config)

    print("월별 정제·변환 중...")
    monthly, _profile = process_monthly(levels, config)
    quarterly = process_quarterly(auxiliary, monthly)
    print("간단 예측 중...")
    forecast, forecast_metrics = run_baseline_forecast(monthly, config.forecast_horizon)
    print("그래프 생성 중...")
    figure_paths = make_figures(monthly, quarterly, forecast, config)
    print("REPORT.md 생성 중...")
    build_report(monthly, quarterly, forecast_metrics, messages, config, figure_paths)
    save_metrics(monthly, quarterly, forecast_metrics, config)
    write_verification_artifacts(levels, monthly, forecast_metrics, messages, config)
    validate_outputs(monthly, figure_paths, config)

    print("\n완료되었습니다.")
    print(f"- 보고서: {PROJECT_ROOT / 'REPORT.md'}")
    print(f"- 정제자료: {PROCESSED_DIR / 'monthly_analysis.csv'}")
    print(f"- 그래프: {FIGURE_DIR}")
    if config.source == "sample":
        print("주의: sample 결과는 구조 확인용입니다. 제출 전 --source live로 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\n[실행 실패] {exc}", file=sys.stderr)
        print("README.md의 '오류가 날 때' 절을 확인하세요.", file=sys.stderr)
        raise
