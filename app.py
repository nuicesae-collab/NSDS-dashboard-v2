from pathlib import Path
from datetime import datetime
import os, sqlite3, hmac
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from generate_demo_data import DISEASES, AGE_GROUPS, MONTHS, SHORT_MONTHS, REGIONS, build

st.set_page_config(page_title="NSDS Dashboard V2", page_icon="🩺", layout="wide")
ROOT = Path(__file__).parent
DATA = ROOT / "data"
FILES = {
    "history": DATA / "historical_cases_2564_2568.csv",
    "forecast": DATA / "forecast_2569.csv",
    "simulation": DATA / "simulation_2569.csv",
    "thresholds": DATA / "disease_thresholds.csv",
    "hospitals": DATA / "hospital_registry.csv",
}
DB = DATA / "notification_history.sqlite3"
DASH_URL = "https://nsds-dashboard-v2-dmyt5gi52if5njkgwsohja.streamlit.app/"

# Generate only missing CSVs; never overwrite existing synthetic data.
missing = [k for k, p in FILES.items() if not p.exists()]
if missing:
    tmp = ROOT / ".nsds_demo_build"
    build(tmp)
    DATA.mkdir(parents=True, exist_ok=True)
    for k in missing:
        (tmp / FILES[k].name).replace(FILES[k])

def read(path):
    return pd.read_csv(path, encoding="utf-8-sig")

history, forecast, simulation, thresholds, hospitals = [read(FILES[k]) for k in
    ("history", "forecast", "simulation", "thresholds", "hospitals")]

required = {"year_be","month","disease","health_region","age_group","sex","cases","data_status"}
for name, frame in [("history",history),("forecast",forecast),("simulation",simulation)]:
    missing_cols = required - set(frame.columns)
    if missing_cols:
        st.error(f"{name} ขาดคอลัมน์: {', '.join(sorted(missing_cols))}")
        st.stop()
    for col in ("year_be","month","cases"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0).astype(int)
    frame["cases"] = frame["cases"].clip(lower=0)
    frame["month"] = frame["month"].clip(1,12)
    frame["age_group"] = pd.Categorical(frame["age_group"], categories=AGE_GROUPS, ordered=True)

for col in ("watch_ratio","alert_ratio","zero_watch_cases","zero_alert_cases"):
    if col in thresholds:
        thresholds[col] = pd.to_numeric(thresholds[col], errors="coerce")
for col in ("hospital_id","hospital_name","health_region","line_user_id","consent_status"):
    if col not in hospitals: hospitals[col] = ""
if "is_active" not in hospitals: hospitals["is_active"] = True

st.markdown("""
<style>
.block-container{padding-top:1.1rem;padding-bottom:2rem;max-width:1500px}
[data-testid="stMetric"]{background:#f5f7fb;border:1px solid #e7edf5;padding:13px 15px;border-radius:12px}
[data-testid="stAlert"]{border-radius:10px}
/* NSDS overview cards only: scoped classes, other pages remain unchanged. */
.nsds-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:0 0 10px}
.nsds-kpi-card{box-sizing:border-box;min-width:0;min-height:148px;padding:16px 18px;border:1px solid;border-radius:15px;display:flex;flex-direction:column;justify-content:space-between}
.nsds-kpi-head{display:flex;align-items:center;gap:10px;color:#20283a;font-size:15px;font-weight:650;line-height:1.35}
.nsds-kpi-icon{width:38px;height:38px;flex:0 0 38px;border-radius:50%;display:grid;place-items:center}
.nsds-kpi-icon svg{width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.nsds-kpi-value{margin-top:10px;color:#172033;font-size:32px;font-weight:750;line-height:1.15;letter-spacing:-.5px;overflow-wrap:anywhere}
.nsds-kpi-note{min-height:18px;margin-top:7px;color:#667085;font-size:12px;line-height:1.35}
.nsds-kpi-blue{background:linear-gradient(135deg,#eff6ff 0%,#dceafe 100%);border-color:#d5e7ff}
.nsds-kpi-blue .nsds-kpi-icon{background:#d5e8ff;color:#1764c0}
.nsds-kpi-pink{background:linear-gradient(135deg,#fff1f3 0%,#ffe0e6 100%);border-color:#ffd8df}
.nsds-kpi-pink .nsds-kpi-icon{background:#ffd9df;color:#b42318}
.nsds-kpi-yellow{background:linear-gradient(135deg,#fffbea 0%,#fff3c4 100%);border-color:#f9edc1}
.nsds-kpi-yellow .nsds-kpi-icon{background:#ffedb0;color:#956000}
.nsds-kpi-purple{background:linear-gradient(135deg,#f7f0ff 0%,#eadcff 100%);border-color:#eadbff}
.nsds-kpi-purple .nsds-kpi-icon{background:#e7d5ff;color:#7138b5}
.nsds-kpi-change{display:inline-flex;align-items:center;gap:5px;margin-top:7px;padding:4px 9px;border-radius:999px;font-size:12px;font-weight:650;width:max-content}
.nsds-kpi-change-positive{background:#dcfce7;color:#187443}
.nsds-kpi-change-negative{background:#fee2e2;color:#b42318}
.nsds-kpi-change-neutral{background:#e9edf5;color:#475467}
@media(max-width:1050px){.nsds-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){.nsds-kpi-grid{grid-template-columns:1fr}.nsds-kpi-card{min-height:130px}}
</style>""", unsafe_allow_html=True)

