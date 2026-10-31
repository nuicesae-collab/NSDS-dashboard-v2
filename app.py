from pathlib import Path
from datetime import datetime
import os

import pandas as pd
import plotly.express as px
import streamlit as st
import requests

from generate_demo_data import (
    DISEASES,
    AGE_GROUPS,
    MONTHS,
    SHORT_MONTHS,
    REGIONS,
    build,
)

# ============================================================
# NSDS Dashboard V2
# Replace the existing app.py with this complete file.
# Existing CSV files and generate_demo_data.py are retained.
# ============================================================

st.set_page_config(
    page_title="NSDS Dashboard V2",
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

# Create demo files only if one or more expected files are missing.
if not all(path.exists() for path in DATA_FILES.values()):
    build(DATA_DIR)


def read_csv(path):
    """Read a project CSV file using UTF-8 with BOM support."""
    return pd.read_csv(path, encoding="utf-8-sig")


history = read_csv(DATA_FILES["history"])
forecast = read_csv(DATA_FILES["forecast"])
simulation = read_csv(DATA_FILES["simulation"])
thresholds = read_csv(DATA_FILES["thresholds"])
hospitals = read_csv(DATA_FILES["hospitals"])

# Normalize types and protect the dashboard from malformed CSV values.
for frame in (history, forecast, simulation):
    for column in ("year_be", "month", "cases"):
        frame[column] = pd.to_numeric(
            frame[column], errors="coerce"
        ).fillna(0).astype(int)
    frame["cases"] = frame["cases"].clip(lower=0)
    frame["month"] = frame["month"].clip(lower=1, upper=12)

for column in ("watch_ratio", "alert_ratio", "zero_watch_cases", "zero_alert_cases"):
    thresholds[column] = pd.to_numeric(thresholds[column], errors="coerce")

for column in ("hospital_id", "hospital_name", "health_region", "line_user_id", "consent_status"):
    if column not in hospitals.columns:
        hospitals[column] = ""

if "is_active" not in hospitals.columns:
    hospitals["is_active"] = True

# Stable ordering for age charts and tables.
for frame in (history, forecast, simulation):
    if "age_group" in frame.columns:
        frame["age_group"] = pd.Categorical(
            frame["age_group"], categories=AGE_GROUPS, ordered=True
        )

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
      .stMetric {
        background: #f5f7fb;
        padding: 12px;
        border-radius: 12px;
        border: 1px solid #e8edf5;
      }
      div[data-testid="stAlert"] {border-radius: 10px;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------- Shared helpers -------------------------

def is_active_value(value):
    return str(value).strip().lower() in ("true", "1", "yes", "y", "active", "ใช่")


def active_hospitals_for_region(region):
    active_mask = hospitals["is_active"].apply(is_active_value)
    return hospitals.loc[
        (hospitals["health_region"] == region) & active_mask
    ].copy()


def threshold_for(disease):
    rows = thresholds.loc[thresholds["disease"] == disease]
    if rows.empty:
        raise ValueError(f"ไม่พบค่าเกณฑ์ของ {disease}")
    return rows.iloc[0].to_dict()


def baseline_for(region, disease, month):
    """Median of the same month across the five historical years."""
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

    ratio = (
        current_cases / baseline
        if baseline is not None and baseline > 0
        else None
    )

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

    # Used only for clearly labelled test scenarios in the demo interface.
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


def demographic_summary(region, disease, month):
    rows = simulation.loc[
        (simulation["health_region"] == region)
        & (simulation["disease"] == disease)
        & (simulation["month"] == month)
    ]

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
    top_age = str(age_totals.idxmax()) if total else "ไม่มีข้อมูล"

    return {
        "total": total,
        "male": male,
        "female": female,
        "age_totals": age_totals,
        "top_age": top_age,
    }


def percent(part, total):
    return f"{part / total * 100:.1f}%" if total else "0.0%"


def status_icon(status):
    return {"ALERT": "🚨", "WATCH": "⚠️", "NORMAL": "🟢"}.get(status, "ℹ️")


def notification_for_disease(result, region):
    detail = demographic_summary(region, result["disease"], result["month"])
    total = detail["total"]
    male = detail["male"]
    female = detail["female"]
    ratio_text = (
        f"{result['ratio']:.2f} เท่า"
        if result["ratio"] is not None
        else "คำนวณอัตราส่วนไม่ได้"
    )
    baseline_text = (
        f"{int(round(result['baseline'])):,} ราย"
        if result["baseline"] is not None
        else "ไม่มีข้อมูลฐานเพียงพอ"
    )

    lines = [
        f"{status_icon(result['status'])} {result['status']} — {result['disease']}",
        f"ผู้ป่วยจำลอง: {total:,} ราย | ค่าฐานเดือนเดียวกัน 5 ปี: {baseline_text}",
        f"เทียบค่าฐาน: {ratio_text}",
        (
            f"เพศ: ชาย {male:,} ราย ({percent(male, total)})"
            f" · หญิง {female:,} ราย ({percent(female, total)})"
        ),
    ]

    if result["status"] == "ALERT":
        lines.append("จำแนกตามช่วงอายุ:")
        for age in AGE_GROUPS:
            count = int(detail["age_totals"].get(age, 0))
            lines.append(f"• {age}: {count:,} ราย ({percent(count, total)})")
    elif result["status"] == "WATCH":
        top_count = int(detail["age_totals"].get(detail["top_age"], 0))
        lines.append(
            f"ช่วงอายุที่พบมากที่สุด: {detail['top_age']} "
            f"{top_count:,} ราย ({percent(top_count, total)})"
        )

    return "\n".join(lines)


def build_notification(region, hospital_name, month, results, test_mode=False):
    flagged = [item for item in results if item["status"] in ("WATCH", "ALERT")]
    alert_count = sum(item["status"] == "ALERT" for item in flagged)
    watch_count = sum(item["status"] == "WATCH" for item in flagged)

    lines = [
        "🩺 NSDS | แจ้งเตือนเฝ้าระวังโรค",
        f"เขตสุขภาพ: {region}",
        f"โรงพยาบาลผู้รับ: {hospital_name}",
        f"เดือนที่ประเมิน: {MONTHS[month - 1]} 2569",
        f"สรุปสถานการณ์: ALERT {alert_count} โรค · WATCH {watch_count} โรค",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if flagged:
        lines.extend(
            notification_for_disease(item, region) for item in flagged
        )
    else:
        lines.append("ขณะนี้ไม่มีโรคที่เข้าเกณฑ์ WATCH หรือ ALERT ในเดือนที่เลือก")

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "หมายเหตุ: ข้อมูลทั้งหมดเป็นข้อมูลสังเคราะห์เพื่อสาธิตระบบ",
            "ไม่ใช่ข้อมูลผู้ป่วยจริงหรือประกาศเตือนภัยจากกรมควบคุมโรค",
        ]
    )

    if test_mode:
        lines.append("โหมดทดสอบ: มีการกำหนดสถานะเพื่อทดลองรูปแบบการแจ้งเตือน")

    # LINE text message limit is 5,000 characters.
    return "\n\n".join(lines)[:4900]


def get_secret(key):
    try:
        value = st.secrets.get(key, "")
        if value:
            return value
    except Exception:
        pass
    return os.getenv(key, "")


def send_line_message(token, user_id, message):
    response = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "to": str(user_id),
            "messages": [{"type": "text", "text": message}],
        },
        timeout=20,
    )
    return response.status_code, response.text[:500]


