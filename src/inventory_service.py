"""Business logic for the spare parts inventory.

All functions are UI-independent (no Streamlit imports) so they can be unit-tested
and reused by the AI assistant, reports and scripts.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from .config import (
    LOCAL_TIMEZONE,
    REORDER_MULTIPLIER,
    STOCK_IN,
    STOCK_OUT,
)
from .database import get_connection, write_audit

STATUS_OUT = "Out of Stock"
STATUS_LOW = "Low Stock"
STATUS_OK = "In Stock"

PART_COLUMNS_PRETTY = {
    "id": "ID",
    "part_name": "Part Name",
    "category": "Category",
    "part_number": "Part Number",
    "quantity": "Quantity",
    "unit": "Unit",
    "min_stock": "Minimum Stock",
    "status": "Status",
    "location": "Location / Panel",
    "manufacturer": "Manufacturer",
    "remarks": "Remarks",
}


class InventoryError(ValueError):
    """A user-correctable problem (validation failure, insufficient stock, ...)."""


# ------------------------------------------------------------------ helpers
def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _local_tz():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(LOCAL_TIMEZONE)
    except Exception:  # tz database missing: fall back to Pakistan Standard Time
        return timezone(timedelta(hours=5))


def local_now() -> datetime:
    """Current local date/time as a naive datetime (the database itself stores UTC)."""
    return datetime.now(_local_tz()).replace(tzinfo=None)


def to_local(series: pd.Series) -> pd.Series:
    """Convert UTC timestamp strings stored in SQLite to naive local datetimes."""
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    return parsed.dt.tz_convert(_local_tz()).dt.tz_localize(None)


def stock_status(quantity: int, min_stock: int) -> str:
    if quantity <= 0:
        return STATUS_OUT
    if quantity <= min_stock:
        return STATUS_LOW
    return STATUS_OK


def suggested_reorder(quantity: int, min_stock: int) -> int:
    """Units needed to restore stock to REORDER_MULTIPLIER x minimum (at least 1)."""
    return max(min_stock * REORDER_MULTIPLIER - quantity, 1)


def _audit(conn, actor: str, action: str, entity: str, entity_id: int | None, details: str) -> None:
    write_audit(conn, actor, action, entity, entity_id, details)


def _validate_part(name: str, category: str, quantity: int | None, min_stock: int) -> None:
    if not name:
        raise InventoryError("Part name is required.")
    if not category:
        raise InventoryError("Category is required.")
    if quantity is not None and int(quantity) < 0:
        raise InventoryError("Quantity cannot be negative.")
    if int(min_stock) < 0:
        raise InventoryError("Minimum stock cannot be negative.")


def _check_duplicate(conn, part_number: str, exclude_id: int | None = None) -> None:
    if not part_number:
        return
    row = conn.execute(
        "SELECT id, part_name FROM spare_parts WHERE is_active = 1 AND LOWER(TRIM(part_number)) = LOWER(?) AND id != ?",
        (part_number, exclude_id or -1),
    ).fetchone()
    if row:
        raise InventoryError(
            f"Part number '{part_number}' already exists (ID {row['id']}: {row['part_name']})."
        )


# ------------------------------------------------------------------ parts CRUD
def add_part(
    *,
    part_name: str,
    category: str,
    part_number: str = "",
    quantity: int = 0,
    min_stock: int = 0,
    location: str = "",
    manufacturer: str = "",
    unit: str = "pcs",
    remarks: str = "",
    actor: str = "system",
    db_path=None,
) -> int:
    name, number = _clean(part_name), _clean(part_number)
    _validate_part(name, _clean(category), quantity, min_stock)
    with get_connection(db_path) as conn:
        _check_duplicate(conn, number)
        now = _utc_now()
        cur = conn.execute(
            """
            INSERT INTO spare_parts
                (part_name, category, part_number, quantity, min_stock, location,
                 manufacturer, unit, remarks, is_active, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,1,?,?)
            """,
            (name, _clean(category), number, int(quantity), int(min_stock), _clean(location),
             _clean(manufacturer), _clean(unit) or "pcs", _clean(remarks), now, now),
        )
        part_id = int(cur.lastrowid)
        _audit(conn, actor, "ADD_PART", "spare_parts", part_id,
               f"{name} [{number}] qty={int(quantity)} min={int(min_stock)}")
        return part_id


EDITABLE_FIELDS = {"part_name", "category", "part_number", "min_stock", "location",
                   "manufacturer", "unit", "remarks"}


def update_part(part_id: int, *, actor: str = "system", db_path=None, **fields) -> None:
    unknown = set(fields) - EDITABLE_FIELDS
    if unknown:
        raise InventoryError(f"Fields cannot be edited here: {', '.join(sorted(unknown))}")
    values = {k: (int(v) if k == "min_stock" else _clean(v)) for k, v in fields.items()}
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM spare_parts WHERE id = ?", (part_id,)).fetchone()
        if not row:
            raise InventoryError("Spare part not found.")
        merged = {**dict(row), **values}
        _validate_part(merged["part_name"], merged["category"], None, merged["min_stock"])
        if "part_number" in values:
            _check_duplicate(conn, values["part_number"], exclude_id=part_id)
        changes = {k: (row[k], v) for k, v in values.items() if row[k] != v}
        if not changes:
            return
        assignments = ", ".join(f"{k} = ?" for k in changes) + ", updated_at = ?"
        conn.execute(
            f"UPDATE spare_parts SET {assignments} WHERE id = ?",
            [v for _, v in changes.values()] + [_utc_now(), part_id],
        )
        _audit(conn, actor, "EDIT_PART", "spare_parts", part_id,
               "; ".join(f"{k}: {old!r} -> {new!r}" for k, (old, new) in changes.items()))


def set_part_active(part_id: int, active: bool, *, actor: str = "system", db_path=None) -> None:
    """Archive (soft delete) or restore a part. Transaction history is always kept."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT part_name FROM spare_parts WHERE id = ?", (part_id,)).fetchone()
        if not row:
            raise InventoryError("Spare part not found.")
        conn.execute(
            "UPDATE spare_parts SET is_active = ?, updated_at = ? WHERE id = ?",
            (1 if active else 0, _utc_now(), part_id),
        )
        _audit(conn, actor, "RESTORE_PART" if active else "ARCHIVE_PART", "spare_parts", part_id, row["part_name"])