def secret(key, default=""):
    try:
        v = st.secrets.get(key, default)
        if v not in (None, ""): return v
    except Exception: pass
    return os.getenv(key, default)

def active(v):
    return str(v).strip().lower() in {"true","1","yes","y","active","ใช่"}

def role_ids(role):
    try:
        section = st.secrets.get("LINE_RECIPIENTS", {})
        values = section.get(role, []) if section else []
    except Exception: values = []
    if isinstance(values, str): values = [x.strip() for x in values.split(",") if x.strip()]
    if not values:
        env = {"epidemiology":"LINE_EPIDEMIOLOGY_USER_IDS",
               "ic":"LINE_IC_USER_IDS","executives":"LINE_EXECUTIVE_USER_IDS"}[role]
        values = [x.strip() for x in os.getenv(env,"").split(",") if x.strip()]
    return [str(x).strip() for x in values if str(x).strip()]

def baseline(region, disease, month):
    rows = history[(history.health_region==region)&(history.disease==disease)&(history.month==month)]
    yearly = rows.groupby("year_be").cases.sum().reindex(range(2564,2569))
    return float(yearly.mean()) if yearly.notna().sum()==5 else None

def eval_disease(region, disease, month):
    rows = simulation[(simulation.health_region==region)&(simulation.disease==disease)&(simulation.month==month)]
    count = int(rows.cases.sum())
    base = baseline(region,disease,month)
    rules = thresholds[thresholds.disease==disease]
    if rules.empty: return dict(disease=disease,cases=count,baseline=base,ratio=None,status="ไม่มีเกณฑ์")
    rule = rules.iloc[0]
    ratio = count/base if base is not None and base>0 else None
    if base is None: status="ข้อมูลฐานไม่ครบ"
    elif base<=0:
        status="ALERT" if count>=int(rule.zero_alert_cases) else ("WATCH" if count>=int(rule.zero_watch_cases) else "NORMAL")
    elif ratio>=float(rule.alert_ratio): status="ALERT"
    elif ratio>=float(rule.watch_ratio): status="WATCH"
    else: status="NORMAL"
    return dict(disease=disease,cases=count,baseline=base,ratio=ratio,status=status)

def year_frame(year):
    if year<=2568: return history[history.year_be==year].copy(), f"ข้อมูลย้อนหลังจำลอง พ.ศ. {year}"
    return simulation.copy(), "ข้อมูลสถานการณ์จำลอง พ.ศ. 2569"

def demo_summary(frame, region, disease):
    rows=frame[(frame.health_region==region)&(frame.disease==disease)]
    age=rows.groupby("age_group",observed=False).cases.sum().reindex(AGE_GROUPS,fill_value=0)
    sex=rows.groupby("sex").cases.sum().reindex(["ชาย","หญิง"],fill_value=0)
    return age,sex,int(rows.cases.sum())

def pct(n,total): return f"{n/total*100:.1f}%" if total else "0.0%"
def dashboard_link(base_url, region, month, disease, status):
    parts = urlsplit(str(base_url).strip())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))

    query.update({
        "view": "overview",
        "region": region,
        "year_be": "2569",
        "month": str(month),
        "highlight_disease": disease,
        "highlight_status": status,
    })

    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path or "/",
        urlencode(query),
        parts.fragment
    ))
