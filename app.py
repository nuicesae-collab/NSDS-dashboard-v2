from pathlib import Path
from datetime import datetime
import os, requests
import pandas as pd
import plotly.express as px
import streamlit as st
from generate_demo_data import DISEASES,AGE_GROUPS,MONTHS,SHORT_MONTHS,REGIONS,build

st.set_page_config(page_title="NSDS Dashboard V2",page_icon="🩺",layout="wide")
ROOT=Path(__file__).parent
DATA=ROOT/"data"
FILES={"hist":DATA/"historical_cases_2564_2568.csv","forecast":DATA/"forecast_2569.csv","sim":DATA/"simulation_2569.csv","threshold":DATA/"disease_thresholds.csv","hosp":DATA/"hospital_registry.csv"}
if not all(p.exists() for p in FILES.values()): build(DATA)
def load(key): return pd.read_csv(FILES[key],encoding="utf-8-sig")
hist,forecast,sim,thresholds,hosp=load("hist"),load("forecast"),load("sim"),load("threshold"),load("hosp")
for df in [hist,forecast,sim]:
    for c in ["year_be","month","cases"]: df[c]=df[c].astype(int)
regions=REGIONS
def config(d):
    return thresholds[thresholds.disease==d].iloc[0].to_dict()
def baseline(region,disease,month):
    x=hist[(hist.health_region==region)&(hist.disease==disease)&(hist.month==month)].groupby("year_be").cases.sum().reindex(range(2564,2569))
    return float(x.median()) if x.notna().sum()==5 else None
def evaluate(region,disease,month,override=None):
    cur=int(sim[(sim.health_region==region)&(sim.disease==disease)&(sim.month==month)].cases.sum())
    if override is not None: cur=int(override)
    base=baseline(region,disease,month); c=config(disease)
    ratio=(cur/base) if base and base>0 else None
    if base is None: status="ข้อมูลฐานไม่ครบ"
    elif base<=0:
        status="ALERT" if cur>=c["zero_alert_cases"] else "WATCH" if cur>=c["zero_watch_cases"] else "NORMAL"
    else: status="ALERT" if ratio>=c["alert_ratio"] else "WATCH" if ratio>=c["watch_ratio"] else "NORMAL"
    return {"โรค":disease,"เดือน":MONTHS[month-1],"ผู้ป่วยจำลอง 2569":cur,"มัธยฐาน 5 ปี":round(base) if base is not None else None,"เทียบฐาน (เท่า)":round(ratio,2) if ratio is not None else None,"สถานะ":status}
def line_push(token,uid,msg):
    r=requests.post("https://api.line.me/v2/bot/message/push",headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},json={"to":str(uid),"messages":[{"type":"text","text":msg[:5000]}]},timeout=20)
    return r.status_code,r.text[:300]
def msg(region,hospital,result):
    ratio=result["เทียบฐาน (เท่า)"]
    return (f"🚨 NSDS แจ้งเตือน ({result['สถานะ']})\nโรงพยาบาล: {hospital}\nเขตสุขภาพ: {region}\nโรค: {result['โรค']}\nเดือน: {result['เดือน']} 2569\nจำนวนผู้ป่วยจำลอง: {result['ผู้ป่วยจำลอง 2569']:,} ราย\nมัธยฐานย้อนหลัง 5 ปี: {result['มัธยฐาน 5 ปี']:,} ราย\nเทียบฐาน: {ratio if ratio is not None else 'คำนวณไม่ได้'}\nหมายเหตุ: ข้อความทดสอบจากข้อมูลสังเคราะห์ ไม่ใช่ประกาศเตือนภัยทางการ")
def secret(key):
    try: return st.secrets.get(key,"") or os.getenv(key,"")
    except Exception: return os.getenv(key,"")

st.markdown("<style>.block-container{padding-top:1.2rem}.stMetric{background:#f5f7fb;padding:12px;border-radius:12px;border:1px solid #e8edf5}</style>",unsafe_allow_html=True)
st.title("🩺 NSDS Dashboard V2")
st.caption("ระบบวิเคราะห์แนวโน้มและเฝ้าระวังโรคระดับเขตสุขภาพ")
st.warning("ชุดข้อมูลที่แนบเป็นข้อมูลสังเคราะห์เพื่อสาธิตเท่านั้น ไม่ใช่ข้อมูลผู้ป่วยจริงจากกรมควบคุมโรค")
st.session_state.setdefault("history",[])
with st.sidebar:
    page=st.radio("เมนู",["ภาพรวม","แนวโน้ม 5 ปีและคาดการณ์","อายุและเพศ","เกณฑ์ WATCH / ALERT","แจ้งเตือนโรงพยาบาล","ทะเบียนโรงพยาบาล","ข้อมูลและวิธีใช้"])
    region=st.selectbox("เขตสุขภาพ",regions,index=3)
    disease=st.selectbox("โรค",DISEASES)