def get_part(part_id: int, db_path=None) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM spare_parts WHERE id = ?", (part_id,)).fetchone()
    return dict(row) if row else None


def list_parts(
    *,
    search: str = "",
    category: str | None = None,
    status: str | None = None,
    archived: bool = False,
    db_path=None,
) -> pd.DataFrame:
    sql = """
        SELECT id, COALESCE(part_name,'') AS part_name, COALESCE(NULLIF(TRIM(category),''),'Other') AS category,
               COALESCE(part_number,'') AS part_number, COALESCE(quantity,0) AS quantity,
               COALESCE(unit,'pcs') AS unit, COALESCE(min_stock,0) AS min_stock,
               COALESCE(location,'') AS location, COALESCE(manufacturer,'') AS manufacturer,
               COALESCE(remarks,'') AS remarks
        FROM spare_parts WHERE is_active = ?
    """
    params: list[Any] = [0 if archived else 1]
    for word in _clean(search).split():
        sql += """ AND (part_name LIKE ? OR category LIKE ? OR part_number LIKE ?
                        OR location LIKE ? OR manufacturer LIKE ?)"""
        params.extend([f"%{word}%"] * 5)
    if category and category != "All":
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY part_name COLLATE NOCASE"
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    df["status"] = [stock_status(q, m) for q, m in zip(df["quantity"], df["min_stock"])]
    if status and status != "All":
        df = df[df["status"] == status].reset_index(drop=True)
    return df


def pretty_parts(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in PART_COLUMNS_PRETTY if c in df.columns]
    return df[cols].rename(columns=PART_COLUMNS_PRETTY)


