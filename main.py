import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "mysecret123").strip()
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

SUPERADMIN_NUMBERS = {
    x.strip().replace("+", "")
    for x in os.getenv("SUPERADMIN_NUMBERS", "").split(",")
    if x.strip()
}

ALLOWED_NUMBERS = {
    x.strip().replace("+", "")
    for x in os.getenv("ALLOWED_NUMBERS", "").split(",")
    if x.strip()
}

GRAPH_API_VERSION = os.getenv("WHATSAPP_GRAPH_API_VERSION", "v18.0").strip()
APP_NAME = os.getenv("APP_NAME", "HR WhatsApp Bot").strip()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper().strip()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("whatsapp_hr_bot")

app = FastAPI(title=APP_NAME)


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing")
    return psycopg2.connect(DATABASE_URL)


def init_db() -> None:
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set. Database features will fail.")
        return

    sql_statements = [
        """
        CREATE TABLE IF NOT EXISTS inbound_messages (
            id SERIAL PRIMARY KEY,
            wa_message_id TEXT,
            from_number TEXT NOT NULL,
            contact_name TEXT,
            message_type TEXT,
            body TEXT,
            raw_payload JSONB,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS employees (
            id SERIAL PRIMARY KEY,
            employee_number TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT,
            department TEXT,
            position TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """,
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            for stmt in sql_statements:
                cur.execute(stmt)
        conn.commit()

    logger.info("Database initialized")


def save_inbound_message(
    wa_message_id: Optional[str],
    from_number: str,
    contact_name: Optional[str],
    message_type: Optional[str],
    body: Optional[str],
    raw_payload: Dict[str, Any],
) -> None:
    if not DATABASE_URL:
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inbound_messages
                (wa_message_id, from_number, contact_name, message_type, body, raw_payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    wa_message_id,
                    from_number,
                    contact_name,
                    message_type,
                    body,
                    json.dumps(raw_payload),
                ),
            )
        conn.commit()


def add_employee(
    employee_number: str,
    full_name: str,
    phone: str,
    department: str,
    position: str,
) -> str:
    if not DATABASE_URL:
        return "DATABASE_URL belum diset."

    employee_number = employee_number.strip().upper()
    full_name = full_name.strip()
    phone = phone.strip()
    department = department.strip()
    position = position.strip()

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id FROM employees WHERE employee_number = %s LIMIT 1",
                (employee_number,),
            )
            existing = cur.fetchone()
            if existing:
                return f"Employee number {employee_number} sudah wujud."

            cur.execute(
                """
                INSERT INTO employees (employee_number, full_name, phone, department, position)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (employee_number, full_name, phone, department, position),
            )
        conn.commit()

    return (
        "✅ Employee berjaya disimpan\n"
        f"Employee No: {employee_number}\n"
        f"Nama: {full_name}\n"
        f"Phone: {phone}\n"
        f"Department: {department}\n"
        f"Position: {position}"
    )


def list_employees(limit: int = 20) -> str:
    if not DATABASE_URL:
        return "DATABASE_URL belum diset."

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT employee_number, full_name, phone, department, position
                FROM employees
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    if not rows:
        return "Tiada employee dalam database."

    lines = ["📋 Senarai Employee"]
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"{idx}. {row['employee_number']} | {row['full_name']} | "
            f"{row.get('department') or '-'} | {row.get('position') or '-'}"
        )
    return "\n".join(lines)


def get_employee(employee_number: str) -> str:
    if not DATABASE_URL:
        return "DATABASE_URL belum diset."

    employee_number = employee_number.strip().upper()

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT employee_number, full_name, phone, department, position, created_at
                FROM employees
                WHERE employee_number = %s
                LIMIT 1
                """,
                (employee_number,),
            )
            row = cur.fetchone()

    if not row:
        return f"Employee {employee_number} tidak dijumpai."

    created_at = row["created_at"].strftime("%Y-%m-%d %H:%M") if row.get("created_at") else "-"
    return (
        "👤 Employee Detail\n"
        f"Employee No: {row['employee_number']}\n"
        f"Nama: {row['full_name']}\n"
        f"Phone: {row.get('phone') or '-'}\n"
        f"Department: {row.get('department') or '-'}\n"
        f"Position: {row.get('position') or '-'}\n"
        f"Dicipta: {created_at}"
    )


def normalize_number(number: str) -> str:
    return (number or "").strip().replace("+", "")


def is_allowed_number(number: str) -> bool:
    normalized = normalize_number(number)

    if normalized in SUPERADMIN_NUMBERS:
        return True

    if not ALLOWED_NUMBERS:
        return True

    return normalized in ALLOWED_NUMBERS


def is_superadmin(number: str) -> bool:
    return normalize_number(number) in SUPERADMIN_NUMBERS


def graph_api_url() -> str:
    return f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"


