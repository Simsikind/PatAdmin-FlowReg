"""
Patadmin_communication.py
Functions for interfacing with patadmin
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import requests


def _require_cookie(cookies: dict[str, str], name: str) -> None:
    value = cookies.get(name)
    if not value:
        raise ValueError(
            f"Missing required cookie '{name}'. "
            "Login must provide JSESSIONID and selecting a concern must provide 'concern'."
        )


def register(base_url: str, cookies: dict[str, str], payload: dict[str, Any], *, timeout: int = 15) -> dict[str, Any]:
    """Registers a patient via the PatAdmin web endpoint.

    New flow requirement:
    - Caller must provide cookies that include BOTH:
      - JSESSIONID (from login)
      - concern (from selecting an active concern)

    Returns a dict with:
      - ok: bool
      - status: int
      - patient_id: int|None (parsed from redirect Location)
      - location: str|None
      - text: str
    """

    base_url = base_url.rstrip("/") + "/"
    endpoint = urljoin(base_url, "patadmin/registration/save")

    cookies = dict(cookies or {})
    _require_cookie(cookies, "JSESSIONID")
    _require_cookie(cookies, "concern")

    # IMPORTANT: to get the new id from the redirect Location header,
    # ensure addNew is NOT set to 'true'
    payload = dict(payload or {})
    payload.pop("addNew", None)

    resp = requests.post(
        endpoint,
        data=payload,          # form-urlencoded
        cookies=cookies,
        allow_redirects=False,  # so we can read Location
        timeout=timeout,
    )

    location = resp.headers.get("Location")
    patient_id = None

    # CoCeSo typically responds 302 with Location like: /patadmin/registration?new=12345
    if location:
        m = re.search(r"(?:\?|&)(?:new|id)=(\d+)", location)
        if m:
            patient_id = int(m.group(1))

    ok = resp.status_code in (200, 302)

    return {
        "ok": ok,
        "status": resp.status_code,
        "patient_id": patient_id,
        "location": location,
        "text": resp.text,
    }