if page=="ภาพรวม":
    st.header(f"ภาพรวมสถานการณ์ · {region}")
    res=pd.DataFrame([evaluate(region,d,10) for d in DISEASES])
    x=sim[(sim.health_region==region)]
    a,b,c,d=st.columns(4)
    a.metric("ผู้ป่วยจำลองปี 2569",f"{x.cases.sum():,} ราย")
    b.metric("ALERT",int((res.สถานะ=="ALERT").sum()))
    c.metric("WATCH",int((res.สถานะ=="WATCH").sum()))
    d.metric("โรคที่เฝ้าระวัง",len(DISEASES))
    st.dataframe(res,hide_index=True,use_container_width=True)
    st.subheader(f"แนวโน้มรายเดือน · {disease}")
    frames=[]
    for yr,g in hist[(hist.health_region==region)&(hist.disease==disease)].groupby("year_be"):
        q=g.groupby("month",as_index=False).cases.sum(); q["ชุดข้อมูล"]=str(yr); frames.append(q)
    for frame,label in [(forecast,"คาดการณ์ 2569"),(sim,"จำลอง 2569")]:
        q=frame[(frame.health_region==region)&(frame.disease==disease)].groupby("month",as_index=False).cases.sum(); q["ชุดข้อมูล"]=label; frames.append(q)
    chart=pd.concat(frames); chart["เดือน"]=chart.month.map(lambda m:SHORT_MONTHS[int(m)-1])
    fig=px.line(chart,x="เดือน",y="cases",color="ชุดข้อมูล",markers=True,labels={"cases":"ผู้ป่วย (ราย)"})
    st.plotly_chart(fig,use_container_width=True)
elif page=="แนวโน้ม 5 ปีและคาดการณ์":
    st.header("แนวโน้มย้อนหลัง 2564–2568 และคาดการณ์ 2569")
    frames=[]
    for yr,g in hist[(hist.health_region==region)&(hist.disease==disease)].groupby("year_be"):
        q=g.groupby("month",as_index=False).cases.sum(); q["ชุดข้อมูล"]=f"ข้อมูลจริงในชุดตัวอย่าง {yr}"; frames.append(q)
    for frame,label in [(forecast,"คาดการณ์ 2569"),(sim,"จำลอง 2569")]:
        q=frame[(frame.health_region==region)&(frame.disease==disease)].groupby("month",as_index=False).cases.sum(); q["ชุดข้อมูล"]=label; frames.append(q)
    chart=pd.concat(frames); chart["เดือน"]=chart.month.map(lambda m:SHORT_MONTHS[int(m)-1])
    st.plotly_chart(px.line(chart,x="เดือน",y="cases",color="ชุดข้อมูล",markers=True,labels={"cases":"ผู้ป่วย (ราย)"}),use_container_width=True)
    st.caption("คาดการณ์ด้วย linear regression จากข้อมูลเดือนเดียวกัน 5 ปี (2564–2568) เป็นวิธีสาธิต ยังไม่ได้ประเมินความแม่นยำ")
    table=hist[(hist.health_region==region)&(hist.disease==disease)].groupby(["year_be","month"],as_index=False).cases.sum().pivot(index="month",columns="year_be",values="cases").reindex(range(1,13))
    table.insert(0,"เดือน",[SHORT_MONTHS[i-1] for i in range(1,13)])
    st.dataframe(table,use_container_width=True)
elif page=="อายุและเพศ":
    st.header("วิเคราะห์จำแนกตามอายุและเพศ")
    source=st.radio("ชุดข้อมูล",["ย้อนหลัง 2564–2568","จำลอง 2569"],horizontal=True)
    frame=hist if source.startswith("ย้อนหลัง") else sim
    q=frame[(frame.health_region==region)&(frame.disease==disease)].groupby(["age_group","sex"],as_index=False).cases.sum()
    left,right=st.columns(2)
    age=q.groupby("age_group",as_index=False).cases.sum(); age["age_group"]=pd.Categorical(age.age_group,AGE_GROUPS,ordered=True); age=age.sort_values("age_group")
    left.plotly_chart(px.bar(age,x="age_group",y="cases",text_auto=True,title="ผู้ป่วยตามช่วงอายุ",labels={"age_group":"ช่วงอายุ","cases":"ราย"}),use_container_width=True)
    sex=q.groupby("sex",as_index=False).cases.sum()
    right.plotly_chart(px.pie(sex,names="sex",values="cases",hole=.4,title="สัดส่วนตามเพศ"),use_container_width=True)
    st.dataframe(q.pivot(index="age_group",columns="sex",values="cases").reindex(AGE_GROUPS),use_container_width=True)
    st.info("ช่วงอายุที่ใช้: 0–4, 5–14, 15–24, 25–44, 45–64 และ 65 ปีขึ้นไป เพื่อแยกเด็กเล็ก/วัยเรียน/วัยรุ่น/วัยทำงาน/ผู้สูงอายุและให้กราฟอ่านง่าย ทั้งนี้ไม่ใช่เกณฑ์ช่วงอายุเดียวที่ใช้กับทุกโรคใน DDC")
