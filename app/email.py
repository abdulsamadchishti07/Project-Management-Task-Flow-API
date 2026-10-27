import html
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import settings

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, html_content: str):
    """Sends an email using Gmail SMTP."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.default_from_email
        msg["To"] = to_email

        part = MIMEText(html_content, "html")
        msg.attach(part)

        with smtplib.SMTP(settings.email_smtp_server, settings.email_smtp_port) as server:
            server.starttls()
            server.login(settings.email_host_user, settings.email_host_password)
            server.sendmail(settings.default_from_email, to_email, msg.as_string())

        logger.info(f"Email successfully sent to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email} (Subject: '{subject}'): {e}", exc_info=True)


def send_otp_email(to_email: str, otp: str):
    """HTML template for Account Verification OTP."""
    safe_otp = html.escape(str(otp))
    subject = "Verify your TaskFlow Account - Verification Code"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; }}
            .container {{ max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 10px; padding: 30px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
            .header {{ text-align: center; margin-bottom: 25px; }}
            .header h1 {{ color: #2563eb; margin: 0; font-size: 24px; font-weight: 700; }}
            .content {{ color: #334155; line-height: 1.6; font-size: 15px; }}
            .otp-box {{ background: #f1f5f9; border: 2px dashed #94a3b8; border-radius: 8px; text-align: center; padding: 18px; margin: 25px 0; }}
            .otp-code {{ font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #1e293b; margin: 0; }}
            .footer {{ text-align: center; color: #94a3b8; font-size: 12px; margin-top: 30px; border-top: 1px solid #e2e8f0; padding-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>TaskFlow</h1>
            </div>
            <div class="content">
                <p>Hello,</p>
                <p>Thank you for signing up with TaskFlow! To complete your registration and activate your account, please enter the following 6-digit verification code:</p>
                
                <div class="otp-box">
                    <p class="otp-code">{safe_otp}</p>
                </div>

                <p>This code will expire in <strong>10 minutes</strong>. If you did not create an account on TaskFlow, you can safely ignore this email.</p>
            </div>
            <div class="footer">
                <p>&copy; TaskFlow API. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    send_email(to_email, subject, html_content)


def send_invitation_email(to_email: str, workspace_name: str, role: str, inviter_name: str):
    """HTML template for Workspace Invitation."""
    safe_ws_name = html.escape(str(workspace_name))
    safe_role = html.escape(str(role))
    safe_inviter = html.escape(str(inviter_name))
    subject = f"You've been invited to join '{safe_ws_name}' on TaskFlow"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; }}
            .container {{ max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 10px; padding: 30px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
            .header {{ text-align: center; margin-bottom: 25px; }}
            .header h1 {{ color: #2563eb; margin: 0; font-size: 24px; font-weight: 700; }}
            .content {{ color: #334155; line-height: 1.6; font-size: 15px; }}
            .highlight-box {{ background: #eff6ff; border-left: 4px solid #3b82f6; border-radius: 4px; padding: 15px; margin: 20px 0; }}
            .footer {{ text-align: center; color: #94a3b8; font-size: 12px; margin-top: 30px; border-top: 1px solid #e2e8f0; padding-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>TaskFlow</h1>
            </div>
            <div class="content">
                <p>Hello,</p>
                <p><strong>{safe_inviter}</strong> has invited you to collaborate on TaskFlow!</p>
                
                <div class="highlight-box">
                    <p style="margin: 0;"><strong>Workspace:</strong> {safe_ws_name}</p>
                    <p style="margin: 5px 0 0 0;"><strong>Assigned Role:</strong> {safe_role.capitalize()}</p>
                </div>

                <p>Log in to your TaskFlow account to accept this invitation and start working with your team.</p>
            </div>
            <div class="footer">
                <p>&copy; TaskFlow API. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    send_email(to_email, subject, html_content)