def low_stock_parts(db_path=None) -> pd.DataFrame:
    df = list_parts(db_path=db_path)
    df = df[df["status"] != STATUS_OK].copy()
    df["suggested_reorder"] = [suggested_reorder(q, m) for q, m in zip(df["quantity"], df["min_stock"])]
    order = {STATUS_OUT: 0, STATUS_LOW: 1}
    df["_rank"] = df["status"].map(order)
    return df.sort_values(["_rank", "quantity"]).drop(columns="_rank").reset_index(drop=True)


# ------------------------------------------------------------------ transactions
def record_transaction(
    part_id: int,
    transaction_type: str,
    quantity: int,
    *,
    reference: str = "",
    remarks: str = "",
    performed_by: str = "",
    db_path=None,
) -> int:
    """Apply a stock movement atomically and return the new stock level."""
    if transaction_type not in (STOCK_IN, STOCK_OUT):
        raise InventoryError("Transaction type must be 'Stock In' or 'Stock Out'.")
    qty = int(quantity)
    if qty <= 0:
        raise InventoryError("Quantity must be greater than zero.")
    with get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT quantity, part_name FROM spare_parts WHERE id = ? AND is_active = 1", (part_id,)
        ).fetchone()
        if not row:
            raise InventoryError("Spare part not found or archived.")
        current = int(row["quantity"] or 0)
        if transaction_type == STOCK_OUT and qty > current:
            raise InventoryError(f"Not enough stock. Available: {current}, requested: {qty}.")
        new_qty = current + qty if transaction_type == STOCK_IN else current - qty
        conn.execute(
            "UPDATE spare_parts SET quantity = ?, updated_at = ? WHERE id = ?", (new_qty, _utc_now(), part_id)
        )
        conn.execute(
            """INSERT INTO transactions
               (part_id, transaction_type, quantity, transaction_date, reference, remarks, performed_by)
               VALUES (?,?,?,?,?,?,?)""",
            (part_id, transaction_type, qty, _utc_now(), _clean(reference), _clean(remarks), _clean(performed_by)),
        )
        return new_qty


def transactions_df(
    *,
    start: date | None = None,
    end: date | None = None,
    part_id: int | None = None,
    transaction_type: str | None = None,
    limit: int | None = None,
    db_path=None,
) -> pd.DataFrame:
    sql = """
        SELECT t.id AS transaction_id, t.part_id, COALESCE(p.part_name,'(deleted part)') AS part_name,
               COALESCE(p.part_number,'') AS part_number, COALESCE(p.category,'') AS category,
               t.transaction_type, t.quantity, t.transaction_date,
               COALESCE(t.reference,'') AS reference, COALESCE(t.remarks,'') AS remarks,
               COALESCE(t.performed_by,'') AS performed_by
        FROM transactions t LEFT JOIN spare_parts p ON p.id = t.part_id WHERE 1=1
    """
    params: list[Any] = []
    if part_id:
        sql += " AND t.part_id = ?"
        params.append(int(part_id))
    if transaction_type and transaction_type != "All":
        sql += " AND t.transaction_type = ?"
        params.append(transaction_type)
    sql += " ORDER BY t.id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    df["timestamp"] = to_local(df["transaction_date"])
    df = df.drop(columns="transaction_date")
    if start:
        df = df[df["timestamp"].dt.date >= start]
    if end:
        df = df[df["timestamp"].dt.date <= end]
    df = df.reset_index(drop=True)
    df["date"] = df["timestamp"].dt.strftime("%d-%b-%Y")
    df["time"] = df["timestamp"].dt.strftime("%I:%M %p").str.lstrip("0")
    return df


TX_COLUMNS_PRETTY = {
    "transaction_id": "Transaction ID", "part_name": "Part Name", "part_number": "Part Number",
    "category": "Category", "transaction_type": "Type", "quantity": "Quantity",
    "reference": "Reference", "performed_by": "Performed By", "remarks": "Remarks",
    "date": "Date", "time": "Time",
}


def pretty_transactions(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in TX_COLUMNS_PRETTY if c in df.columns]
    return df[cols].rename(columns=TX_COLUMNS_PRETTY)


