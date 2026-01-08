"""
Patadmin_communication.py
Functions for interfacing with patadmin
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import requests

from Patient import Patient


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


def get_patient_details(
    base_url: str,
    cookies: dict[str, str],
    patient_id: int,
    *,
    timeout: int = 15
) -> dict[str, Any] | None:
    """
    Retrieves patient details by scraping the edit form at patadmin/treatment/edit/<id>.
    """
    base_url = base_url.rstrip("/") + "/"
    endpoint = urljoin(base_url, f"patadmin/treatment/edit/{patient_id}")

    cookies = dict(cookies or {})
    _require_cookie(cookies, "JSESSIONID")
    _require_cookie(cookies, "concern")

    resp = requests.get(endpoint, cookies=cookies, timeout=timeout)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    
    html = resp.text
    
    # Basic regex-based HTML parsing
    def get_input_value(name: str) -> str | None:
        # Matches <input ... name="name" ... value="value" ...>
        m = re.search(rf'<input[^>]*name="{re.escape(name)}"[^>]*value="([^"]*)"', html)
        if m: return m.group(1)
        return None

    def get_textarea_value(name: str) -> str | None:
        m = re.search(rf'<textarea[^>]*name="{re.escape(name)}"[^>]*>(.*?)</textarea>', html, re.DOTALL)
        return m.group(1) if m else None

    def get_select_value(name: str) -> str | None:
        # Find the select block
        m_select = re.search(rf'<select[^>]*name="{re.escape(name)}"[^>]*>(.*?)</select>', html, re.DOTALL)
        if not m_select:
            return None
        options = m_select.group(1)
        # Find selected option
        m_opt = re.search(r'<option[^>]*value="([^"]*)"[^>]*selected="selected"', options)
        if m_opt: return m_opt.group(1)
        m_opt = re.search(r'<option[^>]*selected="selected"[^>]*value="([^"]*)"', options)
        if m_opt: return m_opt.group(1)
        return None

    def get_radio_value(name: str) -> str | None:
        # Find input type=radio name=name checked="checked" value="..."
        m = re.search(rf'<input[^>]*name="{re.escape(name)}"[^>]*checked="checked"[^>]*value="([^"]*)"', html)
        if m: return m.group(1)
        
        m = re.search(rf'<input[^>]*name="{re.escape(name)}"[^>]*value="([^"]*)"[^>]*checked="checked"', html)
        if m: return m.group(1)
        return None

    data = {
        "id": patient_id,
        "lastname": get_input_value("lastname"),
        "firstname": get_input_value("firstname"),
        "externalId": get_input_value("externalId"),
        "insurance": get_input_value("insurance"),
        "birthday": get_input_value("birthday"),
        "sex": get_radio_value("sex"),
        "diagnosis": get_textarea_value("diagnosis"),
        "info": get_textarea_value("info"),
        "naca": get_select_value("naca"),
    }
    
    group_val = get_select_value("group")
    if group_val:
        try:
            data["group"] = int(group_val)
        except ValueError:
            data["group"] = None
    else:
        data["group"] = None

    return data


def edit_patient(
    base_url: str,
    cookies: dict[str, str],
    patient_id: int,
    payload: dict[str, Any],
    *,
    timeout: int = 15
) -> dict[str, Any]:
    """
    Edits an existing patient.
    
    Args:
        base_url: The base URL of the CoCeSo instance.
        cookies: Dictionary containing required cookies (JSESSIONID, concern).
        patient_id: The ID of the patient to update.
        patient_obj: The Patient object containing updated data.
        timeout: Request timeout in seconds.
        
    Returns:
        A dictionary with 'ok', 'status', and 'text'.
    """
    base_url = base_url.rstrip("/") + "/"
    endpoint = urljoin(base_url, "patadmin/registration/save")

    cookies = dict(cookies or {})
    _require_cookie(cookies, "JSESSIONID")
    _require_cookie(cookies, "concern")

    payload = dict(payload or {})
    
    # Add the patient ID to the payload so the server knows which patient to update
    payload["patient"] = patient_id
    
    # Ensure addNew is NOT set (it shouldn't be from to_payload(False), but just in case)
    payload.pop("addNew", None)

    resp = requests.post(
        endpoint,
        data=payload,          # form-urlencoded
        cookies=cookies,
        allow_redirects=False,  # We might get a redirect to view/edit page
        timeout=timeout,
    )

    # Successful update usually redirects (302) or returns 200
    ok = resp.status_code in (200, 302)

    return {
        "ok": ok,
        "status": resp.status_code,
        "text": resp.text,
    }

def request_transport(
    base_url: str,
    cookies: dict[str, str],
    patient_id: int,
    patient_obj: Patient,
    ertype: str,
    ambulance: str,
    priority: bool = False,
    *,
    timeout: int = 15
) -> dict[str, Any]:
    """
    Requests a transport for a patient.
    
    Args:
        base_url: The base URL of the CoCeSo instance.
        cookies: Dictionary containing required cookies (JSESSIONID, concern).
        patient_id: The ID of the patient.
        patient_obj: The Patient object containing patient data.
        ertype: The emergency type (e.g. "Intern", "Unfall").
        ambulance: The ambulance type (e.g. "KTW", "RTW", "BKTW", "NAW", "NEF", "RTW_C", "NAH").
        priority: Whether this is a priority transport.
        timeout: Request timeout in seconds.
        
    Returns:
        A dictionary with 'ok', 'status', and 'text'.
    """
    base_url = base_url.rstrip("/") + "/"
    endpoint = urljoin(base_url, "patadmin/treatment/transport")

    cookies = dict(cookies or {})
    _require_cookie(cookies, "JSESSIONID")
    _require_cookie(cookies, "concern")

    # Start with standard patient payload
    payload = patient_obj.to_payload(add_new_flow=False)
    
    # Remove 'group' as it is not part of TransportForm/PostprocessingForm
    # (though Spring might just ignore it if present)
    payload.pop("group", None)
    
    # Add transport specific fields
    payload["patient"] = patient_id
    payload["ertype"] = ertype
    payload["ambulance"] = ambulance
    # Spring MVC typically binds boolean from "true"/"false" strings or checkbox presence
    payload["priority"] = "true" if priority else "false"

    resp = requests.post(
        endpoint,
        data=payload,          # form-urlencoded
        cookies=cookies,
        allow_redirects=False,
        timeout=timeout,
    )

    ok = resp.status_code in (200, 302)

    return {
        "ok": ok,
        "status": resp.status_code,
        "text": resp.text,
    }
