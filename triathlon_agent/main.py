import os
import json
import requests
from fastapi import FastAPI, Request
from telegram import Bot
from google import genai
from google.genai import types
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

# Initialize Gemini Client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = Bot(token=TELEGRAM_TOKEN)

# --- GOOGLE SHEETS DATABASE CONNECTOR ---
def log_to_google_sheet(log_type, content, metrics):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client_gs = gspread.authorize(creds)
        sheet = client_gs.open("Triathlon_Agent_Ledger").sheet1
        sheet.append_row([str(os.popen('date').read().strip()), log_type, content, metrics])
    except Exception as e:
        print(f"Sheet logging error: {e}")

# --- PROFESSIONAL SPORTS SCIENCE SYSTEM INSTRUCTION ---
SYSTEM_INSTRUCTION = """
You are an elite, multi-disciplinary sports science entourage for a professional triathlete. Your team consists of:
1. Head Triathlon Coach (Periodization, brick management, tapering, volume/intensity distribution).
2. Sports Physiotherapist & Biomechanist (Injury prevention, ACWR load safety, tendon/joint rehab).
3. Sports Nutritionist (Multimodal plate analysis, macro calculation, glycogen replenishment).
4. Exercise Physiologist (Heart rate zones, cardiac drift analysis, autonomic fatigue tracking).

CORE OPERATING PROTOCOLS:
1. HOLISTIC SYNTHESIS: Evaluate inputs against the athlete's training load and past history. Never analyze in isolation.
2. INJURY GUARDRAIL: Track localized pain scores (1-10). If pain on any tendon/joint is >= 4/10 or recurring, immediately veto high-impact work and mandate a structural modification (e.g., pool/trainer swap).
3. NUTRITIONIST MODE: When food photos are sent, estimate calories, protein, and carbs. Critique recovery gaps relative to training expenditure.
4. TAPER & PERIODIZATION: During tapers, cut volume 40-60% while maintaining short race-pace intervals. Manage phantom fatigue and prohibit unscheduled overtraining.
5. OUTPUT: Concise, structured, mobile-friendly. Always conclude with an exact directive of **WHAT TO EXECUTE TODAY**.
"""

@app.post(f"/webhook/{TELEGRAM_TOKEN}")
async def telegram_webhook(request: Request):
    data = await request.json()
    if "message" not in data:
        return {"status": "ok"}
    
    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    caption = message.get("caption", "")
    
    contents = []
    log_type = "GENERAL"
    metrics_summary = text or caption

    # Handle Photo / Meal Tracking
    if "photo" in message:
        log_type = "NUTRITION"
        file_id = message["photo"][-1]["file_id"]
        file_info_res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}").json()
        file_path = file_info_res["result"]["file_path"]
        photo_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        
        img_bytes = requests.get(photo_url).content
        contents.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
        contents.append(caption if caption else "Analyze this meal photo for macros and triathlon recovery gaps.")
    elif text:
        if any(w in text.lower() for w in ["pain", "hurt", "achilles", "knee"]):
            log_type = "PAIN_INJURY"
        elif any(w in text.lower() for w in ["swim", "bike", "run", "brick", "ride"]):
            log_type = "WORKOUT"
        contents.append(text)

    # Save row to Google Sheets
    log_to_google_sheet(log_type, text or caption or "Meal Photo", metrics_summary)

    # Generate Gemini Response
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.3,
            )
        )
        reply_text = response.text
    except Exception as e:
        reply_text = f"⚠️ Error processing request: {str(e)}"

    await bot.send_message(chat_id=chat_id, text=reply_text)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)