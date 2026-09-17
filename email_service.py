import os
import smtplib
import ssl
from email.message import EmailMessage
from threading import Thread
from html import escape


BRAND = "StayFlow"
SUPPORT = os.getenv("MAIL_FROM", "")


def smtp_configured():
    return all([
        os.getenv("SMTP_HOST"),
        os.getenv("SMTP_PORT"),
        os.getenv("SMTP_USERNAME"),
        os.getenv("SMTP_APP_PASSWORD"),
        os.getenv("MAIL_FROM"),
    ])


def _send_email(to_email, subject, html_body, text_body):
    if not to_email or not smtp_configured():
        print(f"[EMAIL] Skipped: SMTP not configured or recipient missing ({to_email})")
        return False

    msg = EmailMessage()
    msg["From"] = os.getenv("MAIL_FROM")
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_APP_PASSWORD")
    context = ssl.create_default_context()

    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
            server.login(username, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=context)
            server.login(username, password)
            server.send_message(msg)

    return True


def send_email_async(to_email, subject, html_body, text_body):
    """Send a branded HTML email without blocking the Flask request."""
    if not to_email:
        return

    def worker():
        try:
            ok = _send_email(to_email, subject, html_body, text_body)
            if ok:
                print(f"[EMAIL] SUCCESS -> {to_email} | {subject}")
        except Exception as exc:
            print(f"[EMAIL] FAILED -> {to_email} | {exc}")

    Thread(target=worker, daemon=True).start()


def send_to_many(emails, subject, html_body, text_body):
    for email in dict.fromkeys(e for e in emails if e):
        send_email_async(email, subject, html_body, text_body)


def _layout(title, eyebrow, intro, content, footer_note="This is an automated StayFlow message."):
    return f"""<!doctype html>
<html><body style=\"margin:0;background:#f4f7fb;font-family:Arial,Helvetica,sans-serif;color:#172033;\">
<table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f4f7fb;padding:32px 12px;\"><tr><td align=\"center\">
<table width=\"640\" cellpadding=\"0\" cellspacing=\"0\" style=\"max-width:640px;background:#ffffff;border-radius:22px;overflow:hidden;box-shadow:0 12px 40px rgba(15,23,42,.10);\">
<tr><td style=\"background:linear-gradient(135deg,#1d4ed8,#2563eb);padding:28px 34px;color:#fff;\">
<div style=\"font-size:25px;font-weight:800;letter-spacing:-.5px;\">StayFlow</div>
<div style=\"margin-top:8px;font-size:13px;opacity:.85;\">Hotel stays, beautifully managed.</div></td></tr>
<tr><td style=\"padding:34px;\">
<div style=\"font-size:12px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;color:#2563eb;\">{escape(eyebrow)}</div>
<h1 style=\"font-size:30px;line-height:1.2;margin:9px 0 12px;color:#172033;\">{escape(title)}</h1>
<p style=\"font-size:16px;line-height:1.7;color:#64748b;margin:0 0 24px;\">{intro}</p>
{content}
</td></tr>
<tr><td style=\"padding:20px 34px;background:#f8fafc;border-top:1px solid #e5e7eb;color:#94a3b8;font-size:12px;line-height:1.6;\">{escape(footer_note)}<br>© StayFlow Hotel Booking</td></tr>
</table></td></tr></table></body></html>"""


def _details(rows):
    cells = "".join(f"<tr><td style='padding:9px 0;color:#64748b;width:42%;'>{escape(str(k))}</td><td style='padding:9px 0;font-weight:700;color:#172033;'>{escape(str(v))}</td></tr>" for k,v in rows)
    return f"<table width='100%' cellpadding='0' cellspacing='0' style='background:#f8fafc;border:1px solid #e5e7eb;border-radius:15px;padding:12px 18px;margin:18px 0 24px;'>{cells}</table>"


def booking_confirmation(to_email, guest_name, booking_id, hotel_name, room_number, check_in, check_out):
    content = _details([
        ("Booking ID", f"#{booking_id}"), ("Hotel", hotel_name), ("Room", room_number),
        ("Check-in", check_in), ("Check-out", check_out), ("Status", "Booked")
    ]) + "<p style='font-size:15px;line-height:1.7;color:#475569;'>Your room is reserved. We look forward to welcoming you. Please keep this email for your stay details.</p>"
    html = _layout("Your stay is confirmed 🎉", "Reservation confirmed", f"Hello <b>{escape(guest_name)}</b>, your StayFlow reservation has been successfully created.", content)
    send_email_async(to_email, f"StayFlow · Booking confirmed #{booking_id}", html, f"Hello {guest_name}, your booking #{booking_id} at {hotel_name}, room {room_number}, from {check_in} to {check_out} is confirmed.")


