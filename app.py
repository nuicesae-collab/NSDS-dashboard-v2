from pathlib import Path
from datetime import datetime
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

from generate_demo_data import (
    DISEASES,
    AGE_GROUPS,
    MONTHS,
    SHORT_MONTHS,
    REGIONS,
    build,
)

# ============================================================
# NSDS Dashboard V3
# Dashboard layout simplified; existing CSV files and
# generate_demo_data.py are retained.
# ============================================================

st.set_page_config(
    page_title="NSDS Dashboard V3",
    page_icon="🩺",
    layout="wide",
)

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DATA_FILES = {
    "history": DATA_DIR / "historical_cases_2564_2568.csv",
    "forecast": DATA_DIR / "forecast_2569.csv",
    "simulation": DATA_DIR / "simulation_2569.csv",
    "thresholds": DATA_DIR / "disease_thresholds.csv",
    "hospitals": DATA_DIR / "hospital_registry.csv",
}

# Generate demo data only if a required file is missing.
if not all(path.exists() for path in DATA_FILES.values()):
    build(DATA_DIR)


def read_csv(path):
    return pd.read_csv(path, encoding="utf-8-sig")


history = read_csv(DATA_FILES["history"])
forecast = read_csv(DATA_FILES["forecast"])
simulation = read_csv(DATA_FILES["simulation"])
thresholds = read_csv(DATA_FILES["thresholds"])
hospitals = read_csv(DATA_FILES["hospitals"])

# Normalize data types without changing the source CSV files.
for frame in (history, forecast, simulation):
    for column in ("year_be", "month", "cases"):
        if column not in frame.columns:
            frame[column] = 0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(int)
    frame["cases"] = frame["cases"].clip(lower=0)
    frame["month"] = frame["month"].clip(lower=1, upper=12)
    for column in ("health_region", "disease", "age_group", "sex"):
        if column not in frame.columns:
            frame[column] = "ไม่ระบุ"

for column in ("watch_ratio", "alert_ratio", "zero_watch_cases", "zero_alert_cases"):
    if column in thresholds.columns:
        thresholds[column] = pd.to_numeric(thresholds[column], errors="coerce")

# Keep the existing hospital registry columns and add three role-specific
# LINE destination columns in memory. They are included when the user
# downloads the updated registry from the app.
HOSPITAL_COLUMNS = [
    "hospital_id",
    "hospital_name",
    "health_region",
    "line_user_id",  # legacy field; retained for compatibility
    "line_epidemiology_id",
    "line_ic_id",
    "line_executive_id",
    "is_active",
    "consent_status",
]
for column in HOSPITAL_COLUMNS:
    if column not in hospitals.columns:
        hospitals[column] = "" if column != "is_active" else True

if "is_active" in hospitals.columns:
    hospitals["is_active"] = hospitals["is_active"].fillna(False)