def message(region, month, results, recipient, url):
    flagged=[x for x in results if x["status"] in ("WATCH","ALERT")]
    a=sum(x["status"]=="ALERT" for x in flagged); w=sum(x["status"]=="WATCH" for x in flagged)
    lines=["🩺 NSDS V2 | แจ้งเตือนเฝ้าระวังโรค",f"เขตสุขภาพ: {region}",f"ผู้รับ: {recipient}",
           f"เดือนประเมิน: {MONTHS[month-1]} พ.ศ. 2569",f"สรุป: ALERT {a} โรค | WATCH {w} โรค","━━━━━━━━━━━━━━━━━━"]
    if not flagged: lines.append("ไม่พบโรคที่เข้าเกณฑ์ WATCH หรือ ALERT")
    for x in flagged:
        age,sex,total=demo_summary(simulation,region,x["disease"])
        base=f"{x['baseline']:,.1f} ราย" if x["baseline"] is not None else "ข้อมูลฐานไม่ครบ"
        ratio=f"{x['ratio']:.2f} เท่า" if x["ratio"] is not None else "คำนวณไม่ได้"
        lines += ["",f"{'🔴' if x['status']=='ALERT' else '🟠'} {x['status']} | {x['disease']}",
                  f"ผู้ป่วยจำลอง: {x['cases']:,} ราย",f"Baseline เฉลี่ย 5 ปี: {base} | เทียบฐาน: {ratio}",
                  f"เพศชาย {int(sex['ชาย']):,} ({pct(int(sex['ชาย']),total)}) · หญิง {int(sex['หญิง']):,} ({pct(int(sex['หญิง']),total)})",
                  "จำแนกตามอายุ:"]
        for g in AGE_GROUPS:
            n=int(age[g])
            lines.append(f"• {g}: {n:,} ราย ({pct(n,total)})")

        disease_url = dashboard_link(
            url, region, month, x["disease"], x["status"]
        )
        lines.append(
            f"📊 Dashboard เฉพาะโรค {x['disease']}: {disease_url}"
        )

    lines += [
        "────────────",
        "ข้อมูลสังเคราะห์เพื่อการศึกษา ไม่ใช่ข้อมูลผู้ป่วยจริง"
    ]
    return "\n".join(lines)[:4900]        
            





def send_line(token,target,text):
    r=requests.post("https://api.line.me/v2/bot/message/push",
        headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
        json={"to":target,"messages":[{"type":"text","text":text}]},timeout=20)
    return r.status_code,r.text[:400]

