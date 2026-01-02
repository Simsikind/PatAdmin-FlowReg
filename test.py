"""test.py

Simple CLI test runner.

Credential format (login_credentials.txt):
Line 1: URL
Line 2: Username

Password is prompted at runtime and is never stored.
"""

from __future__ import annotations

import getpass
import os

import login
import Patadmin_communication as PatAdmin
from Patient import Patient


def load_server_and_username(filepath: str) -> tuple[str, str]:
    """Reads server URL and username from a text file."""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.read().splitlines() if line.strip()]

    if len(lines) < 2:
        raise ValueError("Credentials file must have at least 2 lines: URL, username")

    return lines[0], lines[1]

def main():
    creds_file = 'login_credentials.txt'
    
    if not os.path.exists(creds_file):
        print(f"Error: '{creds_file}' not found. Please create it with URL and username on separate lines.")
        return

    try:
        url, user = load_server_and_username(creds_file)
    except Exception as e:
        print(f"Error loading credentials: {e}")
        return

    password = getpass.getpass("Password: ")
    if not password:
        print("Error: Password is required.")
        return

    print(f"Attempting to login to {url} as user '{user}'...")
    session_id = login.coceso_login(url, user, password)

    if not session_id:
        print("Login failed. Please check your credentials and network connection.")
        return

    print("Login successful. Session ID obtained.")

    print("Selecting concern...")
    try:
        concern_id, cookies = login.select_concern_interactive(url, session_id)
    except Exception as e:
        print(f"Concern selection failed: {e}")
        return

    print(f"Selected concern id: {concern_id}")

    # Resolve group name (call sign) for nicer printing/labels
    group_id = 229
    try:
        group_name = PatAdmin.get_group_name_by_id(url, cookies, group_id)
    except Exception as e:
        print(f"Warning: Could not resolve group name for group_id={group_id}: {e}")
        group_name = None

    if group_name:
        print(f"Using group: {group_name} (id={group_id})")
    else:
        print(f"Using group id: {group_id}")

    # Fetch group capacity (may be None if unlimited/unknown)
    try:
        capacity = PatAdmin.get_group_capacity(url, cookies, group_id)
        if capacity is None:
            print("Group capacity: (not set)")
        else:
            print(f"Group capacity: {capacity}")
    except Exception as e:
        print(f"Warning: Could not fetch group capacity for group_id={group_id}: {e}")
        capacity = None

    # Count active (not done) patients currently in the group
    try:
        before_count = PatAdmin.get_patient_count_in_group(url, cookies, group_id)
        print(f"Active patients in group before registration: {before_count}")
        if capacity is not None:
            print(f"Occupancy before registration: {before_count}/{capacity}")
    except Exception as e:
        print(f"Warning: Could not fetch patient count for group_id={group_id}: {e}")
        before_count = None

    # Create a test patient
    # Note: group_id=1 is a placeholder. You may need to change this to a valid group ID in your system.
    try:
        test_patient = Patient(
            firstname="Max",
            lastname="Mustermann",
            group_id=group_id,
            group_name=group_name or "",
            external_id="ABC-12345",
            naca="I",
            sex="Male",
            info="Automated Test Patient",
            diagnosis="Test Diagnosis",
            insurance="1234010190",
            birthday="1990-01-01"
        )
    except ValueError as e:
        print(f"Error creating patient: {e}")
        return

    print("Registering patient...")
    payload = test_patient.to_payload()

    print(f"Debug: Sending payload: {payload}")
    
    # The register function handles the endpoint path
    result = PatAdmin.register(url, cookies, payload)

    if result['ok']:
        print("Registration successful!")
        if result.get('patient_id'):
            print(f"New Patient ID: {result.get('patient_id')}")
        if result.get('location'):
            print(f"Redirect Location: {result.get('location')}")

        # Count again after registration
        try:
            after_count = PatAdmin.get_patient_count_in_group(url, cookies, group_id)
            print(f"Active patients in group after registration: {after_count}")
            if capacity is not None:
                print(f"Occupancy after registration: {after_count}/{capacity}")
        except Exception as e:
            print(f"Warning: Could not fetch patient count after registration: {e}")
    else:
        print("Registration failed.")
        print(f"Status Code: {result.get('status')}")
        print(f"Response Body: {result.get('text')}")

if __name__ == "__main__":
    main()
