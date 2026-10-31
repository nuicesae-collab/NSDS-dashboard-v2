from pathlib import Path
import math, random
import numpy as np
import pandas as pd

DISEASES = ["โรคมือเท้าปาก","โรคไข้เลือดออก","โรคปอดบวม","โรคไข้หวัดใหญ่","โรคลมแดด","โรคอุจจาระร่วงเฉียบพลัน"]
AGE_GROUPS = ["0–4 ปี","5–14 ปี","15–24 ปี","25–44 ปี","45–64 ปี","65 ปีขึ้นไป"]
SEXES = ["ชาย","หญิง"]
MONTHS = ["มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน","กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"]
SHORT_MONTHS = ["ม.ค.","ก.พ.","มี.ค.","เม.ย.","พ.ค.","มิ.ย.","ก.ค.","ส.ค.","ก.ย.","ต.ค.","พ.ย.","ธ.ค."]
REGIONS = [f"เขตสุขภาพที่ {i}" for i in range(1,14)]

# ค่าเริ่มต้นเพื่อสาธิตเท่านั้น ไม่ใช่เกณฑ์ทางการของกรมควบคุมโรค
THRESHOLDS = [
 {"disease":"โรคมือเท้าปาก","watch_ratio":1.25,"alert_ratio":1.60,"zero_watch_cases":5,"zero_alert_cases":10,"rationale":"เน้นจับสัญญาณในเด็กและการเพิ่มขึ้นตามฤดูกาล"},
 {"disease":"โรคไข้เลือดออก","watch_ratio":1.20,"alert_ratio":1.50,"zero_watch_cases":3,"zero_alert_cases":6,"rationale":"ติดตามการเพิ่มขึ้นในฤดูฝนและการเปลี่ยนแปลงจากฐาน"},
 {"disease":"โรคปอดบวม","watch_ratio":1.15,"alert_ratio":1.35,"zero_watch_cases":10,"zero_alert_cases":20,"rationale":"จำนวนพื้นฐานมักสูง จึงใช้ตัวคูณที่ต่ำกว่าเพื่อจับการเพิ่มขึ้น"},
 {"disease":"โรคไข้หวัดใหญ่","watch_ratio":1.20,"alert_ratio":1.50,"zero_watch_cases":10,"zero_alert_cases":20,"rationale":"มีฤดูกาล จึงเปรียบเทียบเดือนเดียวกันของหลายปีย้อนหลัง"},
 {"disease":"โรคลมแดด","watch_ratio":1.50,"alert_ratio":2.00,"zero_watch_cases":2,"zero_alert_cases":4,"rationale":"จำนวนพื้นฐานอาจต่ำ อัตราส่วนจึงผันผวน ใช้ตัวคูณสูงและจำนวนขั้นต่ำ"},
 {"disease":"โรคอุจจาระร่วงเฉียบพลัน","watch_ratio":1.20,"alert_ratio":1.45,"zero_watch_cases":10,"zero_alert_cases":20,"rationale":"ติดตามการเพิ่มขึ้นจากระดับพื้นฐานรายเดือน"}
]
BASE = {"โรคมือเท้าปาก":70,"โรคไข้เลือดออก":90,"โรคปอดบวม":150,"โรคไข้หวัดใหญ่":175,"โรคลมแดด":12,"โรคอุจจาระร่วงเฉียบพลัน":165}
SEASON = {
"โรคมือเท้าปาก":[.82,.84,.90,.98,1.06,1.18,1.28,1.24,1.08,.98,.90,.84],
"โรคไข้เลือดออก":[.62,.68,.78,.94,1.08,1.24,1.40,1.36,1.20,1.00,.80,.68],
"โรคปอดบวม":[1.22,1.17,1.10,1.02,.96,.91,.90,.91,.96,1.02,1.12,1.20],
"โรคไข้หวัดใหญ่":[1.28,1.22,1.10,.96,.86,.81,.82,.87,.98,1.12,1.25,1.31],
"โรคลมแดด":[.22,.30,.65,1.28,1.48,1.32,.96,.72,.50,.32,.23,.20],
"โรคอุจจาระร่วงเฉียบพลัน":[.90,.91,.98,1.12,1.18,1.13,1.06,1.02,1.00,.98,.94,.91]
}
AGE_WEIGHTS = {
"โรคมือเท้าปาก":[.42,.46,.06,.035,.018,.007],
"โรคไข้เลือดออก":[.07,.22,.27,.25,.14,.05],
"โรคปอดบวม":[.15,.08,.07,.18,.22,.30],
"โรคไข้หวัดใหญ่":[.12,.25,.15,.18,.14,.16],
"โรคลมแดด":[.01,.03,.16,.35,.25,.20],
"โรคอุจจาระร่วงเฉียบพลัน":[.24,.16,.12,.18,.15,.15]
}
SEX_WEIGHTS = {"ชาย":.51,"หญิง":.49}