def year_data(year, source_2569):
    if year <= 2568:
        return history.loc[history["year_be"] == year].copy(), f"ข้อมูลย้อนหลัง {year}"
    if source_2569 == "คาดการณ์":
        return forecast.copy(), "คาดการณ์ 2569"
    return simulation.copy(), "จำลองสถานการณ์ 2569"


def monthly_disease_totals(frame, region):
    rows = frame.loc[frame["health_region"] == region]
    return (
        rows.groupby(["month", "disease"], as_index=False)["cases"]
        .sum()
        .sort_values(["month", "disease"])
    )


def make_month_labels(frame):
    result = frame.copy()
    result["เดือน"] = result["month"].map(
        lambda value: SHORT_MONTHS[int(value) - 1]
    )
    return result


def get_test_results(region, month, test_mode, selected_disease):
    results = []
    for disease_name in DISEASES:
        forced = None
        if disease_name == selected_disease:
            if test_mode == "ทดสอบ NORMAL":
                forced = "NORMAL"
            elif test_mode == "ทดสอบ WATCH":
                forced = "WATCH"
            elif test_mode == "ทดสอบ ALERT":
                forced = "ALERT"
        results.append(
            evaluate_disease(region, disease_name, month, force_status=forced)
        )
    return results


# ------------------------- App header and navigation -------------------------

st.title("🩺 NSDS Dashboard V2")
st.caption("ระบบวิเคราะห์แนวโน้มและเฝ้าระวังโรคระดับเขตสุขภาพ")

st.warning(
    "ชุดข้อมูลในเวอร์ชันนี้เป็นข้อมูลสังเคราะห์เพื่อสาธิตและทดสอบระบบ "
    "ไม่ใช่ข้อมูลผู้ป่วยจริงจากกรมควบคุมโรค"
)

st.session_state.setdefault("delivery_log", [])

with st.sidebar:
    st.header("เมนูระบบ")
    page = st.radio(
        "ไปยังหน้า",
        [
            "ภาพรวม Dashboard",
            "เปรียบเทียบผู้ป่วยรายเดือน",
            "แนวโน้ม 5 ปีและคาดการณ์",
            "วิเคราะห์อายุและเพศ",
            "เกณฑ์ WATCH / ALERT",
            "แจ้งเตือนโรงพยาบาล",
            "ทะเบียนโรงพยาบาล",
            "ข้อมูลและวิธีใช้",
        ],
    )
    region = st.selectbox("เลือกเขตสุขภาพ", REGIONS, index=3)
    disease = st.selectbox("เลือกโรค", DISEASES)