def send_whatsapp_text(to_number: str, message_text: str) -> None:
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.error("Missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID")
        return

    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_number(to_number),
        "type": "text",
        "text": {"body": message_text},
    }

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            graph_api_url(),
            headers=headers,
            json=payload,
            timeout=30,
        )
        logger.info("Send status=%s response=%s", response.status_code, response.text)
    except Exception as exc:
        logger.exception("Failed to send WhatsApp message: %s", exc)


def build_menu(is_admin: bool) -> str:
    base = [
        f"🤖 {APP_NAME}",
        "",
        "Arahan tersedia:",
        "1. menu",
        "2. ping",
        "3. whoami",
        "4. list employees",
        "5. employee EMP001",
    ]
    if is_admin:
        base.append("6. add employee|EMP001|Ali|60123456789|HR|Clerk")
    return "\n".join(base)


def handle_text_message(
    from_number: str,
    contact_name: Optional[str],
    text_body: str,
) -> str:
    text = (text_body or "").strip()
    lowered = text.lower()

    if not is_allowed_number(from_number):
        return "Nombor anda tidak dibenarkan menggunakan bot ini."

    admin = is_superadmin(from_number)

    if lowered in {"menu", "help", "mula", "start"}:
        return build_menu(admin)

    if lowered == "ping":
        return "pong ✅"

    if lowered == "whoami":
        return (
            "👤 Maklumat Anda\n"
            f"Nama: {contact_name or '-'}\n"
            f"Nombor: {from_number}\n"
            f"Superadmin: {'Ya' if admin else 'Tidak'}"
        )

    if lowered == "list employees":
        return list_employees()

    if lowered.startswith("employee "):
        employee_number = text[9:].strip()
        if not employee_number:
            return "Guna format: employee EMP001"
        return get_employee(employee_number)

    if lowered.startswith("add employee"):
        if not admin:
            return "Hanya superadmin boleh tambah employee."

        parts = text.split("|")
        if len(parts) != 6:
            return (
                "Format salah.\n"
                "Guna:\n"
                "add employee|EMP001|Ali|60123456789|HR|Clerk"
            )

        command_part = parts[0].strip().lower()
        if command_part != "add employee":
            return (
                "Format salah.\n"
                "Guna:\n"
                "add employee|EMP001|Ali|60123456789|HR|Clerk"
            )

        employee_number = parts[1].strip()
        full_name = parts[2].strip()
        phone = parts[3].strip()
        department = parts[4].strip()
        position = parts[5].strip()

        if not employee_number or not full_name:
            return "Employee number dan nama wajib diisi."

        return add_employee(employee_number, full_name, phone, department, position)

    return (
        f"Hai {contact_name or 'user'}.\n"
        "Arahan tidak dikenali.\n"
        "Taip 'menu' untuk lihat fungsi."
    )


def extract_messages(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    if payload.get("object") != "whatsapp_business_account":
        return results

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = value.get("contacts", []) or []
            messages = value.get("messages", []) or []

            contact_name = None
            if contacts:
                contact_name = contacts[0].get("profile", {}).get("name")

            for msg in messages:
                results.append(
                    {
                        "from_number": msg.get("from"),
                        "message_id": msg.get("id"),
                        "message_type": msg.get("type"),
                        "timestamp": msg.get("timestamp"),
                        "contact_name": contact_name,
                        "text_body": msg.get("text", {}).get("body", "") if msg.get("type") == "text" else None,
                        "raw_message": msg,
                    }
                )

    return results


@app.on_event("startup")
def startup_event():
    logger.info("Starting %s", APP_NAME)
    try:
        init_db()
    except Exception as exc:
        logger.exception("Database init failed: %s", exc)


@app.get("/")
async def root():
    return {"status": "running", "app": APP_NAME, "time": datetime.utcnow().isoformat()}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge or "")

    return PlainTextResponse("failed", status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    logger.info("Incoming webhook payload: %s", payload)

    try:
        parsed_messages = extract_messages(payload)

        if not parsed_messages:
            return JSONResponse({"ok": True, "message": "no user messages found"})

        for item in parsed_messages:
            from_number = item.get("from_number") or ""
            contact_name = item.get("contact_name")
            message_type = item.get("message_type")
            text_body = item.get("text_body")
            message_id = item.get("message_id")

            save_inbound_message(
                wa_message_id=message_id,
                from_number=from_number,
                contact_name=contact_name,
                message_type=message_type,
                body=text_body,
                raw_payload=payload,
            )

            if not from_number:
                continue

            if message_type == "text":
                reply = handle_text_message(from_number, contact_name, text_body or "")
                send_whatsapp_text(from_number, reply)
            elif message_type == "image":
                send_whatsapp_text(from_number, "Gambar diterima 👍")
            elif message_type == "document":
                send_whatsapp_text(from_number, "Dokumen diterima 📄")
            else:
                send_whatsapp_text(from_number, f"Mesej jenis '{message_type}' diterima.")

    except Exception as exc:
        logger.exception("Webhook processing failed: %s", exc)

    return JSONResponse({"ok": True})
