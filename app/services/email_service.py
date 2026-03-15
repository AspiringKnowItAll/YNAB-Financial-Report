"""
Async SMTP email delivery service.

Uses aiosmtplib with the user's own SMTP server — no hosted infrastructure.
TLS defaults to enabled. Credentials are passed in memory (never re-stored).

Implemented in Phase 8.
"""

from app.models.settings import AppSettings


async def send_report_email(
    settings: AppSettings,
    master_key: bytes,
    subject: str,
    html_body: str,
    pdf_attachment: bytes | None = None,
) -> None:
    """
    Deliver a report email via the user-configured SMTP server.

    Args:
        settings: AppSettings singleton (id=1); SMTP credentials decrypted here.
        master_key: From app.state.master_key — used to decrypt smtp_password_enc.
        subject: Email subject line.
        html_body: Rendered HTML report.
        pdf_attachment: Optional PDF bytes to attach.

    Raises:
        RuntimeError: If email_enabled is False or SMTP config is incomplete.
        aiosmtplib.SMTPException: On delivery failure.
    """
    raise NotImplementedError
