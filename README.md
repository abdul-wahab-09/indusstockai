# ⚡ IndusStock AI
### Electrical and Electronic Spare Parts Intelligence

Smart inventory management and AI assistance for industrial electrical and electronic spare parts,
built for **Foils and Metals Mill-3**.

Track every contactor, drive, sensor, PLC module and bearing; get automatic low-stock alerts and reorder
suggestions; see consumption trends and stock-cover forecasts; and ask **ElectroBot** questions by text or
voice in **English, اردو (Urdu) and Roman Urdu**. Secure sign-in with roles and four ways to recover a
forgotten password or username.

---

## Features

| Area | What you get |
|---|---|
| **Sign-in & recovery** | Professional sign-in page, show/hide password, **forgot password / username** (e-mail code, recovery code, administrator request), lock-out, idle time-out |
| **Roles** | **Administrator** and **User**, user management, forced password change, audit trail |
| **Dashboard** | Greeting banner, KPI cards, stock-health ring chart, category and consumption bars, needs-attention list, activity timeline |
| **Spare part register** | Add, edit, archive, restore; duplicate part numbers blocked; **bulk import from Excel / CSV** with validation preview |
| **Inventory** | Multi-word search, filters, colour-coded status, **part detail card with history**, CSV / Excel export |
| **Stock In / Out** | Atomic updates, no negative stock, reference and operator on every movement |
| **Low-stock alerts** | Priority list with stock meters, suggested reorder quantities, export for purchase requisitions |
| **Analytics** | Trends, most-consumed parts, **days-of-cover forecast**, slow / idle stock |
| **ElectroBot AI** | Exact database answers, Gemini for engineering questions, chat memory, voice input, spoken answers |
| **Reports & backup** | Excel management report, database backup, audit log, system status, SMTP and Gemini tests |
| **Look & feel** | Modern dark theme (light mode available), responsive cards, consistent icons |

## Quick start

**Windows:** double-click `run_app.bat`.