# ------------------------- Page: Overview -------------------------

if page == "ภาพรวม Dashboard":
    st.header(f"ภาพรวมสถานการณ์ · {region}")

    year_options = [2564, 2565, 2566, 2567, 2568, 2569]
    selected_year = st.selectbox("เลือกปีที่ต้องการดู", year_options, index=5)
    source_2569 = "จำลองสถานการณ์"
    if selected_year == 2569:
        source_2569 = st.radio(
            "ข้อมูลปี 2569",
            ["คาดการณ์", "จำลองสถานการณ์"],
            horizontal=True,
        )

    selected_frame, source_label = year_data(selected_year, source_2569)
    selected_frame = selected_frame.loc[
        selected_frame["health_region"] == region
    ]

    annual_total = int(selected_frame["cases"].sum())
    disease_totals = (
        selected_frame.groupby("disease")["cases"].sum().reindex(DISEASES, fill_value=0)
    )

    if selected_year == 2569 and source_2569 == "จำลองสถานการณ์":
        status_month = st.selectbox(
            "เดือนสำหรับสรุปสถานะ WATCH / ALERT",
            range(1, 13),
            index=9,
            format_func=lambda value: MONTHS[value - 1],
        )
        current_results = [
            evaluate_disease(region, name, status_month) for name in DISEASES
        ]
        alert_count = sum(item["status"] == "ALERT" for item in current_results)
        watch_count = sum(item["status"] == "WATCH" for item in current_results)
    else:
        alert_count = 0
        watch_count = 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(f"ผู้ป่วยรวม · {selected_year}", f"{annual_total:,} ราย")
    col2.metric("ALERT", alert_count if selected_year == 2569 and source_2569 == "จำลองสถานการณ์" else "—")
    col3.metric("WATCH", watch_count if selected_year == 2569 and source_2569 == "จำลองสถานการณ์" else "—")
    col4.metric("โรคที่ติดตาม", len(DISEASES))

    st.caption(f"แหล่งข้อมูลที่แสดง: {source_label}")

    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("เปรียบเทียบจำนวนผู้ป่วยทั้ง 6 โรค")
        bar_data = disease_totals.rename("ผู้ป่วย (ราย)").reset_index()
        bar_data.columns = ["โรค", "ผู้ป่วย (ราย)"]
        bar_fig = px.bar(
            bar_data.sort_values("ผู้ป่วย (ราย)"),
            x="ผู้ป่วย (ราย)",
            y="โรค",
            orientation="h",
            text_auto=True,
            labels={"ผู้ป่วย (ราย)": "จำนวนผู้ป่วย (ราย)"},
        )
        st.plotly_chart(bar_fig, use_container_width=True)

    with right:
        st.subheader("สัดส่วนผู้ป่วยรายโรค")
        pie_data = bar_data.loc[bar_data["ผู้ป่วย (ราย)"] > 0]
        if not pie_data.empty:
            pie_fig = px.pie(
                pie_data,
                names="โรค",
                values="ผู้ป่วย (ราย)",
                hole=0.42,
            )
            st.plotly_chart(pie_fig, use_container_width=True)
        else:
            st.info("ไม่มีข้อมูลสำหรับแสดงกราฟ")

    st.divider()
    st.subheader("กราฟเปรียบเทียบจำนวนผู้ป่วยรายเดือน · ทั้ง 6 โรค")
    monthly = make_month_labels(monthly_disease_totals(selected_frame, region))
    if not monthly.empty:
        line_fig = px.line(
            monthly,
            x="เดือน",
            y="cases",
            color="disease",
            markers=True,
            labels={"cases": "จำนวนผู้ป่วย (ราย)", "disease": "โรค"},
            category_orders={"เดือน": SHORT_MONTHS},
        )
        st.plotly_chart(line_fig, use_container_width=True)
    else:
        st.info("ไม่มีข้อมูลรายเดือนสำหรับตัวกรองนี้")

    st.subheader("ตารางสรุปจำนวนผู้ป่วยรายโรค")
    summary = bar_data.rename(columns={"โรค": "โรค", "ผู้ป่วย (ราย)": "จำนวนผู้ป่วย (ราย)"})
    st.dataframe(summary, hide_index=True, use_container_width=True)


# ------------------------- Page: Monthly comparison -------------------------

