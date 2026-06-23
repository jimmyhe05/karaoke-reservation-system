import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from config import Config

logger = logging.getLogger(__name__)

def _send_email(to_email, subject, body_text):
    """Internal helper to send an email using configured SMTP settings. Fires-and-forgets."""
    smtp_host = getattr(Config, "MAIL_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(getattr(Config, "MAIL_SMTP_PORT", 587))
    smtp_user = getattr(Config, "MAIL_SMTP_USER", "")
    smtp_pass = getattr(Config, "MAIL_SMTP_PASS", "")
    mail_from = getattr(Config, "MAIL_FROM", "") or smtp_user
    
    if not smtp_host or not smtp_user or not smtp_pass:
        logger.warning(
            f"SMTP not fully configured. Would have sent email to '{to_email}' with subject '{subject}'. "
            f"Body:\n{body_text}"
        )
        return False
        
    try:
        msg = MIMEMultipart()
        msg["From"] = mail_from
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain"))
        
        # Connect to SMTP server
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(mail_from, to_email, msg.as_string())
        server.quit()
        logger.info(f"Email successfully sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False

def send_request_received(res):
    """Notify customer that their reservation request is pending."""
    if not res.get("contact_email"):
        return
    subject = "Reservation Request Received - Pending Approval"
    body = (
        f"Hi {res['contact_name']},\n\n"
        f"Thank you for requesting a reservation at Nam's Noodle Karaoke!\n\n"
        f"Here are your request details:\n"
        f"- Date: {res['date']}\n"
        f"- Time: {res['start_time']} - {res['end_time']}\n"
        f"- Room: Room {res['room_id']}\n"
        f"- Guests: {res['num_people']}\n"
        f"- Total Estimated Cost: ${res['total_cost']:.2f}\n\n"
        f"Please note that your reservation is currently PENDING approval. "
        f"We will review your request and send a confirmation email once approved.\n\n"
        f"Best,\nNam's Noodle & Karaoke Team"
    )
    _send_email(res["contact_email"], subject, body)

def send_staff_notification(res):
    """Notify staff of a new pending reservation request."""
    staff_email = getattr(Config, "STAFF_NOTIFY_EMAIL", "")
    if not staff_email:
        return
    subject = "New Reservation Request Received"
    body = (
        f"Hello Staff,\n\n"
        f"A new customer reservation request has been submitted and is pending approval:\n\n"
        f"- Customer Name: {res['contact_name']}\n"
        f"- Phone: {res['contact_phone']}\n"
        f"- Email: {res['contact_email'] or 'Not provided'}\n"
        f"- Date: {res['date']}\n"
        f"- Time: {res['start_time']} - {res['end_time']}\n"
        f"- Room: Room {res['room_id']}\n"
        f"- Guests: {res['num_people']}\n\n"
        f"Please log into the staff dashboard to Approve or Decline this request.\n"
    )
    _send_email(staff_email, subject, body)

def send_confirmation(res):
    """Notify customer that their request is confirmed, providing a cancel link."""
    if not res.get("contact_email"):
        return
    base_url = getattr(Config, "BASE_URL", "http://localhost:5000")
    cancel_url = f"{base_url}/cancel/{res['cancellation_token']}"
    cutoff_hours = int(getattr(Config, "CANCEL_CUTOFF_HOURS", 2))
    
    subject = "Reservation Confirmed!"
    body = (
        f"Hi {res['contact_name']},\n\n"
        f"Great news! Your reservation request at Nam's Noodle Karaoke has been CONFIRMED!\n\n"
        f"Here are your reservation details:\n"
        f"- Date: {res['date']}\n"
        f"- Time: {res['start_time']} - {res['end_time']}\n"
        f"- Room: Room {res['room_id']}\n"
        f"- Guests: {res['num_people']}\n"
        f"- Total Cost: ${res['total_cost']:.2f}\n\n"
        f"If you need to cancel your reservation, you can do so up to {cutoff_hours} hours before the start time using this link:\n"
        f"{cancel_url}\n\n"
        f"We look forward to seeing you!\n\n"
        f"Best,\nNam's Noodle & Karaoke Team"
    )
    _send_email(res["contact_email"], subject, body)

def send_rejection(res, reason):
    """Notify customer that their request was declined."""
    if not res.get("contact_email"):
        return
    reason_str = reason or "No reason specified."
    subject = "Reservation Request Update"
    body = (
        f"Hi {res['contact_name']},\n\n"
        f"Thank you for requesting a reservation at Nam's Noodle Karaoke.\n\n"
        f"Unfortunately, we were unable to accept your reservation request for "
        f"Room {res['room_id']} on {res['date']} at {res['start_time']} - {res['end_time']}.\n\n"
        f"Reason for declining: {reason_str}\n\n"
        f"If you'd like to try booking a different date, room, or time, please feel free to submit a new request on our website.\n\n"
        f"Best,\nNam's Noodle & Karaoke Team"
    )
    _send_email(res["contact_email"], subject, body)

def send_cancellation_notice(res):
    """Notify staff that a customer has cancelled their reservation."""
    staff_email = getattr(Config, "STAFF_NOTIFY_EMAIL", "")
    if not staff_email:
        return
    subject = "Reservation Cancelled by Customer"
    body = (
        f"Hello Staff,\n\n"
        f"A confirmed reservation has been cancelled by the customer:\n\n"
        f"- Customer Name: {res['contact_name']}\n"
        f"- Phone: {res['contact_phone']}\n"
        f"- Email: {res['contact_email'] or 'Not provided'}\n"
        f"- Date: {res['date']}\n"
        f"- Time: {res['start_time']} - {res['end_time']}\n"
        f"- Room: Room {res['room_id']}\n"
        f"- Guests: {res['num_people']}\n"
        f"- Cancelled At: {res.get('updated_at') or 'Just now'}\n"
    )
    _send_email(staff_email, subject, body)