# Stable ordering for age charts.
for frame in (history, forecast, simulation):
    frame["age_group"] = pd.Categorical(
        frame["age_group"].astype(str), categories=AGE_GROUPS, ordered=True
    )

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.15rem; padding-bottom: 2rem;}
      .stMetric {
        background: #f5f7fb;
        padding: 12px;
        border-radius: 12px;
        border: 1px solid #e8edf5;
      }
      div[data-testid="stAlert"] {border-radius: 10px;}
      div[data-testid="stSelectbox"] label {font-weight: 600;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------- Shared helpers -------------------------

RECIPIENT_ROLES = {
    "ระบาดวิทยา": "line_epidemiology_id",
    "ทีม IC": "line_ic_id",
    "ผู้บริหาร": "line_executive_id",
}


def is_active_value(value):
    return str(value).strip().lower() in ("true", "1", "yes", "y", "active", "ใช่")


def active_hospitals_for_region(region):
    active_mask = hospitals["is_active"].apply(is_active_value)
    return hospitals.loc[
        (hospitals["health_region"].astype(str) == region) & active_mask
    ].copy()


def approved_value(value):
    return str(value).strip().lower() == "approved"


def threshold_for(disease):
    rows = thresholds.loc[thresholds["disease"].astype(str) == disease]
    if rows.empty:
        return {
            "watch_ratio": 1.2,
            "alert_ratio": 1.5,
            "zero_watch_cases": 5,
            "zero_alert_cases": 10,
            "rationale": "ไม่มีเกณฑ์เฉพาะในไฟล์ จึงใช้ค่าเริ่มต้นเพื่อสาธิต",
        }
    return rows.iloc[0].to_dict()


def baseline_for(region, disease, month):
    """Median for the same month across all five historical years."""
    values = (
        history.loc[
            (history["health_region"] == region)
            & (history["disease"] == disease)
            & (history["month"] == month)
        ]
        .groupby("year_be")["cases"]
        .sum()
        .reindex(range(2564, 2569))
    )
    if values.notna().sum() < 5:
        return None
    return float(values.median())


def cases_for(frame, region, disease, month):
    rows = frame.loc[
        (frame["health_region"] == region)
        & (frame["disease"] == disease)
        & (frame["month"] == month)
    ]
    return int(rows["cases"].sum())


def evaluate_disease(region, disease, month, force_status=None):
    current_cases = cases_for(simulation, region, disease, month)
    baseline = baseline_for(region, disease, month)
    rule = threshold_for(disease)
    ratio = current_cases / baseline if baseline is not None and baseline > 0 else None

    if baseline is None:
        status = "ข้อมูลฐานไม่ครบ"
    elif baseline <= 0:
        if current_cases >= int(rule["zero_alert_cases"]):
            status = "ALERT"
        elif current_cases >= int(rule["zero_watch_cases"]):
            status = "WATCH"
        else:
            status = "NORMAL"
    elif ratio >= float(rule["alert_ratio"]):
        status = "ALERT"
    elif ratio >= float(rule["watch_ratio"]):
        status = "WATCH"
    else:
        status = "NORMAL"

    # Forced statuses are available only in the clearly labelled test mode.
    if force_status in ("NORMAL", "WATCH", "ALERT"):
        status = force_status

    return {
        "disease": disease,
        "month": month,
        "cases": current_cases,
        "baseline": baseline,
        "ratio": ratio,
        "status": status,
    }


def demographic_data(frame, region, disease):
    rows = frame.loc[
        (frame["health_region"] == region) & (frame["disease"] == disease)
    ].copy()
    grouped = (
        rows.groupby(["age_group", "sex"], observed=False)["cases"]
        .sum()
        .reset_index()
    )
    age_totals = (
        grouped.groupby("age_group", observed=False)["cases"]
        .sum()
        .reindex(AGE_GROUPS, fill_value=0)
    )
    sex_totals = grouped.groupby("sex")["cases"].sum().to_dict()
    total = int(grouped["cases"].sum())
    male = int(sex_totals.get("ชาย", 0))
    female = int(sex_totals.get("หญิง", 0))
    return grouped, age_totals, total, male, female


def percent(part, total):
    return f"{part / total * 100:.1f}%" if total else "0.0%"


def status_icon(status):
    return {"ALERT": "🚨", "WATCH": "⚠️", "NORMAL": "🟢"}.get(status, "ℹ️")


def notification_for_disease(result, region):
    detail, age_totals, total, male, female = demographic_data(
        simulation, region, result["disease"]
    )
    month_rows = simulation.loc[
        (simulation["health_region"] == region)
        & (simulation["disease"] == result["disease"])
        & (simulation["month"] == result["month"])
    ]
    month_grouped = (
        month_rows.groupby(["age_group", "sex"], observed=False)["cases"]
        .sum()
        .reset_index()
    )
    month_total = int(month_grouped["cases"].sum())
    month_male = int(month_grouped.loc[month_grouped["sex"] == "ชาย", "cases"].sum())
    month_female = int(month_grouped.loc[month_grouped["sex"] == "หญิง", "cases"].sum())
    month_age = (
        month_grouped.groupby("age_group", observed=False)["cases"]
        .sum()
        .reindex(AGE_GROUPS, fill_value=0)
    )
    baseline_text = (
        f"{int(round(result['baseline'])):,} ราย"
        if result["baseline"] is not None
        else "ไม่มีข้อมูลฐานเพียงพอ"
    )
    ratio_text = (
        f"{result['ratio']:.2f} เท่า"
        if result["ratio"] is not None
        else "คำนวณอัตราส่วนไม่ได้"
    )

    lines = [
        f"{status_icon(result['status'])} {result['status']} — {result['disease']}",
        f"ผู้ป่วยจำลองเดือน{MONTHS[result['month'] - 1]}: {result['cases']:,} ราย",
        f"ค่าฐานเดือนเดียวกันย้อนหลัง 5 ปี: {baseline_text} | เทียบฐาน: {ratio_text}",
        (
            f"เพศ: ชาย {month_male:,} ราย ({percent(month_male, month_total)})"
            f" · หญิง {month_female:,} ราย ({percent(month_female, month_total)})"
        ),
    ]

    if result["status"] == "ALERT":
        lines.append("จำแนกตามช่วงอายุ:")
        for age in AGE_GROUPS:
            count = int(month_age.get(age, 0))
            lines.append(f"• {age}: {count:,} ราย ({percent(count, month_total)})")
    elif result["status"] == "WATCH":
        if month_total:
            top_age = str(month_age.idxmax())
            top_count = int(month_age.get(top_age, 0))
            lines.append(
                f"ช่วงอายุที่พบมากที่สุด: {top_age} "
                f"{top_count:,} ราย ({percent(top_count, month_total)})"
            )
    return "\n".join(lines)


def build_notification(region, hospital_name, recipient_role, month, results, test_mode=False):
    flagged = [item for item in results if item["status"] in ("WATCH", "ALERT")]
    alert_count = sum(item["status"] == "ALERT" for item in flagged)
    watch_count = sum(item["status"] == "WATCH" for item in flagged)
    lines = [
        "🩺 NSDS | แจ้งเตือนเฝ้าระวังโรค",
        f"กลุ่มผู้รับ: {recipient_role}",
        f"เขตสุขภาพ: {region}",
        f"โรงพยาบาล: {hospital_name}",
        f"เดือนที่ประเมิน: {MONTHS[month - 1]} 2569",
        f"สรุปสถานการณ์: ALERT {alert_count} โรค · WATCH {watch_count} โรค",
        "━━━━━━━━━━━━━━━━━━",
    ]
    if flagged:
        lines.extend(notification_for_disease(item, region) for item in flagged)
    else:
        lines.append("ขณะนี้ไม่มีโรคที่เข้าเกณฑ์ WATCH หรือ ALERT ในเดือนที่เลือก")
    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "หมายเหตุ: ข้อมูลเป็นข้อมูลสังเคราะห์เพื่อสาธิต ไม่ใช่ข้อมูลผู้ป่วยจริง",
            "เกณฑ์ WATCH / ALERT เป็นค่าเริ่มต้น ต้องผ่านการรับรองก่อนใช้งานจริง",
        ]
    )
    if test_mode:
        lines.append("โหมดทดสอบ: มีการกำหนดสถานะเพื่อทดลองรูปแบบข้อความ")
    return "\n\n".join(lines)[:4900]