elif page == "เปรียบเทียบผู้ป่วยรายเดือน":
    st.header(f"เปรียบเทียบจำนวนผู้ป่วยรายเดือน · {region}")

    selected_year = st.selectbox(
        "เลือกปี",
        [2564, 2565, 2566, 2567, 2568, 2569],
        index=5,
        key="monthly_year",
    )
    source_2569 = "จำลองสถานการณ์"
    if selected_year == 2569:
        source_2569 = st.radio(
            "เลือกชุดข้อมูลปี 2569",
            ["คาดการณ์", "จำลองสถานการณ์"],
            horizontal=True,
            key="monthly_source",
        )

    frame, label = year_data(selected_year, source_2569)
    monthly = make_month_labels(monthly_disease_totals(frame, region))

    st.caption(f"กำลังแสดง: {label}")
    if not monthly.empty:
        st.plotly_chart(
            px.line(
                monthly,
                x="เดือน",
                y="cases",
                color="disease",
                markers=True,
                labels={
                    "cases": "จำนวนผู้ป่วย (ราย)",
                    "disease": "โรค",
                },
                category_orders={"เดือน": SHORT_MONTHS},
            ),
            use_container_width=True,
        )

        st.subheader("เลือกดูจำนวนผู้ป่วยรายเดือนของแต่ละโรค")
        chosen_month = st.selectbox(
            "เดือน",
            range(1, 13),
            format_func=lambda value: MONTHS[value - 1],
            key="monthly_bar_month",
        )
        one_month = monthly.loc[monthly["month"] == chosen_month]
        st.plotly_chart(
            px.bar(
                one_month.sort_values("cases"),
                x="cases",
                y="disease",
                orientation="h",
                text_auto=True,
                labels={"cases": "จำนวนผู้ป่วย (ราย)", "disease": "โรค"},
            ),
            use_container_width=True,
        )
        table = (
            monthly.pivot(index="disease", columns="เดือน", values="cases")
            .reindex(DISEASES)
            .reindex(columns=SHORT_MONTHS)
            .fillna(0)
            .astype(int)
        )
        st.subheader("ตารางข้อมูลรายเดือน")
        st.dataframe(table, use_container_width=True)
        st.download_button(
            "ดาวน์โหลดตารางรายเดือน CSV",
            table.to_csv(encoding="utf-8-sig").encode("utf-8-sig"),
            file_name=f"NSDS_monthly_{selected_year}_{region}.csv",
            mime="text/csv",
        )
    else:
        st.info("ไม่พบข้อมูลสำหรับตัวเลือกนี้")


# ------------------------- Page: Five-year trend -------------------------

elif page == "แนวโน้ม 5 ปีและคาดการณ์":
    st.header(f"แนวโน้มย้อนหลัง 2564–2568 และปี 2569 · {region}")
    selected_disease = st.selectbox(
        "เลือกโรคสำหรับวิเคราะห์",
        DISEASES,
        index=DISEASES.index(disease),
        key="trend_disease",
    )

    pieces = []
    history_rows = history.loc[
        (history["health_region"] == region)
        & (history["disease"] == selected_disease)
    ]
    for year_value, group in history_rows.groupby("year_be"):
        part = group.groupby("month", as_index=False)["cases"].sum()
        part["ชุดข้อมูล"] = f"ย้อนหลัง {year_value}"
        pieces.append(part)

    for frame, label in (
        (forecast, "คาดการณ์ 2569"),
        (simulation, "จำลอง 2569"),
    ):
        rows = frame.loc[
            (frame["health_region"] == region)
            & (frame["disease"] == selected_disease)
        ]
        part = rows.groupby("month", as_index=False)["cases"].sum()
        part["ชุดข้อมูล"] = label
        pieces.append(part)

    chart = make_month_labels(pd.concat(pieces, ignore_index=True))
    st.plotly_chart(
        px.line(
            chart,
            x="เดือน",
            y="cases",
            color="ชุดข้อมูล",
            markers=True,
            labels={"cases": "จำนวนผู้ป่วย (ราย)"},
            category_orders={"เดือน": SHORT_MONTHS},
        ),
        use_container_width=True,
    )

    st.info(
        "การคาดการณ์ปี 2569 ใช้ Linear Regression จากข้อมูลเดือนเดียวกันย้อนหลัง "
        "5 ปี เป็นการสาธิตวิธีวิเคราะห์ ยังไม่ได้ประเมินความแม่นยำเชิงพยากรณ์"
    )

    yearly_table = (
        history_rows.groupby(["month", "year_be"])["cases"]
        .sum()
        .unstack("year_be")
        .reindex(range(1, 13))
    )
    yearly_table["คาดการณ์ 2569"] = (
        forecast.loc[
            (forecast["health_region"] == region)
            & (forecast["disease"] == selected_disease)
        ]
        .groupby("month")["cases"]
        .sum()
        .reindex(range(1, 13))
    )
    yearly_table["จำลอง 2569"] = (
        simulation.loc[
            (simulation["health_region"] == region)
            & (simulation["disease"] == selected_disease)
        ]
        .groupby("month")["cases"]
        .sum()
        .reindex(range(1, 13))
    )
    yearly_table.insert(0, "เดือน", SHORT_MONTHS)
    st.dataframe(yearly_table.fillna(0).astype({c: int for c in yearly_table.columns if c != "เดือน"}), use_container_width=True)


