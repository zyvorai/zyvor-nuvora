# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Optional SMTP notifications. Configure NUVORA_SMTP_HOST (+ port/user/password/from)."""
import os
import smtplib
from email.message import EmailMessage


def configured():
    return bool(os.getenv('NUVORA_SMTP_HOST', '').strip())


def send(to, subject, body, timeout=15):
    host = os.getenv('NUVORA_SMTP_HOST', '').strip()
    if not host or not to:
        return False
    port = int(os.getenv('NUVORA_SMTP_PORT', '587') or 587)
    user = os.getenv('NUVORA_SMTP_USER', '').strip()
    password = os.getenv('NUVORA_SMTP_PASSWORD', '')
    sender = os.getenv('NUVORA_SMTP_FROM', user or 'nuvora@localhost').strip()
    use_tls = os.getenv('NUVORA_SMTP_TLS', '1') != '0'
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = to
    msg['Subject'] = subject[:200]
    msg.set_content(body[:50000])
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as smtp:
                if use_tls:
                    smtp.starttls()
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        return True
    except Exception:
        return False
