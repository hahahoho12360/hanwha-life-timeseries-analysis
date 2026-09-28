"""Streamlit 웹 대시보드.

로컬 실행:
    streamlit run dashboard.py

먼저 analysis.py를 실행해 data/processed/monthly_analysis.csv를 만들어야 한다.
배포 시에는 정제 CSV와 outputs/forecast.csv를 GitHub에 함께 커밋한다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parent
MONTHLY_PATH = ROOT / "data" / "processed" / "monthly_analysis.csv"
FORECAST_PATH = ROOT / "outputs" / "forecast.csv"

LABELS = {
    "hanwha_return_pct": "한화생명 월간 수익률(%)",
    "insurance_return_pct": "보험업 시장 대용변수 월간 수익률(%)",
    "kospi_return_pct": "KOSPI 월간 수익률(%)",
    "kr10y_change_pp": "한국 10년물 금리 변화(%p)",
    "usdkrw_change_pct": "원/달러 환율 변화율(%)",
    "us10y_change_pp": "미국 10년물 금리 변화(%p)",
}


@st.cache_data
def load_monthly() -> pd.DataFrame:
    if not MONTHLY_PATH.exists():
        return pd.DataFrame()
    frame = pd.read_csv(MONTHLY_PATH, parse_dates=["date"]).set_index("date").sort_index()
    return frame


@st.cache_data
def load_forecast() -> pd.DataFrame:
    if not FORECAST_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(FORECAST_PATH, parse_dates=["date"]).set_index("date").sort_index()


def max_drawdown(price: pd.Series) -> float:
    price = price.dropna()
    if price.empty:
        return float("nan")
    drawdown = price / price.cummax() - 1
    return float(drawdown.min() * 100)


def apply_condition(frame: pd.DataFrame, condition: str) -> pd.DataFrame:
    if condition == "전체 월":
        return frame
    if condition == "한국 10년물 상승·보합":
        return frame[frame["kr10y_change_pp"] >= 0]
    if condition == "한국 10년물 하락":
        return frame[frame["kr10y_change_pp"] < 0]
    if condition == "원화 약세(원/달러 상승)":
        return frame[frame["usdkrw_change_pct"] >= 0]
    if condition == "원화 강세(원/달러 하락)":
        return frame[frame["usdkrw_change_pct"] < 0]
    return frame


def regression_scatter(frame: pd.DataFrame, x_column: str) -> go.Figure:
    plot = frame[[x_column, "hanwha_return_pct"]].dropna()
    fig = px.scatter(
        plot,
        x=x_column,
        y="hanwha_return_pct",
        labels={x_column: LABELS[x_column], "hanwha_return_pct": LABELS["hanwha_return_pct"]},
        hover_data={x_column: ":.2f", "hanwha_return_pct": ":.2f"},
        title=f"{LABELS[x_column]}와 한화생명 수익률",
    )
    if len(plot) >= 3 and plot[x_column].nunique() > 1:
        slope, intercept = np.polyfit(plot[x_column], plot["hanwha_return_pct"], 1)
        xs = np.linspace(plot[x_column].min(), plot[x_column].max(), 100)
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=slope * xs + intercept,
                mode="lines",
                name="단순 추세선(인과 아님)",
            )
        )
    return fig


def main() -> None:
    st.set_page_config(page_title="한화생명 시계열 분석", page_icon="📈", layout="wide")
    st.title("금리·환율·보험업 환경과 한화생명 주가")
    st.caption("2015~2026 월별 관계 탐색 | 상관은 인과가 아니며 투자 권유가 아닙니다.")

    data = load_monthly()
    if data.empty:
        st.error(
            "정제 데이터가 없습니다. 터미널에서 먼저 "
            "`python analysis.py --source live --start 2015-01-01`을 실행하세요."
        )
        st.stop()

    min_date = data.index.min().date()
    max_date = data.index.max().date()
    with st.sidebar:
        st.header("탐색 조건")
        selected_dates = st.date_input(
            "기간",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        rolling_window = st.slider("이동상관 기간(개월)", 6, 36, 12, 1)
        x_variable = st.selectbox(
            "한화생명과 비교할 변수",
            options=[c for c in LABELS if c != "hanwha_return_pct"],
            format_func=lambda x: LABELS[x],
        )
        condition = st.selectbox(
            "시장 조건",
            [
                "전체 월",
                "한국 10년물 상승·보합",
                "한국 10년물 하락",
                "원화 약세(원/달러 상승)",
                "원화 강세(원/달러 하락)",
            ],
        )

    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_date, end_date = pd.Timestamp(selected_dates[0]), pd.Timestamp(selected_dates[1])
    else:
        start_date, end_date = pd.Timestamp(min_date), pd.Timestamp(max_date)

    filtered = data.loc[(data.index >= start_date) & (data.index <= end_date)].copy()
    conditioned = apply_condition(filtered, condition)
    if len(conditioned) < 6:
        st.warning("선택한 조건의 관측치가 6개보다 적습니다. 기간이나 조건을 넓혀 주세요.")

    metric_columns = st.columns(4)
    metric_columns[0].metric("관측 월", f"{len(conditioned)}개")
    metric_columns[1].metric(
        "평균 월수익률",
        f"{conditioned['hanwha_return_pct'].mean():.2f}%" if not conditioned.empty else "-",
    )
    metric_columns[2].metric(
        "월 변동성",
        f"{conditioned['hanwha_return_pct'].std(ddof=1):.2f}%p" if len(conditioned) > 1 else "-",
    )
    metric_columns[3].metric(
        "최대 낙폭",
        f"{max_drawdown(filtered['hanwha_close']):.2f}%" if not filtered.empty else "-",
    )

    st.subheader("1. 같은 출발점(100)에서 본 가격 흐름")
    price_columns = ["hanwha_close", "insurance_close", "kospi_close"]
    prices = filtered[price_columns].dropna()
    if not prices.empty:
        normalized = prices.div(prices.iloc[0]).mul(100).rename(
            columns={
                "hanwha_close": "한화생명",
                "insurance_close": "보험업 시장 대용변수",
                "kospi_close": "KOSPI",
            }
        )
        fig = px.line(normalized, labels={"value": "기준지수", "date": "월", "variable": "계열"})
        fig.add_hline(y=100, line_dash="dot")
        st.plotly_chart(fig, width="stretch")
    st.info("단위가 다른 가격을 첫 달=100으로 바꾼 그래프입니다. 수익률 분석 자체는 월간 변화율로 수행합니다.")

    left, right = st.columns(2)
    with left:
        st.subheader("2. 변수별 산점도")
        st.plotly_chart(regression_scatter(conditioned, x_variable), width="stretch")
        if len(conditioned) >= 3:
            corr = conditioned[[x_variable, "hanwha_return_pct"]].corr().iloc[0, 1]
            st.write(f"선택 기간·조건의 단순 상관계수: **{corr:.3f}**")
    with right:
        st.subheader("3. 이동상관")
        rolling_corr = filtered["hanwha_return_pct"].rolling(rolling_window).corr(filtered[x_variable])
        fig = px.line(
            rolling_corr.rename("이동상관").to_frame(),
            y="이동상관",
            labels={"date": "월", "value": "상관계수"},
        )
        fig.add_hline(y=0, line_color="black")
        fig.update_yaxes(range=[-1, 1])
        st.plotly_chart(fig, width="stretch")
        st.write("선이 크게 움직이면 전 기간 평균 상관 하나가 모든 시기를 대표하지 못한다는 뜻입니다.")

    st.subheader("4. 상관관계 전체 지도")
    variables = list(LABELS)
    correlation = conditioned[variables].corr().rename(index=LABELS, columns=LABELS)
    fig = px.imshow(
        correlation,
        text_auto=".2f",
        zmin=-1,
        zmax=1,
        color_continuous_scale="RdBu_r",
        aspect="auto",
    )
    st.plotly_chart(fig, width="stretch")

    st.subheader("5. 보너스 B: 짧은 구간 예측")
    forecast = load_forecast()
    if forecast.empty:
        st.warning("예측 파일이 없습니다. analysis.py를 다시 실행하세요.")
    else:
        history = filtered["hanwha_return_pct"].tail(36)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=history.index, y=history, name="실제 월수익률"))
        fig.add_trace(
            go.Scatter(
                x=forecast.index,
                y=forecast["predicted_return_pct"],
                mode="lines+markers",
                line={"dash": "dash"},
                name="AR(3) Ridge 예측",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=list(forecast.index) + list(forecast.index[::-1]),
                y=list(forecast["upper_95_pct"]) + list(forecast["lower_95_pct"][::-1]),
                fill="toself",
                fillcolor="rgba(31,119,180,0.18)",
                line={"color": "rgba(255,255,255,0)"},
                hoverinfo="skip",
                name="근사 95% 구간",
            )
        )
        fig.add_hline(y=0, line_color="black")
        fig.update_layout(xaxis_title="월", yaxis_title="월수익률(%)")
        st.plotly_chart(fig, width="stretch")
        st.warning(
            "이 예측은 과거 3개월 수익률만 이용한 교육용 베이스라인입니다. "
            "공시·정책·구조변화를 모르므로 정확도보다 가정과 한계를 설명하는 데 목적이 있습니다."
        )

    st.subheader("6. 선택 자료 내려받기")
    st.dataframe(conditioned.reset_index(), width="stretch", height=320)
    st.download_button(
        "선택 자료 CSV 다운로드",
        conditioned.to_csv(index_label="date").encode("utf-8-sig"),
        file_name="hanwha_filtered_monthly.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