# ------------------------- Page: Age and sex -------------------------

elif page == "วิเคราะห์อายุและเพศ":
    st.header(f"วิเคราะห์ผู้ป่วยตามช่วงอายุและเพศ · {region}")

    selected_disease = st.selectbox(
        "เลือกโรค",
        DISEASES,
        index=DISEASES.index(disease),
        key="demographic_disease",
    )
    source_choice = st.radio(
        "ชุดข้อมูลที่ต้องการวิเคราะห์",
        [
            "ย้อนหลัง 5 ปี (2564–2568)",
            "แยกปี 2564",
            "แยกปี 2565",
            "แยกปี 2566",
            "แยกปี 2567",
            "แยกปี 2568",
            "คาดการณ์ 2569",
            "จำลอง 2569",
        ],
        horizontal=True,
    )

    if source_choice.startswith("ย้อนหลัง"):
        frame = history
    elif source_choice == "คาดการณ์ 2569":
        frame = forecast
    elif source_choice == "จำลอง 2569":
        frame = simulation
    else:
        selected_year = int(source_choice[-4:])
        frame = history.loc[history["year_be"] == selected_year]

    demographic_rows = frame.loc[
        (frame["health_region"] == region)
        & (frame["disease"] == selected_disease)
    ].copy()

    month_filter = st.selectbox(
        "ช่วงเวลาที่ต้องการดู",
        ["รวมทั้งปี", *MONTHS],
        key="demographic_month",
    )
    if month_filter != "รวมทั้งปี":
        demographic_rows = demographic_rows.loc[
            demographic_rows["month"] == MONTHS.index(month_filter) + 1
        ]

    grouped = (
        demographic_rows.groupby(["age_group", "sex"], observed=False)["cases"]
        .sum()
        .reset_index()
    )
    grouped["age_group"] = pd.Categorical(
        grouped["age_group"], categories=AGE_GROUPS, ordered=True
    )
    total_cases = int(grouped["cases"].sum())
    male_total = int(grouped.loc[grouped["sex"] == "ชาย", "cases"].sum())
    female_total = int(grouped.loc[grouped["sex"] == "หญิง", "cases"].sum())

    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("ผู้ป่วยรวม", f"{total_cases:,} ราย")
    metric2.metric("ชาย", f"{male_total:,} ราย", percent(male_total, total_cases))
    metric3.metric("หญิง", f"{female_total:,} ราย", percent(female_total, total_cases))

    age_chart = (
        grouped.groupby("age_group", observed=False)["cases"]
        .sum()
        .reindex(AGE_GROUPS, fill_value=0)
        .rename_axis("ช่วงอายุ")
        .reset_index()
    )
    sex_chart = grouped.groupby("sex", as_index=False)["cases"].sum()

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            px.bar(
                age_chart,
                x="ช่วงอายุ",
                y="cases",
                text_auto=True,
                labels={"cases": "จำนวนผู้ป่วย (ราย)"},
                title="จำนวนผู้ป่วยแยกตามช่วงอายุ",
            ),
            use_container_width=True,
        )
    with right:
        if not sex_chart.empty:
            st.plotly_chart(
                px.pie(
                    sex_chart,
                    names="sex",
                    values="cases",
                    hole=0.4,
                    title="สัดส่วนผู้ป่วยแยกตามเพศ",
                ),
                use_container_width=True,
            )

    st.subheader("ตารางไขว้ช่วงอายุและเพศ")
    pivot = (
        grouped.pivot_table(
            index="age_group",
            columns="sex",
            values="cases",
            aggfunc="sum",
            observed=False,
        )
        .reindex(AGE_GROUPS)
        .fillna(0)
        .astype(int)
    )
    st.dataframe(pivot, use_container_width=True)

    st.caption(
        "ช่วงอายุที่ใช้เพื่อการแสดงผล: 0–4, 5–14, 15–24, 25–44, 45–64 และ 65 ปีขึ้นไป "
        "เป็นการจัดกลุ่มเพื่อให้อ่านกราฟง่าย ไม่ใช่การยืนยันว่าเป็นมาตรฐานช่วงอายุเดียวกัน "
        "ของกรมควบคุมโรคสำหรับทุกโรค"
    )


# ------------------------- Page: Thresholds -------------------------

