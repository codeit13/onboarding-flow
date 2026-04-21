import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("email-service")


class EmailService:
    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip().strip("'\"")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))
        self.username = os.getenv("SMTP_USERNAME", "").strip().strip("'\"")
        self.password = os.getenv("SMTP_PASSWORD", "").strip().strip("'\"")
        self.from_email = os.getenv("FROM_EMAIL", "").strip().strip("'\"")

    def send_selection_email(
        self,
        to_email: str,
        candidate_name: str,
        integrity_low: bool = False,
    ) -> bool:
        """
        Send a selection email asking the candidate to share their available slots.
        The Google Meet link is sent separately once the interviewer picks a slot.
        """
        subject = "Congratulations! You've Been Selected – Share Your Available Slots"

        if integrity_low:
            body = f"""Dear {candidate_name},

Thank you for attending the interview. We have reviewed your performance and are pleased to inform you that you have been shortlisted for the next stage.

Please stay on the results page and choose your preferred slot there directly. Once you submit it, the Google Meet link will be sent to your email automatically.

We look forward to hearing from you.

Best regards,
The Hiring Team"""
        else:
            body = f"""Dear {candidate_name},

Congratulations! We are pleased to inform you that you have been selected based on your interview performance.

Please stay on the results page and choose your preferred slot there directly. Once you submit it, the Google Meet link will be sent to your email automatically.

We look forward to connecting with you soon.

Best regards,
The Hiring Team"""

        return self._send_email(to_email, subject, body)

    def send_meet_link_email(
        self,
        to_email: str,
        candidate_name: str,
        meet_link: str,
        slot_display: str,
    ) -> bool:
        """Send the Google Meet link to the candidate once the slot is confirmed."""
        subject = "Your 2nd Round Interview is Scheduled – Google Meet Link Inside"

        body = f"""Dear {candidate_name},

Great news! Your 2nd round interview has been confirmed. Here are the details:

  Date & Time : {slot_display}
  Google Meet : {meet_link}

Please join the meeting using the link above at the scheduled time. A calendar invite has also been sent to your email address.

If you need to reschedule or have any questions, please reply to this email.

We look forward to speaking with you!

Best regards,
The Hiring Team"""

        return self._send_email(to_email, subject, body)

    def _send_email(self, to_email: str, subject: str, body: str) -> bool:
        """Send an email via SMTP. Returns True on success, False on failure."""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.from_email
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)

            logger.info(f"Selection email sent successfully to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False
