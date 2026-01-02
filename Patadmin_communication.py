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


def get_treatment_groups(base_url: str, cookies: dict[str, str]) -> list[dict[str, Any]]:
    """
    Fetches all available treatment groups for the active concern.
    Returns a list of group dictionaries (each having 'id', 'call', etc.).
    """
    base_url = base_url.rstrip("/") + "/"
    endpoint = urljoin(base_url, "data/patadmin/registration/groups")

    cookies = dict(cookies or {})
    _require_cookie(cookies, "JSESSIONID")
    _require_cookie(cookies, "concern")

    resp = requests.get(endpoint, cookies=cookies, timeout=15)
    resp.raise_for_status()
    
    data = resp.json()
    # The server returns a SequencedResponse wrapper, the actual list is in 'data'
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    # Fallback if structure is different
    return data


def get_group_name_by_id(base_url: str, cookies: dict[str, str], group_id: int) -> str | None:
    """
    Returns the name (call sign) of a treatment group given its ID.
    Returns None if not found.
    """
    try:
        groups = get_treatment_groups(base_url, cookies)
    except Exception:
        return None

    for group in groups:
        if not isinstance(group, dict):
            continue

        gid = group.get("id")
        if gid == group_id:
            # CoCeSo group objects typically include a call sign in 'call'
            name = group.get("call") or group.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
            return None

    return None


def get_group_capacity(base_url: str, cookies: dict[str, str], group_id: int) -> int | None:
    """Returns the maximum patient capacity for a treatment group.

    Returns None if the group is not found or if no capacity is set.
    """
    try:
        groups = get_treatment_groups(base_url, cookies)
    except Exception:
        return None

    for group in groups:
        if not isinstance(group, dict):
            continue
        if group.get("id") == group_id:
            cap = group.get("capacity")
            if cap is None or cap == "":
                return None
            try:
                return int(cap)
            except Exception:
                return None

    return None


def get_patient_count_in_group(
    base_url: str,
    cookies: dict[str, str],
    group_id: int,
    *,
    timeout: int = 15,
) -> int:
    """Returns the number of active (not done) patients in a treatment group.

    Uses the PatAdmin registration patients endpoint:
      GET data/patadmin/registration/patients?f=lastname&q=

    Note:
    - CoCeSo typically filters out "done" (discharged) patients server-side for this endpoint,
      so no extra filtering for active status is required here.
    - Response may be either a list[dict] OR a wrapper object with a "data" field.
    - The group id is in the JSON field "group".
    """

    base_url = base_url.rstrip("/") + "/"
    endpoint = urljoin(base_url, "data/patadmin/registration/patients")

    cookies = dict(cookies or {})
    _require_cookie(cookies, "JSESSIONID")
    _require_cookie(cookies, "concern")

    # Empty query matches all active patients (backend uses like keyword% and filters done=false).
    params = {"f": "lastname", "q": ""}

    resp = requests.get(endpoint, params=params, cookies=cookies, timeout=timeout)
    resp.raise_for_status()

    payload: Any = resp.json()
    patients: Any = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

    if not isinstance(patients, list):
        return 0

    return sum(1 for p in patients if isinstance(p, dict) and p.get("group") == group_id)


def get_patient_id_by_name(
    base_url: str,
    cookies: dict[str, str],
    name: str,
    *,
    timeout: int = 15,
) -> int | None:
    """
    Searches for a patient by name (lastname) and returns their ID.
    Returns the first matching patient's ID, or None if not found.
    """
    base_url = base_url.rstrip("/") + "/"
    endpoint = urljoin(base_url, "data/patadmin/registration/patients")

    cookies = dict(cookies or {})
    _require_cookie(cookies, "JSESSIONID")
    _require_cookie(cookies, "concern")

    # Search by lastname
    params = {"f": "lastname", "q": name}

    resp = requests.get(endpoint, params=params, cookies=cookies, timeout=timeout)
    resp.raise_for_status()

    payload: Any = resp.json()
    patients: Any = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

    if not isinstance(patients, list):
        return None

    found_ids = []
    for p in patients:
        if isinstance(p, dict):
            pid = p.get("id")
            if pid is not None:
                try:
                    found_ids.append(int(pid))
                except (ValueError, TypeError):
                    continue

    if found_ids:
        return max(found_ids)

    return None