**Any OS**
```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
Opens at http://localhost:8501. Python 3.10 or newer is required.

## Signing in

- **First start:** the app asks you to create the administrator account (default username suggestion: `admin`) and
  then shows a **one-time recovery code**. Save it.
- **Everyone else:** the administrator creates the account under **👥 User Management** and hands over a temporary
  password. The person must choose their own password at first sign-in.
- The password box has a built-in **show / hide (eye)** button.

### Forgot your password or username?
Click **Forgot password or username?** on the sign-in page. Choose one of:

| Method | How it works | Needs |
|---|---|---|
| 📧 **E-mail code** | A 6-digit code (valid 15 minutes, single use) is e-mailed to the address on your account | SMTP set up + e-mail saved in your account |
| 🔑 **Recovery code** | Enter your username and the one-time code you saved; a replacement code is shown right after | A saved recovery code |
| 🛡️ **Ask administrator** | Send a request; the administrator sees it under *Reset Requests* and issues a temporary password | Nothing |
| 🙋 **Forgot username** | E-mails your username to your registered address, or ask the administrator | SMTP, or the admin |

**Last resort (on the computer running the app, with the app stopped):** double-click `reset_password.bat` (Windows), or run:
```bash
python scripts/reset_admin_password.py --list        # shows all usernames
python scripts/reset_admin_password.py admin         # sets a new temporary password
```
Create a recovery code (and add an e-mail) in **My Account** so you never get locked out again.

### Roles

| Feature | Administrator | User |
|---|:---:|:---:|
| Dashboard, inventory, alerts, history, analytics, AI assistant | ✅ | ✅ |
| Add parts (single or bulk import), Stock In / Out | ✅ | ✅ |
| Edit, archive and restore parts | ✅ | ❌ |
| Reports, backup, audit log, system status, Gemini and SMTP setup | ✅ | ❌ |
| User management, reset requests, sign-in activity | ✅ | ❌ |
| My Account (e-mail, password, recovery code) | ✅ | ✅ |

### Security details
Passwords are stored only as salted PBKDF2-SHA256 hashes (600,000 rounds); recovery and e-mail codes are
stored hashed too. 8+ characters with a letter and a number are required. An account locks for 5 minutes after
5 wrong passwords, and each browser session is slowed down after 5 failures in a minute. Reset screens never
reveal whether an account exists. Sessions end after 30 idle minutes (`SESSION_TIMEOUT_MINUTES`). Role changes
and deactivation apply on the next click. The last active administrator cannot be removed. All user-supplied text is
HTML-escaped. Every sign-in, failure, lock-out, reset and account change goes to the audit log (never passwords or codes).
Refreshing the browser page signs you out.

## Set up the AI assistant
1. Create a key at https://aistudio.google.com/apikey (new keys start with `AQ.`, older ones with `AIza`).
2. As administrator open **AI Assistant → 🔑 Gemini connection & key setup**, paste the key, press **Test connection**,
   then **Save key & model**. (Or edit `.streamlit/secrets.toml`.)
3. If the test fails, the message names the cause (key, model, quota, network, missing library).
   Update the library with `pip install -U google-genai` (the launcher does this automatically).

## Set up e-mail (optional, enables e-mail codes and username reminders)
Fill the `SMTP_*` lines in `.streamlit/secrets.toml` (see `secrets.toml.example`), restart, then test under
**Reports & Backup → System → E-mail (SMTP) test**. Gmail needs an *App password*.

## Bulk import
**Add Spare Parts → Bulk import.** Download the Excel template, fill it (columns: Part Name, Category, Part Number,
Quantity, Minimum Stock, Location, Manufacturer, Unit, Remarks; common alternative headings are recognised), upload it,
review the preview (problem rows are flagged and skipped), then confirm. Up to 2,000 rows at a time.

## Project structure
```
IndusStock_AI/
├── app.py                      # entry point, sidebar navigation
├── run_app.bat / run_app.sh    # one-click launchers
├── requirements.txt
├── .streamlit/                 # config.toml (theme), secrets.toml(.example)
├── data/inventory.db           # SQLite database
├── src/
│   ├── config.py  database.py  # settings, schema and migrations
│   ├── inventory_service.py    # stock logic, analytics, bulk import, exports
│   ├── user_service.py         # accounts, roles, lock-out, account recovery
│   ├── security.py  mailer.py  # password hashing; SMTP e-mail
│   ├── auth.py                 # setup, sign-in, recovery screens, session rules
│   ├── ai_assistant.py         # ElectroBot (intents, languages, Gemini)
│   ├── widgets.py  ui.py       # safe HTML components and the stylesheet
│   └── views/                  # one file per page
├── scripts/                    # seed_demo_data, reset_admin_password, test_gemini_connection
├── tests/                      # automated tests
└── docs/USER_MANUAL.md
```

## Optional settings (`.streamlit/secrets.toml` or environment variables)
`GEMINI_API_KEY`, `GEMINI_MODEL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`,
`SESSION_TIMEOUT_MINUTES`, `INVENTORY_DB_PATH`, `APP_TIMEZONE` (default `Asia/Karachi`; the database stores UTC).

## Dark and light mode
Dark by default (`.streamlit/config.toml`). Switch: top-right menu (⋮) → **Settings** → **Theme**.

## Backup and restore
**Reports & Backup → Backup** downloads the database. To restore, stop the app, replace `data/inventory.db`, start the app.
Backups contain hashed passwords: store them safely. Databases from older versions are upgraded automatically on start.

## Testing
```bash
python -m unittest discover -s tests -t .      # or: pytest
```
Covers stock rules, import validation, sign-in and lock-out, all four recovery methods, roles, HTML escaping,
migrations, legacy NULL data and the assistant.

## Troubleshooting
| Problem | Fix |
|---|---|
| Forgot password / username | Use *Forgot password or username?* on the sign-in page, or the recovery script above |
| `ModuleNotFoundError` | Activate the virtual environment and run `pip install -r requirements.txt` |
| AI shows an error | As admin: AI Assistant → Gemini setup → **Test connection** names the cause |
| E-mail code never arrives | Reports & Backup → System → SMTP test; check spam; confirm an e-mail is saved in the account |
| Voice input does not work | Use Chrome or Edge, allow the microphone, open the app on `localhost` or HTTPS |
| Times look 5 hours off | Set `APP_TIMEZONE` |

## Version 3.0 highlights
Rebranded as **IndusStock AI**; forgot password / username with four recovery methods; redesigned sign-in page and
dashboard; bulk import; part detail cards; reset-request inbox and sign-in activity for admins; fixes: recovery-code
screen after first-time setup, checkbox-inside-form behaviour on user forms, stable menu selection when the request badge
changes, NULL-safe data handling for old databases and pandas 2.x.
