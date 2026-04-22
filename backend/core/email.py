import aiosmtplib
from email.message import EmailMessage
from core.config import get_settings

settings = get_settings()

async def send_otp_email(to_email: str, otp: str):
    """
    Send a verification code to the user's email via SMTP.
    """
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message["Subject"] = "Verify your Contract RFI Account"
    
    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                <h2 style="color: #00bcd4;">Verify your email</h2>
                <p>Hello,</p>
                <p>Thank you for signing up for Contract RFI. Please use the following 6-digit code to verify your email address:</p>
                <div style="background: #f4f4f4; padding: 15px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 5px; border-radius: 5px; margin: 20px 0;">
                    {otp}
                </div>
                <p>This code will expire shortly. If you did not request this code, please ignore this email.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="font-size: 12px; color: #888;">Contract RFI — Legal AI Platform</p>
            </div>
        </body>
    </html>
    """
    message.add_alternative(html_content, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            start_tls=settings.SMTP_TLS,
        )
        print(f"✅ OTP Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send OTP Email to {to_email}: {str(e)}")
        return False