def init_log():
    DATA.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS delivery_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, region TEXT, month INTEGER,
        recipient TEXT, status TEXT, detail TEXT)""")
        c.commit()

def log_delivery(region,month,recipient,status,detail):
    init_log()
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO delivery_log(created_at,region,month,recipient,status,detail) VALUES(?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"),region,month,recipient,status,detail))
        c.commit()

def read_log():
    init_log()
    with sqlite3.connect(DB) as c:
        return pd.read_sql_query("SELECT created_at AS เวลา,region AS เขตสุขภาพ,month AS เดือน,recipient AS ผู้รับ,status AS สถานะ,detail AS รายละเอียด FROM delivery_log ORDER BY id DESC LIMIT 100",c)

# ---------------- Sidebar ----------------
st.title("🩺 NSDS Dashboard V2")
st.caption("ระบบวิเคราะห์แนวโน้มและเฝ้าระวังโรคระดับเขตสุขภาพ")
with st.sidebar:
    st.header("เมนูระบบ")
    page=st.radio("ไปยังหน้า",["ภาพรวม Dashboard","วิเคราะห์อายุและเพศ","แจ้งเตือนโรงพยาบาล"],label_visibility="collapsed")
    st.divider()
    st.subheader("ตัวเลือกข้อมูล")
    region=st.selectbox("เขตสุขภาพ",REGIONS,index=3)
    year=st.selectbox("ปี พ.ศ.",[2564,2565,2566,2567,2568,2569],index=5)
    query_disease = st.query_params.get("highlight_disease", "")
    disease_index = DISEASES.index(query_disease) if query_disease in DISEASES else 0
    
    disease = st.selectbox("โรค", DISEASES, index=disease_index)

# ---------------- Page 1 ----------------
if page=="ภาพรวม Dashboard":
    st.header(f"ภาพรวมสถานการณ์ | {region}")
    selected,source=year_frame(year)
    selected=selected[selected.health_region==region].copy()
    month_compare=st.selectbox("เดือนสำหรับกราฟเปรียบเทียบ 6 โรค",range(1,13),index=9,format_func=lambda m:MONTHS[m-1])
    # Summary cards: calculations are scoped to the selected region and disease.
    # For the current year, use the latest completed month; historical years use December.
    current_year_be = datetime.now().year + 543
    latest_month = max(1, datetime.now().month - 1) if year == current_year_be else 12
    disease_rows = selected[selected.disease == disease]
    accumulated_cases = int(disease_rows.cases.sum())
    latest_cases = int(disease_rows.loc[disease_rows.month == latest_month, "cases"].sum())
    previous_month = 12 if latest_month == 1 else latest_month - 1
    previous_cases = int(disease_rows.loc[disease_rows.month == previous_month, "cases"].sum())

    if previous_cases > 0:
        change_pct = (latest_cases - previous_cases) / previous_cases * 100
        change_text = f"{change_pct:+.1f}%"
    elif latest_cases == 0:
        change_text = "0.0%"
    else:
        change_text = "—"

    change_count = latest_cases - previous_cases
    if change_count > 0:
        change_badge = f"↑ +{change_count:,} ราย"
        change_class = "nsds-kpi-change-positive"
    elif change_count < 0:
        change_badge = f"↓ {change_count:,} ราย"
        change_class = "nsds-kpi-change-negative"
    else:
        change_badge = "→ 0 ราย"
        change_class = "nsds-kpi-change-neutral"

    if year == 2569:
        card_status = [eval_disease(region, d, latest_month) for d in DISEASES]
        alert_n = sum(x["status"] == "ALERT" for x in card_status)
        watch_n = sum(x["status"] == "WATCH" for x in card_status)
        flagged_n = alert_n + watch_n
        status_value = f"{flagged_n}"
        status_note = f"ALERT {alert_n} · WATCH {watch_n}"
    else:
        status_value = "—"
        status_note = "แสดงสถานะเมื่อเลือกปี 2569"

    users_icon = "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2'/><circle cx='9' cy='7' r='4'/><path d='M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75'/></svg>"
    calendar_icon = "<svg viewBox='0 0 24 24' aria-hidden='true'><rect x='3' y='5' width='18' height='16' rx='2'/><path d='M16 3v4M8 3v4M3 11h18'/></svg>"
    trend_icon = "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='m3 17 6-6 4 4 8-9'/><path d='M15 6h6v6'/></svg>"
    bell_icon = "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4'/></svg>"

    cards_html = f"""
    <div class="nsds-kpi-grid">
      <section class="nsds-kpi-card nsds-kpi-blue">
        <div class="nsds-kpi-head"><span class="nsds-kpi-icon">{users_icon}</span><span>ผู้ป่วยสะสมโรคที่เลือก</span></div>
        <div class="nsds-kpi-value">{accumulated_cases:,} ราย</div>
        <div class="nsds-kpi-note">{disease} · {region} · พ.ศ. {year}</div>
      </section>
      <section class="nsds-kpi-card nsds-kpi-pink">
        <div class="nsds-kpi-head"><span class="nsds-kpi-icon">{calendar_icon}</span><span>ผู้ป่วยเดือนล่าสุด</span></div>
        <div class="nsds-kpi-value">{latest_cases:,} ราย</div>
        <div class="nsds-kpi-note">{MONTHS[latest_month - 1]} พ.ศ. {year}</div>
      </section>
      <section class="nsds-kpi-card nsds-kpi-yellow">
        <div class="nsds-kpi-head"><span class="nsds-kpi-icon">{trend_icon}</span><span>เปลี่ยนแปลงจากเดือนก่อน</span></div>
        <div class="nsds-kpi-value">{change_text}</div>
        <div class="nsds-kpi-change {change_class}">{change_badge}</div>
      </section>
      <section class="nsds-kpi-card nsds-kpi-purple">
        <div class="nsds-kpi-head"><span class="nsds-kpi-icon">{bell_icon}</span><span>STATUS WATCH / ALERT</span></div>
        <div class="nsds-kpi-value">{status_value}</div>
        <div class="nsds-kpi-note">{status_note}</div>
      </section>
    </div>
    """
    st.markdown(cards_html, unsafe_allow_html=True)
    st.caption(f"{source} · สถานะ WATCH/ALERT ประเมินจาก Simulation 2569")

    st.subheader(f"แนวโน้มผู้ป่วยรายเดือน | {disease}")
    fig=go.Figure()
    for y in range(2564,2569):
        rows=history[(history.health_region==region)&(history.disease==disease)&(history.year_be==y)]
        vals=rows.groupby("month").cases.sum().reindex(range(1,13),fill_value=0)
        fig.add_trace(go.Scatter(x=SHORT_MONTHS,y=vals.tolist(),mode="lines+markers",name=f"ข้อมูลจริง {y}",line={"width":2}))
    for frame,label,dash in [(forecast,"Forecast 2569","dash"),(simulation,"Simulation 2569","dot")]:
        rows=frame[(frame.health_region==region)&(frame.disease==disease)]
        vals=rows.groupby("month").cases.sum().reindex(range(1,13),fill_value=0)
        fig.add_trace(go.Scatter(x=SHORT_MONTHS,y=vals.tolist(),mode="lines+markers",name=label,line={"width":3,"dash":dash}))
    fig.update_layout(height=430,margin={"l":10,"r":10,"t":20,"b":10},xaxis_title="เดือน",yaxis_title="จำนวนผู้ป่วยจำลอง (ราย)",legend_title="ประเภทข้อมูล",hovermode="x unified")
    st.plotly_chart(fig,use_container_width=True)

    left,right=st.columns([1.15,1])
    with left:
        st.subheader(f"เปรียบเทียบ 6 โรค | {MONTHS[month_compare-1]} {year}")
        bar=selected[selected.month==month_compare].groupby("disease").cases.sum().reindex(DISEASES,fill_value=0).rename("ผู้ป่วย (ราย)").reset_index()
        bar.columns=["โรค","ผู้ป่วย (ราย)"]
        bf=px.bar(bar.sort_values("ผู้ป่วย (ราย)"),x="ผู้ป่วย (ราย)",y="โรค",orientation="h",text="ผู้ป่วย (ราย)")
        bf.update_layout(height=390,margin={"l":5,"r":5,"t":15,"b":5})
        st.plotly_chart(bf,use_container_width=True)
    with right:
        st.subheader("สรุปจำนวนผู้ป่วยรายโรค")
        summary=selected.groupby("disease").cases.sum().reindex(DISEASES,fill_value=0).rename("ผู้ป่วย (ราย)").reset_index()
        summary.columns=["โรค","ผู้ป่วย (ราย)"]
        st.dataframe(summary,hide_index=True,use_container_width=True,height=390)
    st.caption("ข้อมูลย้อนหลัง 2564–2568, Forecast และ Simulation เป็นข้อมูลสังเคราะห์เพื่อสาธิต")

# ---------------- Page 2 ----------------
elif page=="วิเคราะห์อายุและเพศ":
    st.header(f"วิเคราะห์อายุและเพศ | {disease}")
    frame,source=year_frame(year); frame=frame[frame.health_region==region]
    age,sex,total=demo_summary(frame,region,disease)
    st.caption(f"{region} · พ.ศ. {year} · {source}")
    a,b,c=st.columns(3)
    a.metric("ผู้ป่วยรวม",f"{total:,} ราย"); b.metric("เพศชาย",f"{int(sex['ชาย']):,} ราย"); c.metric("เพศหญิง",f"{int(sex['หญิง']):,} ราย")
    left,right=st.columns([1.3,1])
    with left:
        st.subheader("จำนวนผู้ป่วยจำแนกตามช่วงอายุ")
        ad=age.rename("ผู้ป่วย (ราย)").reset_index(); ad.columns=["ช่วงอายุ","ผู้ป่วย (ราย)"]
        af=px.bar(ad,x="ช่วงอายุ",y="ผู้ป่วย (ราย)",text="ผู้ป่วย (ราย)",category_orders={"ช่วงอายุ":AGE_GROUPS})
        af.update_layout(height=400); st.plotly_chart(af,use_container_width=True)
    with right:
        st.subheader("สัดส่วนผู้ป่วยตามเพศ")
        sd=sex.rename("ผู้ป่วย (ราย)").reset_index(); sd.columns=["เพศ","ผู้ป่วย (ราย)"]
        sf=px.pie(sd,names="เพศ",values="ผู้ป่วย (ราย)",hole=.48); sf.update_layout(height=400)
        st.plotly_chart(sf,use_container_width=True)
    st.subheader("ตารางจำแนกอายุและเพศ")
    cross=frame[frame.disease==disease].pivot_table(index="age_group",columns="sex",values="cases",aggfunc="sum",fill_value=0,observed=False)
    cross=cross.reindex(AGE_GROUPS,fill_value=0).reindex(columns=["ชาย","หญิง"],fill_value=0)
    cross["รวม"]=cross.sum(axis=1)
    st.dataframe(cross.reset_index().rename(columns={"age_group":"ช่วงอายุ"}),hide_index=True,use_container_width=True)

# ---------------- Page 3: Admin-only notifications ----------------
else:
    st.header("แจ้งเตือนโรงพยาบาลและเจ้าหน้าที่")
    st.caption("พื้นที่ผู้ดูแลระบบ · ต้องยืนยันรหัสผ่านก่อนส่ง LINE และดูประวัติการส่ง")

    admin_password = str(secret("NSDS_ADMIN_PASSWORD", "")).strip()
    if not admin_password:
        st.warning("ยังไม่ได้ตั้งรหัสผ่านผู้ดูแลระบบ จึงยังเข้าใช้งานส่วนแจ้งเตือนไม่ได้")
        st.markdown("เพิ่ม `NSDS_ADMIN_PASSWORD` ใน Streamlit App → Settings → Secrets ก่อนเปิดใช้")
        st.stop()

    if not st.session_state.get("nsds_admin_authenticated", False):
        with st.form("nsds_admin_login"):
            entered_password = st.text_input("รหัสผ่านผู้ดูแลระบบ", type="password")
            login_clicked = st.form_submit_button("เข้าสู่ระบบผู้ดูแล", type="primary")
        if login_clicked:
            if hmac.compare_digest(entered_password, admin_password):
                st.session_state["nsds_admin_authenticated"] = True
                st.rerun()
            else:
                st.error("รหัสผ่านไม่ถูกต้อง กรุณาลองอีกครั้ง")
        st.info("Dashboard และหน้าวิเคราะห์ยังเปิดให้ทุกคนเข้าดูได้ โดยไม่ต้องเข้าสู่ระบบ")
        st.stop()

    top_left, top_right = st.columns([5, 1])
    with top_left:
        st.success("เข้าสู่ระบบผู้ดูแลแล้ว")
    with top_right:
        if st.button("ออกจากระบบ", use_container_width=True):
            st.session_state["nsds_admin_authenticated"] = False
            st.rerun()

    st.caption("ประเมินครบทั้ง 6 โรค และแจ้งเฉพาะโรคที่เข้าเกณฑ์ WATCH หรือ ALERT")
    month=st.selectbox("เดือนที่ต้องการประเมิน",range(1,13),index=9,format_func=lambda m:MONTHS[m-1])
    results=[eval_disease(region,d,month) for d in DISEASES]
    flagged=[x for x in results if x["status"] in ("WATCH","ALERT")]
    alert_n=sum(x["status"]=="ALERT" for x in flagged); watch_n=sum(x["status"]=="WATCH" for x in flagged)
    a,b,c=st.columns(3); a.metric("โรคเข้าเกณฑ์",f"{len(flagged)} / 6"); b.metric("ALERT",alert_n); c.metric("WATCH",watch_n)
    table=pd.DataFrame([{"โรค":x["disease"],"ผู้ป่วยจำลอง":x["cases"],"Baseline เฉลี่ย 5 ปี":round(x["baseline"],1) if x["baseline"] is not None else "—","เทียบ Baseline":f"{x['ratio']:.2f} เท่า" if x["ratio"] is not None else "—","สถานะ":x["status"]} for x in results])
    st.dataframe(table,hide_index=True,use_container_width=True)
    url=secret("DASHBOARD_URL",DASH_URL)
    st.subheader("ตัวอย่างข้อความ LINE")
    st.code(message(region,month,results,"ผู้รับตัวอย่าง",url),language="text")

    st.subheader("กลุ่มผู้รับ")
    st.caption("เลือกส่งหลายกลุ่มพร้อมกันได้")
    l,r=st.columns(2)
    with l:
        send_epi=st.checkbox("เจ้าหน้าที่ระบาดวิทยา",value=True); send_ic=st.checkbox("ทีม IC",value=True)
    with r:
        send_exec=st.checkbox("ผู้บริหาร",value=True); send_hospital=st.checkbox("โรงพยาบาลในเขตที่เลือก",value=True)
    recipients=[]
    if send_epi: recipients += [("เจ้าหน้าที่ระบาดวิทยา",x) for x in role_ids("epidemiology")]
    if send_ic: recipients += [("ทีม IC",x) for x in role_ids("ic")]
    if send_exec: recipients += [("ผู้บริหาร",x) for x in role_ids("executives")]
    if send_hospital:
        eligible=hospitals[(hospitals.health_region==region)&hospitals.is_active.apply(active)&hospitals.consent_status.astype(str).str.lower().eq("approved")&hospitals.line_user_id.astype(str).str.strip().ne("")]
        recipients += [(str(row.hospital_name),str(row.line_user_id).strip()) for _,row in eligible.iterrows()]
    unique={}
    for label,target in recipients: unique.setdefault(target,[]).append(label)
    recipients=[(", ".join(labels),target) for target,labels in unique.items()]
    st.caption(f"ผู้รับที่ตั้งค่าไว้และผ่านเงื่อนไข: {len(recipients)}")
    token=secret("LINE_CHANNEL_ACCESS_TOKEN")
    if not flagged: st.info("เดือนนี้ไม่มีโรคเข้าเกณฑ์ WATCH หรือ ALERT")
    if not token: st.info("ยังไม่ได้ตั้ง LINE_CHANNEL_ACCESS_TOKEN ใน Streamlit Secrets จึงดู Preview ได้ แต่ยังส่งจริงไม่ได้")
    if flagged and not recipients: st.warning("ยังไม่มีผู้รับที่ตั้งค่า LINE User ID และผ่านเงื่อนไขความยินยอม")
    if st.button("ส่ง LINE แจ้งเตือน WATCH / ALERT",type="primary",disabled=not bool(token and recipients and flagged)):
        progress=st.progress(0); output=[]
        for i,(label,target) in enumerate(recipients,1):
            try:
                status_code,detail=send_line(token,target,message(region,month,results,label,url))
                status="ส่งสำเร็จ" if status_code==200 else "ส่งไม่สำเร็จ"
            except Exception as exc:
                status_code,detail,status=0,str(exc)[:300],"ส่งไม่สำเร็จ"
            log_delivery(region,month,label,status,f"HTTP {status_code}: {detail}")
            output.append({"ผู้รับ":label,"สถานะ":status,"HTTP":status_code,"รายละเอียด":detail})
            progress.progress(i/len(recipients))
        st.dataframe(pd.DataFrame(output),hide_index=True,use_container_width=True)
        if all(x["สถานะ"]=="ส่งสำเร็จ" for x in output): st.success(f"ส่ง LINE สำเร็จ {len(output)} รายการ")
        else: st.warning("ส่งเสร็จแล้ว โปรดตรวจสอบสถานะรายผู้รับ")
    st.divider(); st.subheader("ประวัติการส่งแจ้งเตือน")
    logs=read_log()
    if logs.empty: st.info("ยังไม่มีประวัติการส่ง")
    else: st.dataframe(logs,hide_index=True,use_container_width=True)
    with st.expander("วิธีตั้งค่า LINE"):
        st.markdown("""
เพิ่มใน Streamlit App → Settings → Secrets

```toml
NSDS_ADMIN_PASSWORD = "ตั้งรหัสผ่านผู้ดูแลที่คาดเดายาก"
LINE_CHANNEL_ACCESS_TOKEN = "YOUR_CHANNEL_ACCESS_TOKEN"
DASHBOARD_URL = "https://your-dashboard.streamlit.app/"

[LINE_RECIPIENTS]
epidemiology = ["Uxxxxxxxx"]
ic = ["Uxxxxxxxx"]
executives = ["Uxxxxxxxx"]
```

โรงพยาบาล: กรอก LINE User ID ใน `data/hospital_registry.csv` และตั้ง `consent_status` เป็น `approved` หลังได้รับความยินยอมแล้ว ผู้รับต้องเพิ่ม LINE OA เป็นเพื่อนหรือเชิญ OA เข้ากลุ่มก่อน
""")

st.divider()
st.caption("NSDS Dashboard V2 Prototype · Synthetic data only · WATCH/ALERT thresholds are demo settings, not official DDC criteria.")