elif page == "เกณฑ์ WATCH / ALERT":
    st.header("เกณฑ์ WATCH / ALERT แยกตามโรค")

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
    columns = [
        "โรค",
        "WATCH ตั้งแต่ (เท่า)",
        "ALERT ตั้งแต่ (เท่า)",
        "WATCH เมื่อฐานเป็นศูนย์ (ราย)",
        "ALERT เมื่อฐานเป็นศูนย์ (ราย)",
        "เหตุผลเบื้องต้น",
    ]
    st.dataframe(
        display_thresholds[columns],
        hide_index=True,
        use_container_width=True,
    )

    st.markdown(
        """
        **วิธีประเมินสถานะ**
        - NORMAL: จำนวนผู้ป่วยยังต่ำกว่าเกณฑ์ WATCH
        - WATCH: จำนวนผู้ป่วยเทียบค่าฐานถึงเกณฑ์ WATCH แต่ยังไม่ถึง ALERT
        - ALERT: จำนวนผู้ป่วยเทียบค่าฐานถึงเกณฑ์ ALERT
        - ค่าฐาน: มัธยฐานของจำนวนผู้ป่วยในเดือนเดียวกันย้อนหลัง 5 ปี (2564–2568)
        - หากค่าฐานเป็นศูนย์ ระบบใช้จำนวนขั้นต่ำรายโรคแทนการคำนวณอัตราส่วน
        """
    )
    st.warning(
        "ตัวคูณและจำนวนขั้นต่ำเป็นค่าเริ่มต้นสำหรับทดสอบโปรแกรมเท่านั้น "
        "ไม่ใช่เกณฑ์มาตรฐานทางการของกรมควบคุมโรค "
        "ต้องผ่านการทบทวนและรับรองโดยผู้เชี่ยวชาญก่อนใช้งานจริง"
    )


# ------------------------- Page: Hospital alerts -------------------------