def get_secret(key):
    try:
        value = st.secrets.get(key, "")
        if value:
            return value
    except Exception:
        pass
    return os.getenv(key, "")


def send_line_message(token, target_id, message):
    response = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "to": str(target_id).strip(),
            "messages": [{"type": "text", "text": message}],
        },
        timeout=20,
    )
    return response.status_code, response.text[:500]


def monthly_totals(frame, region, disease=None):
    rows = frame.loc[frame["health_region"] == region]
    if disease:
        rows = rows.loc[rows["disease"] == disease]
    return (
        rows.groupby("month")["cases"]
        .sum()
        .reindex(range(1, 13), fill_value=0)
        .astype(int)
    )


def all_disease_monthly(frame, region):
    rows = frame.loc[frame["health_region"] == region]
    result = (
        rows.groupby(["month", "disease"], as_index=False)["cases"]
        .sum()
    )
    result["เดือน"] = result["month"].map(lambda m: SHORT_MONTHS[int(m) - 1])
    return result


def test_results(region, month, test_mode, selected_disease):
    forced = None
    if test_mode == "ทดสอบ NORMAL":
        forced = "NORMAL"
    elif test_mode == "ทดสอบ WATCH":
        forced = "WATCH"
    elif test_mode == "ทดสอบ ALERT":
        forced = "ALERT"
    return [
        evaluate_disease(
            region,
            disease_name,
            month,
            force_status=forced if disease_name == selected_disease else None,
        )
        for disease_name in DISEASES
    ]


def recipient_targets(hospital_rows):
    targets = []
    for _, hospital in hospital_rows.iterrows():
        if not approved_value(hospital.get("consent_status", "")):
            continue
        for role, column in RECIPIENT_ROLES.items():
            target_id = str(hospital.get(column, "") or "").strip()
            if target_id and target_id.lower() not in ("nan", "none"):
                targets.append(
                    {
                        "hospital_name": str(hospital.get("hospital_name", "โรงพยาบาล")),
                        "role": role,
                        "target_id": target_id,
                    }
                )
    return targets


