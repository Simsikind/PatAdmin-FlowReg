# PatAdmin FlowReg

**PatAdmin FlowReg** is a streamlined, keyboard-centric desktop application for rapid patient registration during mass casualty incidents, large-scale events, or disaster relief operations. It interfaces with the **Coceso/PatAdmin** server backend to manage patient data and treatment capacities in real-time.

## Usecase

In high-pressure environments (e.g., triage tents, field hospitals), speed and accuracy are critical. Standard web interfaces can be slow and require extensive mouse usage. **PatAdmin FlowReg** solves this by providing:
- **Rapid Data Entry:** Optimized for keyboard-only operation.
- **Real-time Overview:** Live monitoring of treatment group capacities and patient counts.
- **Offline-First Design:** Robust handling of network latency (though a connection is required for data submission).
- **Instant Feedback:** Visual capacity indicators and Windows Toast notifications for successful registrations.
- **Physical Receipts:** Integration with ESC/POS thermal printers for printing patient wristbands or routing slips immediately upon registration.

## How to Use

1.  **Setup Server:** On first launch, press `Ctrl+Alt+S` (or use the menu **Setup > Server**) to enter your Coceso server URL (e.g., `https://aserver.example.org/coceso`).
2.  **Login:** Press `Ctrl+Alt+L` to log in with your credentials. You can choose to save your username for future sessions.
3.  **Select Concern:** Press `Ctrl+Alt+C` to select the active "Concern" (Operation/Event) you are working on.
4.  **Register Patients:**
    *   Press `Ctrl+N` to open the registration form.
    *   Fill in the details (Last Name, First Name, Treatment Group are required).
    *   Use `Tab` or `Arrow Keys` to navigate fields.
    *   Press `Enter` or `Ctrl+S` to save.
5.  **Monitor:** The main dashboard updates automatically (default: every 10s) to show the current occupancy of all treatment groups.

## Keyboard Shortcuts

The application is designed to be used almost entirely without a mouse.

### Global Hotkeys
| Shortcut | Action |
| :--- | :--- |
| `Ctrl` + `N` | **Register new Patient** (Opens the registration form) |
| `F11` | Toggle **Fullscreen** mode |
| `Ctrl` + `Alt` + `S` | Setup **Server** URL |
| `Ctrl` + `Alt` + `L` | **Login** |
| `Ctrl` + `Alt` + `C` | Select **Concern** |
| `Ctrl` + `Alt` + `D` | Show Connection **Details** |
| `Ctrl` + `Alt` + `T` | Open **Settings** |
| `Ctrl` + `Alt` + `P` | Toggle **Printing** (On/Off) |
| `Ctrl` + `Alt` + `R` | Toggle **Auto-Refresh** (On/Off) |

### Registration Form
| Shortcut | Action |
| :--- | :--- |
| `Tab` / `Shift`+`Tab` | Move focus between fields |
| `Up` / `Down` | Cycle through options in Dropdowns (Sex, Group, NACA) |
| `Enter` | **Save** and Close |
| `Ctrl` + `S` | **Save** and Close |
| `Esc` | **Cancel** and Close |

## How it Works

### Server Communication
The application acts as a thick client for the PatAdmin web API.
- It uses standard HTTP/HTTPS requests to communicate with the server.
- Authentication is handled via session cookies (`JSESSIONID`), which are managed automatically.
- Data fetching (patient counts, group capacities) is optimized to minimize server load, using a "visual refresh" vs. "data refresh" strategy.

### Locally Stored Data
The application stores minimal configuration data locally in the application directory:
- `login_credentials.txt`: Stores the Server URL and (optionally) the last used Username. **Passwords are never stored.**
- `app_settings.json`: Stores user preferences like Printer Name, Refresh Interval, Theme, and Fullscreen state.
- `themes/`: Contains generated JSON theme files (e.g., `red.json`, `violet.json`) created by the application's theming engine.

## How to Install

### Prerequisites
- **Python 3.10+**
- **Windows 10/11** (Required for Toast Notifications and Printer discovery)

### Installation
1.  Clone or download this repository.
2.  Install the required Python packages:
    ```bash
    pip install customtkinter requests tkcalendar pywin32
    ```
    *Note: `pywin32` is optional but recommended for better printer detection.*
3.  Run the application:
    ```bash
    python main.py
    ```

### Dependencies
- **CustomTkinter:** Modern UI framework based on Tkinter.
- **Requests:** HTTP library for API communication.
- **tkcalendar:** Date picker widget (falls back to text entry if missing).
- **pywin32:** Access to Windows print spooler API.
