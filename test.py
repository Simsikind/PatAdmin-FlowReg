"""
test.py
"""

import login
import Patadmin_communication as PatAdmin
from Patient import Patient
import os

def load_credentials(filepath):
    """
    Reads the credentials from the specified text file.
    Expected format:
    Line 1: URL
    Line 2: Username
    Line 3: Password
    """
    with open(filepath, 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    
    if len(lines) < 3:
        raise ValueError("Credentials file must have at least 3 lines: URL, username, password")
    
    return lines[0], lines[1], lines[2]

def main():
    creds_file = 'login_credentials.txt'
    
    if not os.path.exists(creds_file):
        print(f"Error: '{creds_file}' not found. Please create it with URL, username, and password on separate lines.")
        return

    try:
        url, user, password = load_credentials(creds_file)
    except Exception as e:
        print(f"Error loading credentials: {e}")
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

    # Create a test patient
    # Note: group_id=1 is a placeholder. You may need to change this to a valid group ID in your system.
    try:
        test_patient = Patient(
            firstname="Max",
            lastname="Mustermann",
            group_id=229, 
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
    else:
        print("Registration failed.")
        print(f"Status Code: {result.get('status')}")
        print(f"Response Body: {result.get('text')}")

if __name__ == "__main__":
    main()
