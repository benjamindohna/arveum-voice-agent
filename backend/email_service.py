"""Email-Service-Interface + Mock-Implementation.

In Phase A (Browser-MVP) triggert MockEmailService das Browser-Modal-Popup.
In Phase B kommt ResendEmailService dazu — gleiche Schnittstelle, anderes Backend."""

from abc import ABC, abstractmethod
from datetime import datetime


class EmailService(ABC):
    @abstractmethod
    async def send_upload_link(self, email: str, job_id: str, session, on_event) -> None:
        """Schickt dem Bewerber einen Link zum CV-Upload."""
        ...


class MockEmailService(EmailService):
    """Triggert das Browser-Modal-Popup statt echter Mail.

    Identisches UX wie der bisherige Browser-MVP — der Browser zeigt
    ein simuliertes Email-Fenster mit "Upload"-Button."""

    async def send_upload_link(self, email: str, job_id: str, session, on_event) -> None:
        await on_event({
            "type": "show_email_modal",
            "email": email,
            "job_id": job_id,
            "time": datetime.now().strftime("%H:%M"),
        })
        await on_event({
            "type": "log",
            "logtype": "sys",
            "message": f"Email-Popup angezeigt für {email}",
        })


# Phase B Stub:
# class ResendEmailService(EmailService):
#     def __init__(self, api_key: str, sender: str, base_url: str):
#         self.api_key = api_key
#         self.sender = sender
#         self.base_url = base_url
#
#     async def send_upload_link(self, email, job_id, session, on_event):
#         # Generate signed upload URL (S3 pre-signed o.ä.)
#         upload_url = f"{self.base_url}/upload/{generate_token(...)}"
#         # POST an Resend-API mit HTML-Email
#         ...
