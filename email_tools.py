"""
Email tools for agent_bot: send_email and read_emails via SMTP/IMAP.
Credentials read from EMAIL_ADDRESS and EMAIL_APP_PASSWORD env vars.
"""
import os, smtplib, imaplib, email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header

EMAIL_ADDRESS  = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
IMAP_HOST = "imap.gmail.com"


def tool_send_email(to: str, subject: str, body: str) -> str:
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        return "❌ EMAIL_ADDRESS або EMAIL_APP_PASSWORD не задані."
    try:
        msg = MIMEMultipart()
        msg["From"]    = EMAIL_ADDRESS
        msg["To"]      = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.starttls()
            s.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            s.sendmail(EMAIL_ADDRESS, to, msg.as_string())
        return f"✅ Лист надіслано на {to}."
    except Exception as e:
        return f"❌ Помилка надсилання: {e}"


def _decode_str(s) -> str:
    parts = decode_header(s or "")
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def tool_read_emails(folder: str = "INBOX", limit: int = 5) -> str:
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        return "❌ EMAIL_ADDRESS або EMAIL_APP_PASSWORD не задані."
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
            imap.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            imap.select(folder)
            _, data = imap.search(None, "ALL")
            ids = data[0].split()
            recent = ids[-limit:] if len(ids) >= limit else ids
            recent = list(reversed(recent))
            results = []
            for num in recent:
                _, msg_data = imap.fetch(num, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
                subj = _decode_str(msg["Subject"])
                frm  = _decode_str(msg["From"])
                date = msg["Date"]
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(
                                part.get_content_charset() or "utf-8", errors="replace")
                            break
                else:
                    body = msg.get_payload(decode=True).decode(
                        msg.get_content_charset() or "utf-8", errors="replace")
                results.append(
                    f"📧 Від: {frm}\nТема: {subj}\nДата: {date}\n{body[:500]}"
                )
            return "\n\n---\n\n".join(results) if results else "Папка порожня."
    except Exception as e:
        return f"❌ Помилка читання пошти: {e}"