elif page == "แจ้งเตือนโรงพยาบาล":
    st.header(f"ระบบแจ้งเตือนโรงพยาบาล · {region}")
    st.write(
        "เลือกเดือนและสถานการณ์ ระบบจะสรุปโรคที่เข้าเกณฑ์ WATCH / ALERT "
        "แล้วกระจายข้อความแยกไปยังโรงพยาบาลที่ลงทะเบียนในเขตสุขภาพนี้"
    )

    month = st.selectbox(
        "เดือนที่ต้องการทดสอบ",
        range(1, 13),
        index=9,
        format_func=lambda value: MONTHS[value - 1],
    )
    selected_alert_disease = st.selectbox(
        "โรคสำหรับทดสอบสถานะ",
        DISEASES,
        index=DISEASES.index(disease),
        key="alert_test_disease",
    )
    test_mode = st.radio(
        "รูปแบบการทดสอบ",
        [
            "คำนวณจากข้อมูลจำลอง 2569",
            "ทดสอบ NORMAL",
            "ทดสอบ WATCH",
            "ทดสอบ ALERT",
        ],
        horizontal=True,
    )
    force_mode = None
    if test_mode == "ทดสอบ NORMAL":
        force_mode = "NORMAL"
    elif test_mode == "ทดสอบ WATCH":
        force_mode = "WATCH"
    elif test_mode == "ทดสอบ ALERT":
        force_mode = "ALERT"

    results = get_test_results(
        region,
        month,
        force_mode,
        selected_alert_disease,
    )
    flagged = [item for item in results if item["status"] in ("WATCH", "ALERT")]
    alert_total = sum(item["status"] == "ALERT" for item in flagged)
    watch_total = sum(item["status"] == "WATCH" for item in flagged)
    test_active = force_mode is not None

    a, b, c = st.columns(3)
    a.metric("โรคระดับ ALERT", alert_total)
    b.metric("โรคระดับ WATCH", watch_total)
    c.metric("โรงพยาบาลที่ลงทะเบียนและเปิดใช้งาน", len(active_hospitals_for_region(region)))

    status_rows = [
        {
            "โรค": item["disease"],
            "จำนวนผู้ป่วยจำลอง": item["cases"],
            "ค่าฐาน 5 ปี": (
                round(item["baseline"]) if item["baseline"] is not None else None
            ),
            "เทียบฐาน (เท่า)": item["ratio"],
            "สถานะ": item["status"],
        }
        for item in results
    ]
    st.subheader("ผลประเมินทั้ง 6 โรค")
    st.dataframe(
        pd.DataFrame(status_rows),
        hide_index=True,
        use_container_width=True,
    )

    recipients = active_hospitals_for_region(region)
    st.subheader(f"รายชื่อผู้รับใน {region}")
    if recipients.empty:
        st.warning("ยังไม่มีโรงพยาบาลที่เปิดใช้งานในเขตสุขภาพนี้")
    else:
        st.dataframe(
            recipients[
                ["hospital_id", "hospital_name", "health_region", "consent_status"]
            ],
            hide_index=True,
            use_container_width=True,
        )

    preview_hospital = (
        recipients.iloc[0]["hospital_name"]
        if not recipients.empty
        else "โรงพยาบาลตัวอย่าง"
    )
    preview_message = build_notification(
        region,
        preview_hospital,
        month,
        results,
        test_mode=test_active,
    )

    with st.expander("ดูตัวอย่างข้อความแจ้งเตือน", expanded=True):
        st.code(preview_message, language="text")

    st.caption(
        "WATCH: แสดงจำนวนผู้ป่วย เพศ และช่วงอายุที่พบมากที่สุด "
        "· ALERT: แสดงจำนวนผู้ป่วย เพศ และรายละเอียดครบทุกช่วงอายุ"
    )

    if st.button(
        "จำลองกระจายข้อความให้ทุกโรงพยาบาลในเขต",
        type="primary",
        disabled=recipients.empty,
    ):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for _, hospital in recipients.iterrows():
            st.session_state.delivery_log.append(
                {
                    "เวลา": timestamp,
                    "เขตสุขภาพ": region,
                    "โรงพยาบาล": hospital["hospital_name"],
                    "เดือน": MONTHS[month - 1],
                    "โรค WATCH": watch_total,
                    "โรค ALERT": alert_total,
                    "ผลการดำเนินการ": "จำลองสำเร็จ (ไม่ได้ส่ง LINE จริง)",
                }
            )
        st.success(
            f"จำลองการกระจายข้อความให้โรงพยาบาล {len(recipients)} แห่งแล้ว "
            "การทำงานนี้ยังไม่ได้ส่ง LINE จริง"
        )

    st.divider()
    st.subheader("ส่ง LINE จริง (เมื่อเตรียมระบบและได้รับความยินยอมแล้ว)")

    token = get_secret("LINE_CHANNEL_ACCESS_TOKEN")
    approved_recipients = recipients.loc[
        (recipients["consent_status"].astype(str).str.lower() == "approved")
        & recipients["line_user_id"].fillna("").astype(str).str.strip().ne("")
    ]

    st.info(
        f"โรงพยาบาลที่เปิดใช้งานและมี LINE User ID พร้อมสถานะ approved: "
        f"{len(approved_recipients)} แห่ง"
    )
    consent_confirmed = st.checkbox(
        "ยืนยันว่าผู้รับทุกแห่งในรายการ approved ยินยอมรับข้อความแจ้งเตือน"
    )

    real_send_disabled = (
        not token
        or approved_recipients.empty
        or not consent_confirmed
        or test_active
        or not flagged
    )

    if st.button(
        "ส่ง LINE จริงให้โรงพยาบาลที่อนุมัติ",
        disabled=real_send_disabled,
    ):
        success_count = 0
        for _, hospital in approved_recipients.iterrows():
            message = build_notification(
                region,
                hospital["hospital_name"],
                month,
                results,
                test_mode=False,
            )
            try:
                status_code, response_text = send_line_message(
                    token,
                    hospital["line_user_id"],
                    message,
                )
                success = status_code == 200
                success_count += int(success)
                st.session_state.delivery_log.append(
                    {
                        "เวลา": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "เขตสุขภาพ": region,
                        "โรงพยาบาล": hospital["hospital_name"],
                        "เดือน": MONTHS[month - 1],
                        "โรค WATCH": watch_total,
                        "โรค ALERT": alert_total,
                        "ผลการดำเนินการ": (
                            f"ส่งสำเร็จ (HTTP {status_code})"
                            if success
                            else f"ส่งไม่สำเร็จ (HTTP {status_code}) {response_text}"
                        ),
                    }
                )
            except requests.RequestException as error:
                st.session_state.delivery_log.append(
                    {
                        "เวลา": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "เขตสุขภาพ": region,
                        "โรงพยาบาล": hospital["hospital_name"],
                        "เดือน": MONTHS[month - 1],
                        "โรค WATCH": watch_total,
                        "โรค ALERT": alert_total,
                        "ผลการดำเนินการ": f"เกิดข้อผิดพลาด: {str(error)[:160]}",
                    }
                )
        st.success(
            f"LINE API ตอบรับคำขอส่งสำเร็จ {success_count}/"
            f"{len(approved_recipients)} โรงพยาบาล"
        )
        st.warning(
            "HTTP 200 หมายถึง LINE API รับคำขอแล้ว ไม่ได้ยืนยันว่าผู้รับอ่านหรือได้รับข้อความบนอุปกรณ์แล้ว"
        )

    if not token:
        st.caption(
            "ยังไม่ได้ตั้งค่า LINE_CHANNEL_ACCESS_TOKEN ใน Streamlit Secrets "
            "จึงใช้ได้เฉพาะโหมดจำลอง"
        )
    if test_active:
        st.caption(
            "ปิดการส่ง LINE จริงในโหมดทดสอบ เพื่อป้องกันการส่งสถานะที่บังคับขึ้นไปยังผู้รับจริง"
        )

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


# ------------------------- Page: Hospital registry -------------------------