def movement_summary(df: pd.DataFrame, freq: str = "D") -> pd.DataFrame:
    """Stock In / Stock Out totals per day ('D') or month ('M')."""
    if df.empty:
        return pd.DataFrame(columns=[STOCK_IN, STOCK_OUT])
    data = df.dropna(subset=["timestamp"]).copy()
    if freq == "M":
        data["period"] = data["timestamp"].dt.strftime("%Y-%m")
    else:
        data["period"] = data["timestamp"].dt.strftime("%Y-%m-%d")
    pivot = data.pivot_table(index="period", columns="transaction_type", values="quantity",
                             aggfunc="sum", fill_value=0)
    for column in (STOCK_IN, STOCK_OUT):
        if column not in pivot.columns:
            pivot[column] = 0
    return pivot[[STOCK_IN, STOCK_OUT]].sort_index()


# ------------------------------------------------------------------ analytics
def kpis(db_path=None) -> dict:
    parts = list_parts(db_path=db_path)
    tx = transactions_df(start=date.today() - timedelta(days=29), db_path=db_path)
    return {
        "total_parts": int(len(parts)),
        "total_units": int(parts["quantity"].sum()) if not parts.empty else 0,
        "low_stock": int((parts["status"] == STATUS_LOW).sum()),
        "out_of_stock": int((parts["status"] == STATUS_OUT).sum()),
        "categories": int(parts["category"].nunique()) if not parts.empty else 0,
        "movements_30d": int(len(tx)),
        "issued_30d": int(tx.loc[tx["transaction_type"] == STOCK_OUT, "quantity"].sum()) if not tx.empty else 0,
    }


def consumption(days: int | None = None, top_n: int | None = None, db_path=None) -> pd.DataFrame:
    """Total quantity issued (Stock Out) per part, highest first."""
    sql = """
        SELECT p.id AS part_id, COALESCE(p.part_name,'') AS part_name, COALESCE(p.part_number,'') AS part_number,
               COALESCE(NULLIF(TRIM(p.category),''),'Other') AS category,
               SUM(t.quantity) AS consumed, COUNT(*) AS issues
        FROM transactions t JOIN spare_parts p ON p.id = t.part_id
        WHERE t.transaction_type = 'Stock Out'
    """
    params: list[Any] = []
    if days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        sql += " AND t.transaction_date >= ?"
        params.append(cutoff)
    sql += " GROUP BY p.id ORDER BY consumed DESC"
    if top_n:
        sql += f" LIMIT {int(top_n)}"
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    df["label"] = df["part_name"] + " (" + df["part_number"] + ")"
    return df


def stock_cover(days: int = 90, db_path=None) -> pd.DataFrame:
    """Estimate how many days current stock will last at the recent usage rate."""
    parts = list_parts(db_path=db_path)
    used = consumption(days=days, db_path=db_path)[["part_id", "consumed"]]
    df = parts.merge(used, how="left", left_on="id", right_on="part_id").drop(columns="part_id")
    df["consumed"] = df["consumed"].fillna(0).astype(int)
    df["daily_usage"] = (df["consumed"] / days).round(3)
    df["days_of_cover"] = [
        round(q / rate, 1) if rate > 0 else None for q, rate in zip(df["quantity"], df["daily_usage"])
    ]

    def risk(row) -> str:
        if row["consumed"] == 0:
            return "No recent usage"
        if row["days_of_cover"] <= 15:
            return "Critical (<= 15 days)"
        if row["days_of_cover"] <= 45:
            return "Watch (<= 45 days)"
        return "Healthy"

    df["cover_status"] = [risk(row) for _, row in df.iterrows()]  # also safe for an empty table
    return df.sort_values(["consumed"], ascending=False).reset_index(drop=True)


def category_summary(db_path=None) -> pd.DataFrame:
    parts = list_parts(db_path=db_path)
    if parts.empty:
        return pd.DataFrame(columns=["category", "parts", "units"])
    return (parts.groupby("category").agg(parts=("id", "count"), units=("quantity", "sum"))
            .reset_index().sort_values("parts", ascending=False))


