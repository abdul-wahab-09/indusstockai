r"""Create a demo database with realistic sample data (for demonstrations and testing).

Usage:
    python scripts/seed_demo_data.py                  # writes data/demo_inventory.db
    python scripts/seed_demo_data.py --db my_demo.db
Then run the app against it:
    INVENTORY_DB_PATH=data/demo_inventory.db streamlit run app.py        (Linux / macOS)
    set INVENTORY_DB_PATH=data\demo_inventory.db && streamlit run app.py (Windows)
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import inventory_service as svc  # noqa: E402
from src import user_service  # noqa: E402
from src.database import init_db  # noqa: E402

# (name, category, part number, qty, min, location, manufacturer)
DEMO_PARTS = [
    ("Contactor 25A 24VDC coil", "Contactor", "DEMO-LC1D25", 8, 3, "MCC Panel 1", "Schneider"),
    ("Contactor 40A 230VAC coil", "Contactor", "DEMO-LC1D40", 5, 2, "MCC Panel 1", "Schneider"),
    ("MCCB 100A 3P", "Circuit Breaker / MCB / MCCB", "DEMO-MCCB100", 3, 2, "Main Distribution", "ABB"),
    ("MCB 16A 1P", "Circuit Breaker / MCB / MCCB", "DEMO-MCB16", 20, 8, "Store Rack A2", "Siemens"),
    ("HRC Fuse 63A", "Fuse", "DEMO-HRC63", 12, 6, "Store Rack A1", "Siemens"),
    ("Glass Fuse 5A", "Fuse", "DEMO-GF5", 40, 20, "Store Rack A1", "Generic"),
    ("Relay 24VDC 4C/O", "Relay", "DEMO-RXM4", 15, 6, "Control Room", "Schneider"),
    ("Inductive Proximity Sensor M18", "Sensor / Transducer", "DEMO-PRX18", 6, 4, "Store Rack B1", "Omron"),
    ("Pressure Transmitter 4-20mA", "Sensor / Transducer", "DEMO-PT420", 2, 2, "Store Rack B1", "Endress+Hauser"),
    ("VFD 15kW 415V", "VFD / Drive", "DEMO-VFD15", 1, 1, "Drive Room", "ABB"),
    ("VFD 7.5kW 415V", "VFD / Drive", "DEMO-VFD75", 2, 1, "Drive Room", "ABB"),
    ("PLC Digital Input Module 16pt", "PLC / I/O Module", "DEMO-DI16", 4, 2, "PLC Cabinet", "Siemens"),
    ("PLC Analog Input Module 8ch", "PLC / I/O Module", "DEMO-AI8", 2, 2, "PLC Cabinet", "Siemens"),
    ("HMI 10 inch Touch Panel", "HMI / Display", "DEMO-HMI10", 1, 1, "Control Room", "Siemens"),
    ("Power Supply 24VDC 10A", "Power Supply", "DEMO-PSU24", 3, 2, "Control Room", "Phoenix Contact"),
    ("Induction Motor 5.5kW", "Motor", "DEMO-MOT55", 1, 1, "Motor Store", "Siemens"),
    ("Bearing 6310 2RS", "Bearing", "DEMO-B6310", 10, 6, "Mechanical Store", "SKF"),
    ("Push Button Green NO", "Switch / Push Button", "DEMO-PBG", 14, 8, "Store Rack A3", "Schneider"),
    ("Control Transformer 415/110V 500VA", "Transformer", "DEMO-CT500", 0, 1, "Store Rack C1", "Generic"),
    ("Capacitor 50uF 440V", "Capacitor", "DEMO-CAP50", 9, 4, "Store Rack C2", "Generic"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/demo_inventory.db")
    args = parser.parse_args()
    db = Path(args.db)
    if db.exists():
        db.unlink()
    init_db(db)

    random.seed(42)
    ids = []
    for name, cat, number, qty, minimum, loc, maker in DEMO_PARTS:
        ids.append(svc.add_part(part_name=name, category=cat, part_number=number, quantity=qty,
                                min_stock=minimum, location=loc, manufacturer=maker, actor="demo", db_path=db))

    # Spread realistic movements over the last ~100 days.
    now = datetime.now(timezone.utc)
    for pid in ids:
        for _ in range(random.randint(2, 9)):
            kind = random.choice(["Stock Out", "Stock Out", "Stock In"])
            amount = random.randint(1, 3)
            if kind == "Stock Out" and (svc.get_part(pid, db) or {}).get("quantity", 0) < amount:
                kind = "Stock In"
            svc.record_transaction(
                pid, kind, amount, reference=random.choice(["WO-1042", "WO-1057", "Breakdown", "PO-7781", "PM Round"]),
                performed_by="demo", db_path=db)
    # Back-date the generated transactions.
    conn = sqlite3.connect(db)
    for (tx_id,) in conn.execute("SELECT id FROM transactions").fetchall():
        stamp = (now - timedelta(days=random.randint(0, 100), hours=random.randint(0, 23))).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE transactions SET transaction_date = ? WHERE id = ?", (stamp, tx_id))
    conn.commit()
    conn.close()
    # Demo-only accounts. Never use these passwords on a real installation.
    user_service.create_user("admin", "Admin12345", full_name="Demo Administrator", role="admin",
                             must_change=False, actor="demo", db_path=db)
    user_service.create_user("operator", "Operator123", full_name="Demo Store Operator", role="user",
                             must_change=False, actor="demo", db_path=db)
    print(f"Demo database created: {db} ({len(ids)} parts)")
    print("Demo sign-in -> admin / Admin12345   |   operator / Operator123")


if __name__ == "__main__":
    main()
