"""
login.py
Functions for User Login/Logout handling
"""
import requests
import getpass
from urllib.parse import urljoin

def coceso_login(url, user, pw):
    """
    Logs into CoCeSo and returns the JSESSIONID string.
    """
    # Ensure the URL doesn't have a trailing slash for clean path joining
    base_url = url.rstrip('/')
    login_endpoint = f"{base_url}/client/login"

    # The server expects form-urlencoded data
    payload = {
        'username': user,
        'password': pw
    }

    try:
        # Send the POST request
        response = requests.post(login_endpoint, data=payload)
        
        # Raise an error if the server returns 4xx or 5xx
        response.raise_for_status()
        
        # Parse the JSON response
        data = response.json()
        
        if data.get('success'):
            # The /client/login endpoint returns the session ID in the 'properties' object
            session_id = data.get('properties', {}).get('JSESSIONID')
            
            # Fallback: If not in JSON, grab it from the standard cookies
            if not session_id:
                session_id = response.cookies.get('JSESSIONID')
                
            return session_id
        else:
            print("Login failed: Credentials rejected by server.")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}")
        return None

def select_open_concern(url: str, JSessionID: str, *, timeout: int = 15) -> tuple[int, dict]:
    """
    Selects the first open concern (closed == False) and returns:
      (concern_id, cookies_dict)

    cookies_dict includes BOTH:
      - "JSESSIONID": ...
      - "concern": <id as str>
    """
    concerns = get_concerns(url, JSessionID, timeout=timeout)
    open_concerns = [c for c in concerns if isinstance(c, dict) and c.get("closed") is False]
    if not open_concerns:
        raise RuntimeError("No open concerns found (closed == false).")

    chosen = open_concerns[0]
    concern_id = chosen.get("id")
    if not isinstance(concern_id, int):
        raise RuntimeError(f"Concern has no valid integer id: {chosen}")

    cookies = set_active_concern(url, JSessionID, concern_id, timeout=timeout)
    return concern_id, cookies


def get_concerns(url: str, JSessionID: str, *, timeout: int = 15) -> list[dict]:
    """Returns all concerns visible to the logged-in user."""
    base = url.rstrip("/") + "/"
    s = requests.Session()
    s.cookies.set("JSESSIONID", JSessionID)

    list_url = urljoin(base, "data/concern/getAll")
    r = s.get(list_url, timeout=timeout)
    r.raise_for_status()
    concerns = r.json()
    if not isinstance(concerns, list):
        raise RuntimeError(f"Unexpected response from {list_url}: {type(concerns)}")
    return [c for c in concerns if isinstance(c, dict)]


def set_active_concern(url: str, JSessionID: str, concern_id: int, *, timeout: int = 15) -> dict:
    """Sets the active concern and returns cookies to use for subsequent requests."""
    base = url.rstrip("/") + "/"
    s = requests.Session()
    s.cookies.set("JSESSIONID", JSessionID)

    set_url = urljoin(base, "data/setActiveConcern")
    r2 = s.post(set_url, params={"concern_id": concern_id}, timeout=timeout)
    r2.raise_for_status()

    # CoCeSo uses a 'concern' cookie for the active concern
    s.cookies.set("concern", str(concern_id))
    return {"JSESSIONID": JSessionID, "concern": str(concern_id)}


def select_concern_interactive(url: str, JSessionID: str, *, timeout: int = 15) -> tuple[int, dict]:
    """Interactive concern picker; returns (concern_id, cookies)."""
    concerns = get_concerns(url, JSessionID, timeout=timeout)
    if not concerns:
        raise RuntimeError("No concerns returned by server.")

    # Show open concerns first
    open_concerns = [c for c in concerns if c.get("closed") is False]
    closed_concerns = [c for c in concerns if c.get("closed") is True]
    ordered = open_concerns + closed_concerns

    print("Available concerns:")
    for idx, c in enumerate(ordered, start=1):
        cid = c.get("id")
        name = c.get("name") or "(no name)"
        closed = c.get("closed")
        state = "closed" if closed else "open"
        print(f"  {idx}. [{state}] {name} (id={cid})")

    raw = input("Select concern number (default 1): ").strip()
    choice = 1 if raw == "" else int(raw)
    if choice < 1 or choice > len(ordered):
        raise ValueError("Invalid concern selection.")

    chosen = ordered[choice - 1]
    concern_id = chosen.get("id")
    if not isinstance(concern_id, int):
        raise RuntimeError(f"Selected concern has no valid integer id: {chosen}")

    cookies = set_active_concern(url, JSessionID, concern_id, timeout=timeout)
    return concern_id, cookies


def __main__():
    server = input("Server (with https://): ").strip()
    if not server.startswith("http"):
        raise ValueError("Please include https:// in the server URL")

    user = input("Username: ").strip()
    passw = getpass.getpass("Password: ")

    print(f"Attempting to login to {server} as user '{user}'...")
    jsessionid = coceso_login(server, user, passw)
    if not jsessionid:
        print("Login failed.")
        return

    print("Login successful. JSESSIONID obtained:")
    print(jsessionid)

    print("Selecting an open concern (closed == false)...")
    try:
        concern_id, cookies = select_open_concern(server, jsessionid)
    except Exception as e:
        print(f"Concern selection failed: {e}")
        return

    print(f"Selected concern id: {concern_id}")
    print("Cookies to use for further requests:")
    print(cookies)

if __name__ == "__main__":
    __main__()