def monthly_series_for_disease(frame, region, disease):
    return monthly_totals(frame, region, disease)


def make_trend_figure(region, disease, selected_year):
    fig = go.Figure()
    series_specs = []
    if selected_year == 2569:
        series_specs = [
            (history.loc[history["year_be"] == 2567], "ข้อมูลจริง 2567", "#1769D2", "solid"),
            (history.loc[history["year_be"] == 2568], "ข้อมูลจริง 2568", "#79B9F2", "dot"),
            (forecast, "คาดการณ์ 2569", "#E53935", "dash"),
            (simulation, "ข้อมูลจำลอง 2569", "#FF9B9B", "longdash"),
        ]
    else:
        series_specs = [
            (history.loc[history["year_be"] == selected_year], f"ข้อมูลจริง {selected_year}", "#1769D2", "solid"),
        ]

    for frame, label, color, dash in series_specs:
        values = monthly_series_for_disease(frame, region, disease)
        fig.add_trace(
            go.Scatter(
                x=SHORT_MONTHS,
                y=values.tolist(),
                mode="lines+markers",
                name=label,
                line={"color": color, "width": 2.5, "dash": dash},
                marker={"size": 6},
                hovertemplate=f"{label}<br>%{{x}}: %{{y:,}} ราย<extra></extra>",
            )
        )
    fig.update_layout(
        height=430,
        margin={"l": 10, "r": 10, "t": 25, "b": 10},
        legend={"title": "ประเภทข้อมูล", "orientation": "v", "y": 1, "x": 1.01},
        xaxis_title="เดือน",
        yaxis_title="จำนวนผู้ป่วย (ราย)",
        hovermode="x unified",
    )
    fig.update_xaxes(categoryorder="array", categoryarray=SHORT_MONTHS)
    fig.update_yaxes(rangemode="tozero", separatethousands=True)
    return fig


# ------------------------- App header, navigation, and filters -------------------------

st.title("🩺 NSDS Dashboard")
st.caption("ระบบวิเคราะห์แนวโน้มและเฝ้าระวังโรคระดับเขตสุขภาพ")

with st.sidebar:
    st.header("เมนูระบบ")
    page = st.radio(
        "ไปยังหน้า",
        ["ภาพรวม Dashboard", "ระบบ ALERT / LINE"],
        label_visibility="collapsed",
    )

filter_region, filter_year, filter_disease = st.columns([1.15, 0.9, 1.45])
with filter_region:
    region = st.selectbox("เขตสุขภาพ", REGIONS, index=3, key="global_region")
with filter_year:
    selected_year = st.selectbox(
        "ปี พ.ศ.", [2564, 2565, 2566, 2567, 2568, 2569], index=5, key="global_year"
    )
with filter_disease:
    disease = st.selectbox("โรค", DISEASES, index=0, key="global_disease")

st.session_state.setdefault("delivery_log", [])


# ------------------------- Page: Dashboard -------------------------

