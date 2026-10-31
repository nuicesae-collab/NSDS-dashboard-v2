import os, hmac, hashlib, base64, json, logging
from fastapi import FastAPI, Request, HTTPException

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("nsds-webhook")
app=FastAPI(title="NSDS LINE Registration Webhook")

@app.get("/")
async def health():
    return {"service":"NSDS LINE webhook","status":"ok"}

@app.post("/callback")
async def callback(request:Request):
    body=await request.body()
    secret=os.getenv("LINE_CHANNEL_SECRET","")
    signature=request.headers.get("x-line-signature","")
    if not secret: raise HTTPException(500,"LINE_CHANNEL_SECRET is not configured")
    digest=hmac.new(secret.encode(),body,hashlib.sha256).digest()
    expected=base64.b64encode(digest).decode()
    if not hmac.compare_digest(signature,expected): raise HTTPException(401,"Invalid LINE signature")
    payload=json.loads(body.decode("utf-8"))
    for event in payload.get("events",[]):
        source=event.get("source",{})
        text_value=event.get("message",{}).get("text","")
        # User ID is written to service logs so the admin can register a consenting hospital device.
        log.info("NSDS_LINE_REGISTER source_type=%s user_id=%s group_id=%s text=%s",
                 source.get("type",""),source.get("userId",""),source.get("groupId",""),str(text_value)[:80])
    return {"ok":True}