elif page == "ทะเบียนโรงพยาบาล":
    st.header("ทะเบียนโรงพยาบาล")
    st.write(
        "หนึ่งแถวแทนโรงพยาบาลหนึ่งแห่ง และ LINE User ID ใช้ระบุปลายทางของโรงพยาบาลนั้น "
        "ไม่ใช่ชื่อบัญชี LINE ที่ใช้ค้นหาเพื่อน"
    )

    edited_hospitals = st.data_editor(
        hospitals,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "is_active": st.column_config.CheckboxColumn(
                "เปิดใช้งาน",
                help="เลือกเพื่อให้โรงพยาบาลอยู่ในรายชื่อผู้รับที่เปิดใช้งาน",
            ),
            "line_user_id": st.column_config.TextColumn(
                "LINE User ID",
                help="ใส่ User ID ที่ได้จาก LINE Messaging API / webhook",
            ),
            "consent_status": st.column_config.SelectboxColumn(
                "สถานะความยินยอม",
                options=["demo", "pending", "approved", "rejected"],
            ),
        },
    )

    st.download_button(
        "ดาวน์โหลดทะเบียนโรงพยาบาลที่แก้ไข",
        edited_hospitals.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name="hospital_registry.csv",
        mime="text/csv",
    )

    st.warning(
        "การแก้ไขในหน้านี้ยังไม่บันทึกกลับไปยัง GitHub หรือไฟล์ CSV บนเซิร์ฟเวอร์ "
        "ให้ดาวน์โหลดไฟล์ที่แก้ไข แล้วนำไปแทนที่ data/hospital_registry.csv ใน Repository"
    )


# ------------------------- Page: Data notes -------------------------

else:
    st.header("ข้อมูลและวิธีใช้")

    st.markdown(
        """
        **ขอบเขตของ Dashboard**
        - 6 โรคที่ใช้ในต้นแบบ
        - 13 เขตสุขภาพ
        - ข้อมูลย้อนหลัง 5 ปี พ.ศ. 2564–2568
        - ข้อมูลคาดการณ์ปี 2569
        - ข้อมูลจำลองสถานการณ์ปี 2569
        - จำแนกข้อมูลตามเพศ 2 กลุ่ม และช่วงอายุ 6 กลุ่ม

        **ช่วงอายุที่ใช้แสดงผล**
        - 0–4 ปี
        - 5–14 ปี
        - 15–24 ปี
        - 25–44 ปี
        - 45–64 ปี
        - 65 ปีขึ้นไป

        ช่วงอายุเหล่านี้เป็นการจัดกลุ่มเพื่อให้กราฟอ่านง่ายและเปรียบเทียบได้ในต้นแบบ
        ไม่ใช่การยืนยันว่าเป็นมาตรฐานช่วงอายุเดียวกันของกรมควบคุมโรคสำหรับทุกโรค

        **การคาดการณ์**
        ใช้ Linear Regression จากข้อมูลเดือนเดียวกันย้อนหลัง 5 ปี
        แยกชุดคาดการณ์ออกจากชุดจำลองสถานการณ์อย่างชัดเจน

        **การแจ้งเตือน**
        เมื่อเลือกเขตสุขภาพ ระบบจะเตรียมข้อความแยกตามโรงพยาบาลทุกแห่ง
        ที่ลงทะเบียนและเปิดใช้งานในเขตนั้น โทรศัพท์หรือบัญชี LINE ของแต่ละโรงพยาบาล
        ต้องมี LINE User ID ที่ถูกต้องและได้รับความยินยอมก่อนส่งจริง

        **ข้อจำกัดสำคัญ**
        ไฟล์ CSV ในต้นแบบเป็นข้อมูลสังเคราะห์ ไม่ใช่ข้อมูลจริงจากกรมควบคุมโรค
        เกณฑ์ WATCH / ALERT เป็นค่าเริ่มต้นเพื่อทดสอบระบบ ไม่ใช่เกณฑ์ทางการ
        ต้องตรวจสอบแหล่งข้อมูลและให้ผู้เชี่ยวชาญรับรองก่อนใช้สนับสนุนการตัดสินใจจริง
        """
    )

    st.subheader("ดาวน์โหลดชุดข้อมูลที่แอปกำลังใช้")
    for key, label in [
        ("history", "ข้อมูลย้อนหลัง 2564–2568"),
        ("forecast", "ข้อมูลคาดการณ์ 2569"),
        ("simulation", "ข้อมูลจำลอง 2569"),
        ("thresholds", "เกณฑ์ WATCH / ALERT"),
        ("hospitals", "ทะเบียนโรงพยาบาล"),
    ]:
        file_path = DATA_FILES[key]
        st.download_button(
            f"ดาวน์โหลด {label}",
            file_path.read_bytes(),
            file_name=file_path.name,
            mime="text/csv",
            key=f"download_{key}",
        )


# ------------------------- Footer -------------------------

st.divider()
st.caption(
    "NSDS Dashboard V2 Prototype · Synthetic data only · "
    "LINE push requires opt-in, a valid LINE User ID, and Messaging API credentials"
)
