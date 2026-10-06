"""WhatsApp: chat with Hangul, and get reminders and the brief, on WhatsApp.

Meta's Cloud API, called only through the vault (the ``whatsapp`` provider, an
operator credential from WHATSAPP_ACCESS_TOKEN). ``client`` sends and
downloads, ``fmt`` turns Markdown answers into WhatsApp text, ``inbound``
reads and checks webhook deliveries, ``service`` runs them through the agent
and delivers notifications.
"""

from harness.config import get_settings


def enabled() -> bool:
    s = get_settings()
    return bool(s.whatsapp_access_token and s.whatsapp_phone_number_id)