elif page=="เกณฑ์ WATCH / ALERT":
    st.header("เกณฑ์ WATCH / ALERT แยกตามโรค")
    show=thresholds.rename(columns={"disease":"โรค","watch_ratio":"WATCH ตั้งแต่ (เท่า)","alert_ratio":"ALERT ตั้งแต่ (เท่า)","rationale":"เหตุผลเบื้องต้น"})
    st.dataframe(show[["โรค","WATCH ตั้งแต่ (เท่า)","ALERT ตั้งแต่ (เท่า)","เหตุผลเบื้องต้น"]],hide_index=True,use_container_width=True)
    st.markdown("**วิธีคำนวณ:** ใช้มัธยฐานของเดือนเดียวกันย้อนหลัง 5 ปีเป็น baseline; ต่ำกว่า WATCH = NORMAL; ถึง WATCH = WATCH; ถึง ALERT = ALERT; หาก baseline เป็นศูนย์ ใช้จำนวนขั้นต่ำแยกโรค")
    st.warning("ตัวคูณเป็นค่าเริ่มต้นสำหรับทดสอบระบบ ไม่ใช่เกณฑ์มาตรฐานทางการของ DDC ต้องให้ผู้เชี่ยวชาญ/แนวทางเฉพาะโรครับรองก่อนใช้จริง")
elif page=="แจ้งเตือนโรงพยาบาล":
    st.header(f"การแจ้งเตือนโรงพยาบาล · {region}")
    month=st.selectbox("เดือนทดสอบ",range(1,13),index=6,format_func=lambda m:MONTHS[m-1])
    scenario=st.radio("สถานการณ์",["ใช้ข้อมูลจำลอง 2569","ทดสอบ NORMAL","ทดสอบ WATCH","ทดสอบ ALERT"],horizontal=True)
    base=baseline(region,disease,month); cfg=config(disease)
    override=None
    if scenario!="ใช้ข้อมูลจำลอง 2569" and base is not None:
        if scenario=="ทดสอบ NORMAL": override=int(base*max(.1,cfg["watch_ratio"]-.1))
        elif scenario=="ทดสอบ WATCH": override=int(base*(cfg["watch_ratio"]+cfg["alert_ratio"])/2)
        else: override=int(base*(cfg["alert_ratio"]+.2))
    result=evaluate(region,disease,month,override)
    st.subheader(f"สถานะ: {result['สถานะ']}")
    st.write(result)
    recipients=hosp[(hosp.health_region==region)&(hosp.is_active.astype(str).str.lower().isin(["true","1","yes"]))]
    st.subheader(f"ผู้รับใน {region}: {len(recipients)} โรงพยาบาล")
    st.dataframe(recipients[["hospital_id","hospital_name","consent_status"]],hide_index=True,use_container_width=True)
    with st.expander("ดูตัวอย่างข้อความแจ้งเตือน"):
        st.code(msg(region,"โรงพยาบาลปลายทาง",result))
    if st.button("จำลองส่งให้ทุกโรงพยาบาลในเขต",type="primary",disabled=recipients.empty):
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for _,h in recipients.iterrows():
            st.session_state.history.append({"เวลา":now,"เขต":region,"โรงพยาบาล":h.hospital_name,"โรค":disease,"สถานะ":result["สถานะ"],"ผล":"จำลองเท่านั้น"})
        st.success(f"จำลองกระจายข้อความให้ {len(recipients)} โรงพยาบาลในเขตนี้แล้ว ยังไม่ได้ส่ง LINE จริง")
    token=secret("LINE_CHANNEL_ACCESS_TOKEN")
    approved=recipients[(recipients.consent_status.astype(str).str.lower()=="approved")&recipients.line_user_id.fillna("").astype(str).str.strip().ne("")]
    confirm=st.checkbox("ยืนยันว่าผู้รับที่เลือกยินยอมรับข้อความ LINE")
    if st.button("ส่ง LINE จริงให้โรงพยาบาลที่อนุมัติ",disabled=(not token or approved.empty or not confirm or result["สถานะ"] not in ["WATCH","ALERT"])):
        sent=0
        for _,h in approved.iterrows():
            try:
                code,_=line_push(token,h.line_user_id,msg(region,h.hospital_name,result))
                sent+=int(code==200)
                st.session_state.history.append({"เวลา":datetime.now().isoformat(timespec="seconds"),"เขต":region,"โรงพยาบาล":h.hospital_name,"โรค":disease,"สถานะ":result["สถานะ"],"ผล":f"LINE API HTTP {code}"})
            except Exception as e:
                st.session_state.history.append({"เวลา":datetime.now().isoformat(timespec="seconds"),"เขต":region,"โรงพยาบาล":h.hospital_name,"โรค":disease,"สถานะ":result["สถานะ"],"ผล":str(e)[:120]})
        st.success(f"LINE API รับคำขอส่งสำเร็จ {sent}/{len(approved)} แห่ง")
    if not token: st.info("ยังไม่ตั้ง LINE_CHANNEL_ACCESS_TOKEN จึงทดลองโหมดจำลองได้")
    if st.session_state.history: st.dataframe(pd.DataFrame(st.session_state.history),hide_index=True,use_container_width=True)