def new_booking_manager(to_email, manager_name, booking_id, guest_name, hotel_name, room_number, check_in, check_out):
    content = _details([
        ("Booking ID", f"#{booking_id}"), ("Guest", guest_name), ("Hotel", hotel_name),
        ("Room", room_number), ("Check-in", check_in), ("Check-out", check_out)
    ]) + "<p style='font-size:15px;color:#475569;'>A new reservation requires your attention in the manager dashboard.</p>"
    html = _layout("New reservation received", "Manager notification", f"Hello <b>{escape(manager_name)}</b>, a guest has made a new reservation.", content)
    send_email_async(to_email, f"StayFlow · New booking #{booking_id}", html, f"New booking #{booking_id} for {guest_name} at {hotel_name}, room {room_number}, {check_in} to {check_out}.")


def admin_event(to_email, admin_name, title, message, booking_id=None):
    extra = _details([("Booking ID", f"#{booking_id}")]) if booking_id else ""
    content = extra + f"<div style='background:#eff6ff;border-left:4px solid #2563eb;padding:15px 17px;border-radius:10px;color:#334155;line-height:1.7;'>{escape(message)}</div>"
    html = _layout(title, "Administrator notification", f"Hello <b>{escape(admin_name)}</b>, here is an activity update from StayFlow.", content)
    send_email_async(to_email, f"StayFlow · {title}", html, message)


def booking_status(to_email, guest_name, booking_id, status, hotel_name=None, room_number=None):
    rows = [("Booking ID", f"#{booking_id}"), ("Status", status)]
    if hotel_name: rows.insert(1, ("Hotel", hotel_name))
    if room_number: rows.insert(2, ("Room", room_number))
    content = _details(rows) + "<p style='font-size:15px;line-height:1.7;color:#475569;'>You can sign in to your StayFlow dashboard to view your latest reservation details.</p>"
    html = _layout("Your booking has been updated", "Booking update", f"Hello <b>{escape(guest_name)}</b>, your reservation status has changed.", content)
    send_email_async(to_email, f"StayFlow · Booking update #{booking_id}", html, f"Hello {guest_name}, booking #{booking_id} is now {status}.")


def cancellation_requested(to_email, guest_name, booking_id, hotel_name, reason=""):
    content = _details([("Booking ID", f"#{booking_id}"), ("Hotel", hotel_name), ("Request", "Cancellation review")])
    if reason:
        content += f"<p style='color:#475569;line-height:1.7;'><b>Guest reason:</b> {escape(reason)}</p>"
    html = _layout("Cancellation request received", "Cancellation", f"Hello <b>{escape(guest_name)}</b>, your cancellation request has been sent to the hotel manager for review.", content)
    send_email_async(to_email, f"StayFlow · Cancellation request #{booking_id}", html, f"Cancellation requested for booking #{booking_id} at {hotel_name}.")


def manager_cancellation_request(to_email, manager_name, booking_id, guest_name, hotel_name, reason=""):
    content = _details([("Booking ID", f"#{booking_id}"), ("Guest", guest_name), ("Hotel", hotel_name)])
    if reason:
        content += f"<p style='color:#475569;line-height:1.7;'><b>Guest reason:</b> {escape(reason)}</p>"
    html = _layout("Cancellation review required", "Manager action", f"Hello <b>{escape(manager_name)}</b>, a guest has requested cancellation of a reservation.", content)
    send_email_async(to_email, f"StayFlow · Cancellation review #{booking_id}", html, f"Cancellation review required for booking #{booking_id} by {guest_name} at {hotel_name}. Reason: {reason}")


def cancellation_decision(to_email, guest_name, booking_id, decision, note=""):
    approved = decision.lower() == "approved"
    label = "approved" if approved else "rejected"
    color_text = "Your cancellation request has been approved." if approved else "Your cancellation request was not approved."
    content = _details([("Booking ID", f"#{booking_id}"), ("Decision", decision)])
    if note:
        content += f"<p style='color:#475569;line-height:1.7;'><b>Manager note:</b> {escape(note)}</p>"
    html = _layout(f"Cancellation {label}", "Cancellation decision", f"Hello <b>{escape(guest_name)}</b>, {color_text}", content)
    send_email_async(to_email, f"StayFlow · Cancellation {label} #{booking_id}", html, f"Booking #{booking_id} cancellation was {label}. {note}")