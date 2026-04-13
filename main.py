import os
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse

app = FastAPI()

# =========================
# CONFIG
# =========================
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "mysecret123")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

# =========================
# ROOT CHECK
# =========================
@app.get("/")
async def root():
    return {"status": "running"}

# =========================
# WEBHOOK VERIFY (GET)
# =========================
@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge or "")

    return PlainTextResponse("failed", status_code=403)

# =========================
# SEND MESSAGE FUNCTION
# =========================
def send_whatsapp_message(to_number: str, message_text: str):
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        print("Missing ACCESS TOKEN or PHONE NUMBER ID")
        return

    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "body": message_text
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        print("Send status:", response.status_code)
        print("Response:", response.text)
    except Exception as e:
        print("Send error:", str(e))

# =========================
# WEBHOOK RECEIVE (POST)
# =========================
@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()
    print("Incoming:", data)

    try:
        if data.get("object") != "whatsapp_business_account":
            return JSONResponse({"ok": True})

        entries = data.get("entry", [])

        for entry in entries:
            changes = entry.get("changes", [])

            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])

                contact_name = None
                if contacts:
                    contact_name = contacts[0].get("profile", {}).get("name")

                for msg in messages:
                    from_number = msg.get("from")
                    msg_type = msg.get("type")

                    print("From:", from_number)
                    print("Type:", msg_type)

                    # =========================
                    # TEXT MESSAGE
                    # =========================
                    if msg_type == "text":
                        text_body = msg.get("text", {}).get("body", "")
                        print("Text:", text_body)

                        reply = f"Hai {contact_name or 'user'}, anda hantar: {text_body}"
                        send_whatsapp_message(from_number, reply)

                    # =========================
                    # IMAGE
                    # =========================
                    elif msg_type == "image":
                        print("Image received")
                        send_whatsapp_message(from_number, "Gambar diterima 👍")

                    # =========================
                    # DOCUMENT
                    # =========================
                    elif msg_type == "document":
                        print("Document received")
                        send_whatsapp_message(from_number, "Dokumen diterima 📄")

                    # =========================
                    # OTHER
                    # =========================
                    else:
                        print("Other type:", msg_type)
                        send_whatsapp_message(from_number, "Jenis mesej diterima.")

    except Exception as e:
        print("Error:", str(e))

    return JSONResponse({"ok": True})