elif page=="ทะเบียนโรงพยาบาล":
    st.header("ทะเบียนโรงพยาบาล")
    edited=st.data_editor(hosp,use_container_width=True,hide_index=True,num_rows="dynamic")
    st.download_button("ดาวน์โหลดทะเบียนที่แก้ไข",edited.to_csv(index=False).encode("utf-8-sig"),"hospital_registry.csv","text/csv")
    st.info("ใส่ LINE User ID ที่ได้จาก webhook ไม่ใช่ LINE ID สำหรับค้นหาเพื่อน และตั้ง consent_status เป็น approved เมื่อผู้รับยินยอมแล้ว")
else:
    st.header("ข้อมูลและวิธีใช้")
    st.markdown("""
**ขอบเขต:** 6 โรค · 13 เขตสุขภาพ · ข้อมูล 2564–2568 · คาดการณ์ 2569 · สถานการณ์จำลอง 2569

**ช่วงอายุที่แนะนำ**
- 0–4 ปี: แยกเด็กเล็ก ซึ่งสำคัญต่อมือเท้าปากและโรคติดเชื้อบางชนิด
- 5–14 ปี: วัยเรียน
- 15–24 ปี: วัยรุ่นและวัยผู้ใหญ่ตอนต้น
- 25–44 ปี: วัยทำงานตอนต้นถึงกลาง
- 45–64 ปี: วัยกลางคน/ก่อนสูงอายุ
- 65 ปีขึ้นไป: ผู้สูงอายุและกลุ่มเสี่ยงต่อโรครุนแรง

ช่วงอายุเป็นการจัดกลุ่มเพื่อการแสดงผล ไม่ใช่การยืนยันว่าเป็นมาตรฐาน DDC เดียวกันทุกโรค

**การคาดการณ์:** Linear regression จากเดือนเดียวกันใน 5 ปีย้อนหลัง แยกจากชุดข้อมูลจำลอง 2569

**การแจ้งเตือน:** เลือกเขตสุขภาพหนึ่งเขต ระบบจะส่งให้โรงพยาบาลที่ลงทะเบียนในเขตนั้นเป็นรายแห่ง โทรศัพท์แต่ละเครื่องแทนโรงพยาบาลหนึ่งแห่งได้ โดยต้องลงทะเบียน LINE User ID และได้รับความยินยอมก่อนส่งจริง

**ข้อจำกัด:** ข้อมูล CSV ที่ให้มาทั้งหมดเป็นข้อมูลสังเคราะห์เพื่อทดสอบระบบ ไม่ใช่ข้อมูลจริงจาก DDC ต้องนำข้อมูลจริงที่ตรวจสอบแหล่งที่มาแล้วมาแทนก่อนใช้เป็นรายงานสถานการณ์จริง
""")
    for key,label in [("hist","ย้อนหลัง 2564–2568"),("forecast","คาดการณ์ 2569"),("sim","จำลอง 2569"),("threshold","เกณฑ์รายโรค"),("hosp","ทะเบียนโรงพยาบาล")]:
        st.download_button(f"ดาวน์โหลด {label}",FILES[key].read_bytes(),FILES[key].name,"text/csv",key=key)
st.divider()
st.caption("NSDS V2 prototype · Synthetic data only · LINE push requires opt-in and valid LINE Messaging API credentials")