def audit_df(limit: int = 500, db_path=None) -> pd.DataFrame:
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT id, event_time, actor, action, entity, entity_id, details FROM audit_log ORDER BY id DESC LIMIT ?",
            conn, params=[int(limit)],
        )
    df["event_time"] = to_local(df["event_time"])
    return df


# ------------------------------------------------------------------ AI-assistant helpers
def search_parts_text(words: list[str], limit: int = 15, db_path=None) -> pd.DataFrame:
    """Rank active parts by how many of the search words they match."""
    words = [w for w in words if w]
    if not words:
        return pd.DataFrame()
    df = list_parts(db_path=db_path)
    if df.empty:
        return df
    haystack = (df["part_name"] + " " + df["category"] + " " + df["part_number"] + " "
                + df["location"] + " " + df["manufacturer"]).str.lower()
    df["_score"] = sum(haystack.str.contains(re.escape(w.lower())).astype(int) for w in words)
    df = df[df["_score"] > 0].sort_values(["_score", "part_name"], ascending=[False, True])
    return df.head(limit).drop(columns="_score").reset_index(drop=True)


def history_for_words(words: list[str], limit: int = 50, db_path=None) -> pd.DataFrame:
    tx = transactions_df(db_path=db_path)
    if tx.empty or not words:
        return tx.head(limit)
    haystack = (tx["part_name"] + " " + tx["part_number"] + " " + tx["category"]).str.lower()
    mask = pd.Series(False, index=tx.index)
    for word in words:
        mask |= haystack.str.contains(re.escape(word.lower()))
    return tx[mask].head(limit).reset_index(drop=True)


# ------------------------------------------------------------------ bulk import
IMPORT_ALIASES = {
    "part_name": ["part name", "name", "item", "item name", "description", "part"],
    "category": ["category", "type", "group"],
    "part_number": ["part number", "part no", "part no.", "part #", "partno", "pn", "model", "code", "catalog number"],
    "quantity": ["quantity", "qty", "stock", "opening quantity", "opening stock", "available"],
    "min_stock": ["minimum stock", "min stock", "minimum stock level", "min", "minimum", "reorder level", "min qty"],
    "location": ["location", "location / panel", "panel", "rack", "store location", "bin"],
    "manufacturer": ["manufacturer", "manufacturer / brand", "brand", "make", "maker", "vendor"],
    "unit": ["unit", "uom"],
    "remarks": ["remarks", "notes", "comment", "comments"],
}
IMPORT_COLUMNS = list(IMPORT_ALIASES)
MAX_IMPORT_ROWS = 2000