if page == "ภาพรวม Dashboard":
    st.header(f"ภาพรวมสถานการณ์ · {region}")
    st.warning(
        "ข้อมูลในต้นแบบนี้เป็นข้อมูลสังเคราะห์เพื่อสาธิตและทดสอบระบบ "
        "ไม่ใช่ข้อมูลผู้ป่วยจริงจากกรมควบคุมโรค"
    )

    if selected_year == 2569:
        dashboard_frame = simulation.copy()
        source_caption = "ปี 2569: ยอดรวมและข้อมูลประชากรใช้ชุด Simulation เพื่อไม่ให้นับ Forecast ซ้ำ"
    else:
        dashboard_frame = history.loc[history["year_be"] == selected_year].copy()
        source_caption = f"แสดงข้อมูลย้อนหลังปี พ.ศ. {selected_year}"

    region_frame = dashboard_frame.loc[dashboard_frame["health_region"] == region]
    annual_total = int(region_frame["cases"].sum())
    disease_totals = (
        region_frame.groupby("disease")["cases"]
        .sum()
        .reindex(DISEASES, fill_value=0)
    )

    # ALERT / WATCH cards always summarize the current surveillance month in 2569.
    status_month = max(1, min(datetime.now().month, 12))
    live_results = [evaluate_disease(region, item, status_month) for item in DISEASES]
    alert_count = sum(item["status"] == "ALERT" for item in live_results)
    watch_count = sum(item["status"] == "WATCH" for item in live_results)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(f"ผู้ป่วยรวม · {selected_year}", f"{annual_total:,} ราย")
    col2.metric("ALERT", f"{alert_count} โรค", f"เดือน{MONTHS[status_month - 1]} 2569")
    col3.metric("WATCH", f"{watch_count} โรค", f"เดือน{MONTHS[status_month - 1]} 2569")
    col4.metric("โรคที่ติดตาม", f"{len(DISEASES)} โรค")
    st.caption(source_caption)

    st.divider()
    st.subheader(f"แนวโน้มรายเดือน: {disease}")
    if selected_year == 2569:
        st.caption("เปรียบเทียบข้อมูลจริง 2567–2568 กับ Forecast และ Simulation 2569")
    st.plotly_chart(
        make_trend_figure(region, disease, selected_year),
        use_container_width=True,
        config={"displaylogo": False},
    )

    st.divider()
    st.subheader("เปรียบเทียบจำนวนผู้ป่วยรายเดือน · ทั้ง 6 โรค")
    if selected_year == 2569:
        compare_frame = simulation.copy()
        st.caption("กราฟนี้ใช้ข้อมูล Simulation 2569 เป็นชุดข้อมูลเปรียบเทียบของทั้ง 6 โรค")
    else:
        compare_frame = history.loc[history["year_be"] == selected_year].copy()
    monthly = all_disease_monthly(compare_frame, region)
    if not monthly.empty:
        monthly_fig = px.line(
            monthly,
            x="เดือน",
            y="cases",
            color="disease",
            markers=True,
            category_orders={"เดือน": SHORT_MONTHS, "disease": DISEASES},
            labels={"cases": "จำนวนผู้ป่วย (ราย)", "disease": "โรค", "เดือน": "เดือน"},
        )
        monthly_fig.update_layout(
            height=430,
            margin={"l": 10, "r": 10, "t": 20, "b": 10},
            legend_title_text="โรค",
            hovermode="x unified",
        )
        monthly_fig.update_yaxes(rangemode="tozero", separatethousands=True)
        st.plotly_chart(monthly_fig, use_container_width=True, config={"displaylogo": False})
    else:
        st.info("ไม่มีข้อมูลรายเดือนสำหรับตัวกรองนี้")

    st.divider()
    st.subheader(f"ข้อมูลประชากร: {disease}")
    st.caption(
        "ปี 2569 ใช้ข้อมูล Simulation · ปี 2564–2568 ใช้ข้อมูลย้อนหลังของปีที่เลือก"
    )
    grouped, age_totals, demo_total, male_total, female_total = demographic_data(
        region_frame, region, disease
    )
    d1, d2, d3 = st.columns(3)
    d1.metric("ผู้ป่วยรวม", f"{demo_total:,} ราย")
    d2.metric("ชาย", f"{male_total:,} ราย", percent(male_total, demo_total))
    d3.metric("หญิง", f"{female_total:,} ราย", percent(female_total, demo_total))

    age_chart = (
        age_totals.rename("จำนวนผู้ป่วย")
        .rename_axis("ช่วงอายุ")
        .reset_index()
    )
    sex_chart = pd.DataFrame(
        {"เพศ": ["ชาย", "หญิง"], "จำนวนผู้ป่วย": [male_total, female_total]}
    )
    age_col, sex_col = st.columns([1.35, 1])
    with age_col:
        age_fig = px.bar(
            age_chart,
            x="จำนวนผู้ป่วย",
            y="ช่วงอายุ",
            orientation="h",
            text_auto=True,
            category_orders={"ช่วงอายุ": AGE_GROUPS},
            labels={"จำนวนผู้ป่วย": "จำนวนผู้ป่วย (ราย)"},
        )
        age_fig.update_layout(height=330, margin={"l": 5, "r": 10, "t": 20, "b": 5})
        age_fig.update_xaxes(rangemode="tozero", separatethousands=True)
        st.plotly_chart(age_fig, use_container_width=True, config={"displaylogo": False})
    with sex_col:
        if demo_total:
            sex_fig = px.pie(
                sex_chart,
                names="เพศ",
                values="จำนวนผู้ป่วย",
                hole=0.48,
            )
            sex_fig.update_layout(height=330, margin={"l": 5, "r": 5, "t": 20, "b": 5})
            st.plotly_chart(sex_fig, use_container_width=True, config={"displaylogo": False})
        else:
            st.info("ไม่มีข้อมูลเพศสำหรับตัวกรองนี้")

    st.subheader("ตารางสรุปจำนวนผู้ป่วยทั้ง 6 โรค")
    summary = disease_totals.rename("จำนวนผู้ป่วย (ราย)").rename_axis("โรค").reset_index()
    st.dataframe(summary, hide_index=True, use_container_width=True)

    st.caption(
        "ช่วงอายุเป็นกลุ่มเพื่อการแสดงผลในต้นแบบ ไม่ใช่การยืนยันว่าเป็นมาตรฐานช่วงอายุ "
        "เดียวกันของกรมควบคุมโรคสำหรับทุกโรค"
    )