def allocate(total, weights):
    raw=[total*w for w in weights]
    vals=[math.floor(x) for x in raw]
    for i in sorted(range(len(raw)),key=lambda i:raw[i]-vals[i],reverse=True)[:total-sum(vals)]:
        vals[i]+=1
    return vals

def make_records(total,disease):
    result=[]
    for age,n in zip(AGE_GROUPS,allocate(total,AGE_WEIGHTS[disease])):
        male,female=allocate(n,[SEX_WEIGHTS["ชาย"],SEX_WEIGHTS["หญิง"]])
        result.extend([(age,"ชาย",male),(age,"หญิง",female)])
    return result

def build(out_dir):
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    rng=random.Random(2569)
    year_factor={2564:.88,2565:.93,2566:.98,2567:1.02,2568:1.06}
    region_factor={r:.72+i*.045 for i,r in enumerate(REGIONS)}
    hist=[]
    for year in range(2564,2569):
      for month in range(1,13):
       for disease in DISEASES:
        for region in REGIONS:
         total=max(0,round(BASE[disease]*SEASON[disease][month-1]*year_factor[year]*region_factor[region]*rng.uniform(.88,1.14)))
         for age,sex,cases in make_records(total,disease):
          hist.append(dict(year_be=year,month=month,month_name_th=MONTHS[month-1],disease=disease,health_region=region,age_group=age,sex=sex,cases=cases,data_status="synthetic_history",source_note="ข้อมูลสังเคราะห์ ไม่ใช่ข้อมูลจริงจาก DDC"))
    hist=pd.DataFrame(hist)
    # Linear extrapolation by same month, region, disease, age and sex
    forecasts=[]
    group_cols=["month","disease","health_region","age_group","sex"]
    for keys,g in hist.groupby(group_cols):
      g=g.sort_values("year_be")
      slope,intercept=np.polyfit(g.year_be.to_numpy(float),g.cases.to_numpy(float),1)
      month,disease,region,age,sex=keys
      forecasts.append(dict(year_be=2569,month=month,month_name_th=MONTHS[month-1],disease=disease,health_region=region,age_group=age,sex=sex,cases=max(0,int(round(slope*2569+intercept))),data_status="forecast_demo",source_note="คาดการณ์เชิงเส้นจากข้อมูลสังเคราะห์ 2564–2568"))
    forecast=pd.DataFrame(forecasts)
    sims=[]
    for row in forecast.to_dict("records"):
      d,reg,m=row["disease"],row["health_region"],int(row["month"])
      mult=rng.uniform(.92,1.10)
      if reg=="เขตสุขภาพที่ 6" and d=="โรคไข้เลือดออก" and m in (6,7,8): mult*=1.75
      if reg=="เขตสุขภาพที่ 13" and d=="โรคไข้หวัดใหญ่" and m in (8,9): mult*=1.70
      if reg=="เขตสุขภาพที่ 4" and d=="โรคมือเท้าปาก" and m in (7,8): mult*=1.85
      if reg=="เขตสุขภาพที่ 10" and d=="โรคลมแดด" and m in (4,5): mult*=2.20
      if reg=="เขตสุขภาพที่ 3" and d=="โรคอุจจาระร่วงเฉียบพลัน" and m in (5,6): mult*=1.65
      r=row.copy(); r["cases"]=max(0,int(round(int(row["cases"])*mult)))
      r["data_status"]="synthetic_simulation"; r["source_note"]="ข้อมูลจำลองปี 2569 สำหรับทดสอบสถานการณ์"
      sims.append(r)
    pd.DataFrame(hist).to_csv(out/"historical_cases_2564_2568.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(forecast).to_csv(out/"forecast_2569.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(sims).to_csv(out/"simulation_2569.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(THRESHOLDS).to_csv(out/"disease_thresholds.csv",index=False,encoding="utf-8-sig")
    hospitals=[]
    for i,region in enumerate(REGIONS,1):
      for letter in ["A","B","C"]:
       hospitals.append(dict(hospital_id=f"R{i:02d}-{letter}",hospital_name=f"โรงพยาบาลตัวอย่าง {letter} ({region})",health_region=region,line_user_id="",is_active=True,consent_status="demo"))
    pd.DataFrame(hospitals).to_csv(out/"hospital_registry.csv",index=False,encoding="utf-8-sig")
    return len(hist),len(forecast),len(sims),len(hospitals)

if __name__=="__main__":
    print("Generated:",build(Path(__file__).parent/"data"))
