import os
import logging
from threading import Thread

import requests

logger = logging.getLogger(__name__)

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_DEFAULT_LIST_ID = int(os.environ.get("BREVO_LIST_ID", "3"))
BREVO_CONTACTS_URL = "https://api.brevo.com/v3/contacts"


def _send_to_brevo(email: str, first_name: str, last_name: str, list_id: int) -> None:
    if not BREVO_API_KEY:
        logger.warning("BREVO_API_KEY not set; skipping Brevo sync for %s", email)
        return
    try:
        response = requests.post(
            BREVO_CONTACTS_URL,
            json={
                "email": email,
                "attributes": {
                    "FIRSTNAME": first_name,
                    "LASTNAME": last_name,
                },
                "listIds": [list_id],
                "updateEnabled": True,
            },
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "api-key": BREVO_API_KEY,
            },
            timeout=10,
        )
        if response.status_code in (201, 204):
            logger.info("Brevo: contact created/updated for %s", email)
        else:
            logger.error(
                "Brevo error %s for %s: %s",
                response.status_code,
                email,
                response.text,
            )
    except Exception as e:
        logger.error("Brevo request failed for %s: %s", email, e)


def add_contact_to_brevo(
    email: str,
    first_name: str = "",
    last_name: str = "",
    list_id: int | None = None,
) -> None:
    """Push a new user to Brevo in a background thread so signup is never blocked."""
    if not email:
        return
    Thread(
        target=_send_to_brevo,
        args=(
            email,
            first_name or "",
            last_name or "",
            list_id or BREVO_DEFAULT_LIST_ID,
        ),
        daemon=True,
    ).start()