# ------------------------- Page: ALERT / LINE -------------------------

else:
    st.header(f"ระบบ ALERT และแจ้งเตือน LINE · {region}")
    st.warning(
        "ข้อมูลและเกณฑ์ในต้นแบบเป็นข้อมูลสังเคราะห์เพื่อทดสอบระบบ "
        "ต้องตรวจสอบและรับรองก่อนใช้แจ้งเตือนในงานจริง"
    )

    left, right = st.columns(2)
    with left:
        month = st.selectbox(
            "เดือนที่ต้องการประเมิน",
            range(1, 13),
            index=max(0, min(datetime.now().month - 1, 11)),
            format_func=lambda value: MONTHS[value - 1],
            key="alert_month",
        )
    with right:
        test_mode = st.selectbox(
            "โหมดประเมิน",
            ["คำนวณจาก Simulation 2569", "ทดสอบ NORMAL", "ทดสอบ WATCH", "ทดสอบ ALERT"],
            key="alert_test_mode",
        )

    results = test_results(region, month, test_mode, disease)
    flagged = [item for item in results if item["status"] in ("WATCH", "ALERT")]
    alert_total = sum(item["status"] == "ALERT" for item in flagged)
    watch_total = sum(item["status"] == "WATCH" for item in flagged)
    test_active = test_mode != "คำนวณจาก Simulation 2569"

    active_hospitals = active_hospitals_for_region(region)
    approved_hospitals = active_hospitals.loc[
        active_hospitals["consent_status"].apply(approved_value)
    ]
    targets = recipient_targets(approved_hospitals)

    a, b, c, d = st.columns(4)
    a.metric("โรคระดับ ALERT", alert_total)
    b.metric("โรคระดับ WATCH", watch_total)
    c.metric("โรงพยาบาลเปิดใช้งาน", len(active_hospitals))
    d.metric("ปลายทาง LINE ที่พร้อมส่ง", len(targets))

    status_rows = [
        {
            "โรค": item["disease"],
            "ผู้ป่วยจำลอง": item["cases"],
            "ค่าฐาน 5 ปี": round(item["baseline"]) if item["baseline"] is not None else "ไม่มีข้อมูล",
            "เทียบฐาน (เท่า)": round(item["ratio"], 2) if item["ratio"] is not None else "—",
            "สถานะ": item["status"],
        }
        for item in results
    ]
    st.subheader(f"ผลประเมินทั้ง 6 โรค · {MONTHS[month - 1]} 2569")
    st.dataframe(pd.DataFrame(status_rows), hide_index=True, use_container_width=True)

    preview_hospital = (
        str(active_hospitals.iloc[0]["hospital_name"])
        if not active_hospitals.empty
        else "โรงพยาบาลตัวอย่าง"
    )
    preview_role = "ระบาดวิทยา"
    preview_message = build_notification(
        region,
        preview_hospital,
        preview_role,
        month,
        results,
        test_mode=test_active,
    )
    with st.expander("ตัวอย่างข้อความ LINE", expanded=True):
        st.code(preview_message, language="text")
    st.caption(
        "WATCH: แสดงจำนวนผู้ป่วย เพศ และช่วงอายุที่พบมากที่สุด · "
        "ALERT: แสดงจำนวนผู้ป่วย เพศ และรายละเอียดครบทุกช่วงอายุ"
    )

    st.divider()
    st.subheader("ผู้รับแจ้งเตือนในโรงพยาบาล")
    st.write("ระบบรองรับผู้รับ 3 กลุ่มเท่านั้น: เจ้าหน้าที่ระบาดวิทยา, ทีม IC และผู้บริหาร")
    if active_hospitals.empty:
        st.info("ยังไม่มีโรงพยาบาลที่เปิดใช้งานในเขตสุขภาพนี้")
    else:
        recipient_summary = []
        for _, hospital in active_hospitals.iterrows():
            recipient_summary.append(
                {
                    "โรงพยาบาล": hospital["hospital_name"],
                    "ระบาดวิทยา": "ตั้งค่าแล้ว" if str(hospital["line_epidemiology_id"]).strip() not in ("", "nan") else "ยังไม่ตั้งค่า",
                    "ทีม IC": "ตั้งค่าแล้ว" if str(hospital["line_ic_id"]).strip() not in ("", "nan") else "ยังไม่ตั้งค่า",
                    "ผู้บริหาร": "ตั้งค่าแล้ว" if str(hospital["line_executive_id"]).strip() not in ("", "nan") else "ยังไม่ตั้งค่า",
                    "ความยินยอม": hospital["consent_status"],
                }
            )
        st.dataframe(pd.DataFrame(recipient_summary), hide_index=True, use_container_width=True)

    token = get_secret("LINE_CHANNEL_ACCESS_TOKEN")
    st.info(
        f"มีปลายทาง LINE ที่กรอก ID และได้รับสถานะ approved แล้ว {len(targets)} ปลายทาง "
        f"จากโรงพยาบาลใน {region}"
    )
    consent_confirmed = st.checkbox(
        "ยืนยันว่าปลายทาง LINE ที่มีสถานะ approved ทุกกลุ่มยินยอมรับการแจ้งเตือน",
        key="line_consent_confirm",
    )

    sim_col, send_col = st.columns(2)
    with sim_col:
        if st.button(
            "จำลองการแจ้งเตือนทั้ง 3 กลุ่ม",
            type="secondary",
            use_container_width=True,
            disabled=active_hospitals.empty,
        ):
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for _, hospital in active_hospitals.iterrows():
                for role in RECIPIENT_ROLES:
                    st.session_state.delivery_log.append(
                        {
                            "เวลา": timestamp,
                            "เขตสุขภาพ": region,
                            "โรงพยาบาล": hospital["hospital_name"],
                            "กลุ่มผู้รับ": role,
                            "เดือน": MONTHS[month - 1],
                            "ALERT": alert_total,
                            "WATCH": watch_total,
                            "ผลการดำเนินการ": "จำลองสำเร็จ (ไม่ได้ส่ง LINE จริง)",
                        }
                    )
            st.success(
                f"จำลองการแจ้งเตือน {len(active_hospitals)} โรงพยาบาล "
                f"รวม {len(active_hospitals) * len(RECIPIENT_ROLES)} กลุ่มผู้รับแล้ว"
            )

    real_send_disabled = (
        not token or not targets or not consent_confirmed or test_active or not flagged
    )
    with send_col:
        if st.button(
            "ส่ง LINE จริงให้ผู้รับที่อนุมัติ",
            type="primary",
            use_container_width=True,
            disabled=real_send_disabled,
        ):
            success_count = 0
            for target in targets:
                message = build_notification(
                    region,
                    target["hospital_name"],
                    target["role"],
                    month,
                    results,
                    test_mode=False,
                )
                try:
                    status_code, response_text = send_line_message(
                        token, target["target_id"], message
                    )
                    success = status_code == 200
                    success_count += int(success)
                    outcome = (
                        f"ส่งสำเร็จ (HTTP {status_code})"
                        if success
                        else f"ส่งไม่สำเร็จ (HTTP {status_code}) {response_text}"
                    )
                except requests.RequestException as error:
                    outcome = f"เกิดข้อผิดพลาด: {str(error)[:160]}"
                st.session_state.delivery_log.append(
                    {
                        "เวลา": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "เขตสุขภาพ": region,
                        "โรงพยาบาล": target["hospital_name"],
                        "กลุ่มผู้รับ": target["role"],
                        "เดือน": MONTHS[month - 1],
                        "ALERT": alert_total,
                        "WATCH": watch_total,
                        "ผลการดำเนินการ": outcome,
                    }
                )
            st.success(f"LINE API ตอบรับคำขอส่งสำเร็จ {success_count}/{len(targets)} ปลายทาง")
            st.warning(
                "HTTP 200 หมายถึง LINE API รับคำขอแล้ว ไม่ได้ยืนยันว่าผู้รับอ่านหรือเห็นข้อความแล้ว"
            )

    if not token:
        st.caption("ยังไม่ได้ตั้งค่า LINE_CHANNEL_ACCESS_TOKEN จึงใช้ได้เฉพาะโหมดจำลอง")
    if test_active:
        st.caption("โหมดทดสอบปิดการส่ง LINE จริง เพื่อป้องกันการส่งสถานะที่บังคับขึ้นไปยังผู้รับจริง")
    if not targets:
        st.caption(
            "ยังไม่มีปลายทางพร้อมส่ง: ต้องกรอก LINE ID ของแต่ละกลุ่ม และตั้ง consent_status เป็น approved"
        )
    if not flagged:
        st.caption("เดือนที่เลือกไม่มีโรคเข้าเกณฑ์ WATCH หรือ ALERT จึงปิดการส่ง LINE จริง")

    st.divider()
    st.subheader("ทะเบียนโรงพยาบาลและ LINE ID")
    st.caption(
        "กรอก LINE User ID หรือ Group ID แยกตามกลุ่มผู้รับ แล้วดาวน์โหลด CSV "
        "เพื่อนำไปแทนที่ data/hospital_registry.csv ใน GitHub"
    )
    edited_hospitals = st.data_editor(
        hospitals[HOSPITAL_COLUMNS],
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "is_active": st.column_config.CheckboxColumn("เปิดใช้งาน"),
            "line_user_id": st.column_config.TextColumn(
                "LINE ID เดิม (ไม่ใช้กระจายตามกลุ่ม)",
                help="คงไว้เพื่อความเข้ากันได้กับไฟล์เดิม ควรกรอก ID ในช่องแยกกลุ่มด้านล่างแทน",
            ),
            "line_epidemiology_id": st.column_config.TextColumn("LINE ID · ระบาดวิทยา"),
            "line_ic_id": st.column_config.TextColumn("LINE ID · ทีม IC"),
            "line_executive_id": st.column_config.TextColumn("LINE ID · ผู้บริหาร"),
            "consent_status": st.column_config.SelectboxColumn(
                "สถานะความยินยอม",
                options=["demo", "pending", "approved", "rejected"],
                help="สถานะ approved ใช้กับ LINE ID ทั้ง 3 กลุ่มของโรงพยาบาลนั้น",
            ),
        },
        key="hospital_registry_editor",
    )
    st.download_button(
        "ดาวน์โหลด hospital_registry.csv ที่แก้ไขแล้ว",
        edited_hospitals.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name="hospital_registry.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("เกณฑ์ WATCH / ALERT")
    display_thresholds = thresholds.rename(
        columns={
            "disease": "โรค",
            "watch_ratio": "WATCH ตั้งแต่ (เท่า)",
            "alert_ratio": "ALERT ตั้งแต่ (เท่า)",
            "zero_watch_cases": "WATCH เมื่อฐานเป็นศูนย์ (ราย)",
            "zero_alert_cases": "ALERT เมื่อฐานเป็นศูนย์ (ราย)",
            "rationale": "เหตุผลเบื้องต้น",
        }
    )
    threshold_columns = [
        "โรค",
        "WATCH ตั้งแต่ (เท่า)",
        "ALERT ตั้งแต่ (เท่า)",
        "WATCH เมื่อฐานเป็นศูนย์ (ราย)",
        "ALERT เมื่อฐานเป็นศูนย์ (ราย)",
        "เหตุผลเบื้องต้น",
    ]
    st.dataframe(display_thresholds[threshold_columns], hide_index=True, use_container_width=True)
    st.caption(
        "ค่าตัวคูณและจำนวนขั้นต่ำเป็นค่าเริ่มต้นเพื่อทดสอบระบบ ไม่ใช่เกณฑ์ทางการ "
        "ต้องให้ผู้เชี่ยวชาญทบทวนและรับรองก่อนใช้งานจริง"
    )

    st.divider()
    st.subheader("ประวัติการจำลอง / ส่งแจ้งเตือน")
    if st.session_state.delivery_log:
        log_frame = pd.DataFrame(st.session_state.delivery_log)
        st.dataframe(log_frame, hide_index=True, use_container_width=True)
        st.download_button(
            "ดาวน์โหลดประวัติการแจ้งเตือน CSV",
            log_frame.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
            file_name="NSDS_alert_delivery_log.csv",
            mime="text/csv",
        )
    else:
        st.caption("ยังไม่มีประวัติการส่งใน session นี้")


# ------------------------- Footer -------------------------

st.divider()
st.caption(
    "NSDS Dashboard V3 Prototype · Synthetic data only · "
    "LINE push requires opt-in, approved recipients, and valid Messaging API credentials"
)
