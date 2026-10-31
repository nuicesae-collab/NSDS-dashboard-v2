# NSDS Dashboard V2

## วิธีติดตั้ง
```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## อัปโหลด GitHub
อัปโหลดทั้งโฟลเดอร์และไฟล์ใน ZIP นี้เข้า Repository ใหม่ (แนะนำอย่าทับ Repository เดิม) โดยให้ `app.py` อยู่ที่ root แล้ว Deploy บน Streamlit Community Cloud โดยเลือก Main file path = `app.py`

## สิ่งที่มี
- ข้อมูลย้อนหลัง 5 ปี พ.ศ. 2564–2568
- คาดการณ์ 2569 แยกจากข้อมูลจำลอง 2569
- 6 โรค, 13 เขตสุขภาพ
- อายุ 6 กลุ่มและเพศ
- WATCH / ALERT แยกโรค
- ทดลองกระจายการแจ้งเตือนไปโรงพยาบาลทั้งหมดที่ลงทะเบียนในเขตที่เลือก
- LINE Messaging API สำหรับส่งจริงเมื่อมี token, LINE User ID และความยินยอม
- Webhook สำหรับรับ LINE User ID จาก LINE event

## ข้อสำคัญเกี่ยวกับข้อมูล
CSV ที่ให้มาเป็นข้อมูลสังเคราะห์ทั้งหมด เพื่อทดสอบการทำงานของแอปเท่านั้น ไม่ใช่ข้อมูลผู้ป่วยจริงหรือข้อมูลจากกรมควบคุมโรค ต้องแทนที่ `data/historical_cases_2564_2568.csv` ด้วยข้อมูลทางการที่ตรวจสอบแล้วก่อนใช้รายงานสถานการณ์จริง

## ช่วงอายุที่เลือก
0–4, 5–14, 15–24, 25–44, 45–64, 65 ปีขึ้นไป
เลือกเพื่อแยกเด็กเล็ก/วัยเรียน/วัยรุ่น/วัยทำงาน/ผู้สูงอายุ โดยยังคงจำนวนกลุ่มที่อ่านง่าย ไม่ใช่การอ้างว่าเป็นมาตรฐาน DDC เดียวกันทุกโรค

## เกณฑ์ WATCH / ALERT
เกณฑ์เริ่มต้นใน `data/disease_monthly_data_simulated.csv`? **ไม่ใช่** — เกณฑ์อยู่ใน `data/disease_thresholds.csv` และเป็นค่าเพื่อสาธิต ไม่ใช่เกณฑ์ทางการ ต้อง validate กับแนวทางเฉพาะโรคและผู้เชี่ยวชาญก่อนใช้จริง
ใช้ median ของเดือนเดียวกันย้อนหลัง 5 ปีเป็น baseline; หาก baseline เป็นศูนย์ใช้จำนวนขั้นต่ำเฉพาะโรค

## ตั้งค่า LINE จริง
1. สร้าง LINE Official Account และเปิด Messaging API ใน LINE Developers
2. Deploy `line_webhook.py` เป็น Web Service (เช่น Render) และตั้ง `LINE_CHANNEL_SECRET`
3. ตั้ง Webhook URL เป็น `https://<your-service>/callback` แล้วเปิด Use webhook
4. ให้โทรศัพท์ของโรงพยาบาลเพิ่ม OA เป็นเพื่อนและส่งข้อความหา OA
5. ดู `user_id` ใน service logs แล้วบันทึกลง `data/hospital_registry.csv` ในแถวโรงพยาบาลนั้น
6. เปลี่ยน `consent_status` เป็น `approved` เมื่อผู้รับยินยอม
7. ตั้ง Streamlit Secrets:
```toml
LINE_CHANNEL_ACCESS_TOKEN = "YOUR_CHANNEL_ACCESS_TOKEN"
```
8. ส่งทดสอบกับผู้รับที่ยินยอมเท่านั้น

LINE User ID ไม่ใช่ LINE ID สำหรับค้นหาเพื่อน และผู้รับต้องเพิ่ม OA เป็นเพื่อนก่อนจึงจะรับ Push message ได้ การที่ API รับคำขอสำเร็จไม่ยืนยันว่าอ่านแล้ว

## เกณฑ์เริ่มต้นที่ตั้งไว้
- มือเท้าปาก WATCH 1.25x / ALERT 1.60x
- ไข้เลือดออก WATCH 1.20x / ALERT 1.50x
- ปอดบวม WATCH 1.15x / ALERT 1.35x
- ไข้หวัดใหญ่ WATCH 1.20x / ALERT 1.50x
- ลมแดด WATCH 1.50x / ALERT 2.00x
- อุจจาระร่วง WATCH 1.20x / ALERT 1.45x

ทั้งหมดเป็นค่าทดลองเพื่อทดสอบ workflow เท่านั้น ห้ามอ้างเป็นเกณฑ์ DDC
