import asyncio
import os
import sys

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.email import send_otp_email
from core.config import get_settings

async def main():
    settings = get_settings()
    print("\n--- Current SMTP Configuration ---")
    print(f"Host: {settings.SMTP_HOST}")
    print(f"Port: {settings.SMTP_PORT}")
    print(f"User: {settings.SMTP_USERNAME}")
    masked_pw = settings.SMTP_PASSWORD[:3] + "..." + settings.SMTP_PASSWORD[-3:] if settings.SMTP_PASSWORD else "EMPTY"
    print(f"Pass: {masked_pw}")
    print(f"From: {settings.SMTP_FROM_EMAIL}")
    print("----------------------------------\n")

    recipient = input("Enter recipient email address for test: ").strip()
    if not recipient:
        print("Aborting: No recipient provided.")
        return

    print(f"Sending test OTP '123456' to {recipient}...")
    success = await send_otp_email(recipient, "123456")

    if success:
        print("\n✅ SUCCESS: Email sent! Please check your inbox (and spam).")
    else:
        print("\n❌ FAILED: Email could not be sent. Check the console output above for the specific error.")

if __name__ == "__main__":
    asyncio.run(main())