def read_upload(content: bytes, filename: str) -> pd.DataFrame:
    """Read an uploaded .csv / .xlsx file as text (so part numbers like 00123 keep their zeros)."""
    name = (filename or "").lower()
    buffer = io.BytesIO(content)
    try:
        if name.endswith((".xlsx", ".xlsm")):
            return pd.read_excel(buffer, dtype=str, keep_default_na=False)
        if name.endswith(".csv"):
            return pd.read_csv(buffer, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except Exception as error:  # noqa: BLE001 - corrupted or unsupported file
        raise InventoryError(f"The file could not be read: {error}") from error
    raise InventoryError("Please upload a .csv or .xlsx file.")


def _to_int(value: str, label: str) -> tuple[int, str | None]:
    text = _clean(value).replace(",", "")
    if text == "":
        return 0, None
    try:
        number = float(text)
    except ValueError:
        return 0, f"{label} '{value}' is not a number"
    if number < 0 or number != int(number):
        return 0, f"{label} must be a whole number of 0 or more"
    return int(number), None


def validate_import(raw: pd.DataFrame, db_path=None) -> pd.DataFrame:
    """Map columns, validate every row and flag problems. Nothing is written to the database."""
    lookup = {}
    for column in raw.columns:
        key = re.sub(r"\s+", " ", str(column).strip().lower())
        for canonical, aliases in IMPORT_ALIASES.items():
            if key == canonical.replace("_", " ") or key in aliases:
                lookup.setdefault(canonical, column)
    if "part_name" not in lookup:
        raise InventoryError("No 'Part Name' column found. Download the template to see the expected columns.")
    if len(raw) > MAX_IMPORT_ROWS:
        raise InventoryError(f"At most {MAX_IMPORT_ROWS} rows can be imported at once (file has {len(raw)}).")

    with get_connection(db_path) as conn:
        existing = {r[0].strip().lower() for r in conn.execute(
            "SELECT part_number FROM spare_parts WHERE is_active = 1 AND TRIM(COALESCE(part_number,'')) != ''")}
    seen: set[str] = set()
    rows = []
    for position, (_, source) in enumerate(raw.iterrows(), start=2):  # row 1 is the header
        record = {c: _clean(source[lookup[c]]) if c in lookup else "" for c in IMPORT_COLUMNS}
        if not any(record.values()):
            continue  # skip fully blank lines
        problems = []
        if not record["part_name"]:
            problems.append("Part Name is missing")
        if len(record["part_name"]) > 200:
            problems.append("Part Name is longer than 200 characters")
        record["category"] = record["category"] or "Other"
        record["unit"] = record["unit"] or "pcs"
        record["quantity"], err = _to_int(record["quantity"], "Quantity")
        problems += [err] if err else []
        record["min_stock"], err = _to_int(record["min_stock"], "Minimum Stock")
        problems += [err] if err else []
        key = record["part_number"].lower()
        if key:
            if key in existing:
                problems.append("Part Number already exists in inventory")
            elif key in seen:
                problems.append("Part Number is repeated in this file")
            seen.add(key)
        rows.append({"row": position, **record, "status": "error" if problems else "ok",
                     "message": "; ".join(problems) or "Ready to import"})
    return pd.DataFrame(rows, columns=["row", *IMPORT_COLUMNS, "status", "message"])


def import_parts(preview: pd.DataFrame, *, actor: str = "system", db_path=None) -> tuple[int, int]:
    """Insert every row marked 'ok'. Returns (added, skipped)."""
    added = skipped = 0
    for record in preview.to_dict("records"):
        if record["status"] != "ok":
            skipped += 1
            continue
        try:
            add_part(**{c: record[c] for c in IMPORT_COLUMNS}, actor=actor, db_path=db_path)
            added += 1
        except InventoryError:
            skipped += 1  # e.g. a part number added by someone else in the meantime
    if added:
        with get_connection(db_path) as conn:
            _audit(conn, actor, "BULK_IMPORT", "spare_parts", None, f"{added} added, {skipped} skipped")
    return added, skipped


def import_template_bytes() -> bytes:
    sample = pd.DataFrame([
        ["Contactor 25A 24VDC coil", "Contactor", "LC1D25BD", 8, 3, "MCC Panel 1", "Schneider", "pcs", ""],
        ["HRC Fuse 63A", "Fuse", "NH00-63", 20, 6, "Store Rack A1", "Siemens", "pcs", "Spare for MCC 2"],
    ], columns=["Part Name", "Category", "Part Number", "Quantity", "Minimum Stock", "Location",
                "Manufacturer", "Unit", "Remarks"])
    return to_excel_bytes({"Parts": sample})


# ------------------------------------------------------------------ exports
def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")  # BOM keeps Excel happy with Urdu text


def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """Build a formatted .xlsx workbook (header style, frozen header row, auto column widths)."""
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame = frame.copy()
            for col in frame.columns:
                if pd.api.types.is_datetime64_any_dtype(frame[col]):
                    frame[col] = frame[col].dt.strftime("%Y-%m-%d %H:%M")
            frame.to_excel(writer, sheet_name=name[:31], index=False)
            ws = writer.sheets[name[:31]]
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1F3864")
                cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.freeze_panes = "A2"
            for idx, col in enumerate(frame.columns, start=1):
                longest = max([len(str(col))] + [len(str(v)) for v in frame[col].head(200)])
                ws.column_dimensions[get_column_letter(idx)].width = min(max(longest + 3, 10), 50)
    return buffer.getvalue()

