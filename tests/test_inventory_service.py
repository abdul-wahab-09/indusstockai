import os
import sqlite3
import tempfile
import unittest
from datetime import date

from src import inventory_service as svc
from src.database import backup_bytes, init_db


class InventoryServiceTests(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self.db)

    def tearDown(self):
        os.remove(self.db)

    def _add(self, name="Contactor 25A", number="LC1D25", qty=5, minimum=2, category="Contactor"):
        return svc.add_part(part_name=name, category=category, part_number=number, quantity=qty,
                            min_stock=minimum, location="MCC 1", db_path=self.db)

    # -- parts
    def test_add_and_list(self):
        self._add()
        df = svc.list_parts(db_path=self.db)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["status"], svc.STATUS_OK)

    def test_validation(self):
        with self.assertRaises(svc.InventoryError):
            svc.add_part(part_name="  ", category="Fuse", db_path=self.db)
        with self.assertRaises(svc.InventoryError):
            svc.add_part(part_name="X", category="Fuse", quantity=-1, db_path=self.db)

    def test_duplicate_part_number_rejected_case_insensitive(self):
        self._add()
        with self.assertRaises(svc.InventoryError):
            self._add(name="Other", number="lc1d25")

    def test_update_and_audit(self):
        pid = self._add()
        svc.update_part(pid, min_stock=4, location="MCC 2", actor="tester", db_path=self.db)
        part = svc.get_part(pid, self.db)
        self.assertEqual((part["min_stock"], part["location"]), (4, "MCC 2"))
        self.assertIn("EDIT_PART", svc.audit_df(db_path=self.db)["action"].tolist())

    def test_archive_and_restore_keep_history(self):
        pid = self._add()
        svc.record_transaction(pid, "Stock Out", 1, db_path=self.db)
        svc.set_part_active(pid, False, db_path=self.db)
        self.assertTrue(svc.list_parts(db_path=self.db).empty)
        self.assertEqual(len(svc.list_parts(archived=True, db_path=self.db)), 1)
        self.assertEqual(len(svc.transactions_df(db_path=self.db)), 1)
        with self.assertRaises(svc.InventoryError):
            svc.record_transaction(pid, "Stock In", 1, db_path=self.db)
        svc.set_part_active(pid, True, db_path=self.db)
        self.assertEqual(len(svc.list_parts(db_path=self.db)), 1)

    # -- transactions
    def test_stock_in_out(self):
        pid = self._add(qty=5)
        self.assertEqual(svc.record_transaction(pid, "Stock In", 5, db_path=self.db), 10)
        self.assertEqual(svc.record_transaction(pid, "Stock Out", 4, reference="WO-1", db_path=self.db), 6)
        tx = svc.transactions_df(db_path=self.db)
        self.assertEqual(len(tx), 2)
        self.assertEqual(tx.iloc[0]["reference"], "WO-1")

    def test_cannot_issue_more_than_available(self):
        pid = self._add(qty=2)
        with self.assertRaises(svc.InventoryError):
            svc.record_transaction(pid, "Stock Out", 3, db_path=self.db)
        self.assertEqual(svc.get_part(pid, self.db)["quantity"], 2)
        self.assertTrue(svc.transactions_df(db_path=self.db).empty)

    def test_invalid_transaction_inputs(self):
        pid = self._add()
        with self.assertRaises(svc.InventoryError):
            svc.record_transaction(pid, "Stock Out", 0, db_path=self.db)
        with self.assertRaises(svc.InventoryError):
            svc.record_transaction(pid, "Transfer", 1, db_path=self.db)

    # -- alerts / analytics
    def test_low_stock_and_reorder(self):
        self._add(name="A", number="A1", qty=0, minimum=3)
        self._add(name="B", number="B1", qty=2, minimum=3)
        self._add(name="C", number="C1", qty=10, minimum=3)
        low = svc.low_stock_parts(db_path=self.db)
        self.assertEqual(low["part_name"].tolist(), ["A", "B"])
        self.assertEqual(low["suggested_reorder"].tolist(), [6, 4])

    def test_consumption_and_cover(self):
        pid = self._add(qty=30)
        svc.record_transaction(pid, "Stock Out", 9, db_path=self.db)
        cons = svc.consumption(db_path=self.db)
        self.assertEqual(int(cons.iloc[0]["consumed"]), 9)
        cover = svc.stock_cover(days=90, db_path=self.db)
        self.assertEqual(cover.iloc[0]["days_of_cover"], 210.0)  # 21 units / (9/90 per day)
        self.assertEqual(cover.iloc[0]["cover_status"], "Healthy")

    def test_kpis_and_movement_summary(self):
        pid = self._add(qty=5)
        svc.record_transaction(pid, "Stock In", 2, db_path=self.db)
        svc.record_transaction(pid, "Stock Out", 1, db_path=self.db)
        k = svc.kpis(self.db)
        self.assertEqual((k["total_parts"], k["total_units"], k["movements_30d"]), (1, 6, 2))
        tx = svc.transactions_df(start=date(2000, 1, 1), db_path=self.db)
        summary = svc.movement_summary(tx, "M")
        self.assertEqual(summary.iloc[0].tolist(), [2, 1])

    def test_search(self):
        self._add(name="Contactor 25A", number="LC1D25")
        self._add(name="HRC Fuse 63A", number="F63", category="Fuse")
        self.assertEqual(len(svc.list_parts(search="fuse 63", db_path=self.db)), 1)
        self.assertEqual(len(svc.search_parts_text(["lc1d25"], db_path=self.db)), 1)

    # -- exports / migration
    def test_exports(self):
        self._add()
        df = svc.pretty_parts(svc.list_parts(db_path=self.db))
        self.assertTrue(svc.to_csv_bytes(df).startswith(b"\xef\xbb\xbf"))
        self.assertTrue(svc.to_excel_bytes({"Inventory": df})[:2] == b"PK")

    def test_backup_is_valid_sqlite(self):
        self._add()
        data = backup_bytes(self.db)
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            with open(path, "wb") as handle:
                handle.write(data)
            self.assertEqual(sqlite3.connect(path).execute("SELECT COUNT(*) FROM spare_parts").fetchone()[0], 1)
        finally:
            os.remove(path)


class LegacyMigrationTests(unittest.TestCase):
    def test_upgrades_v1_database_and_cleans_whitespace(self):
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = sqlite3.connect(db)
            conn.executescript("""
                CREATE TABLE spare_parts (id INTEGER PRIMARY KEY AUTOINCREMENT, part_name TEXT, category TEXT,
                    part_number TEXT, quantity INTEGER, min_stock INTEGER, location TEXT);
                CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, part_id INTEGER,
                    transaction_type TEXT, quantity INTEGER, transaction_date TEXT DEFAULT CURRENT_TIMESTAMP);
                INSERT INTO spare_parts VALUES (1,'Contactor','Contactor',char(9)||'LC1D25',2,3,char(9)||'MCC Panel 1');
                INSERT INTO transactions VALUES (1,1,'Stock Out',6,'2026-11-19 13:29:14');
            """)
            conn.commit()
            conn.close()
            init_db(db)
            init_db(db)  # idempotent
            parts = svc.list_parts(db_path=db)
            self.assertEqual(parts.iloc[0]["part_number"], "LC1D25")
            self.assertEqual(parts.iloc[0]["location"], "MCC Panel 1")
            self.assertEqual(parts.iloc[0]["status"], svc.STATUS_OUT if parts.iloc[0]["quantity"] == 0 else svc.STATUS_LOW)
            tx = svc.transactions_df(db_path=db)
            self.assertEqual(tx.iloc[0]["time"], "6:29 PM")  # 13:29 UTC -> Asia/Karachi
        finally:
            os.remove(db)


if __name__ == "__main__":
    unittest.main()


class BulkImportTests(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self.db)
        svc.add_part(part_name="Existing", category="Fuse", part_number="EX-1", quantity=1, min_stock=1, db_path=self.db)

    def tearDown(self):
        os.remove(self.db)

    def test_csv_import_with_aliases_and_validation(self):
        csv = ("Item,Type,PN,Qty,Min,Rack\n"
               "Relay 24V,Relay,00123,5,2,Panel A\n"      # leading zeros must survive
               "Bad qty,Relay,R2,five,1,Panel A\n"
               ",Relay,R3,1,1,Panel A\n"                  # missing name
               "Dup existing,Fuse,ex-1,1,1,Panel A\n"
               "Dup in file,Fuse,00123,1,1,Panel A\n"
               "Neg,Fuse,R9,-1,1,\n"
               ",,,,,\n").encode()
        preview = svc.validate_import(svc.read_upload(csv, "parts.csv"), self.db)
        self.assertEqual(preview["status"].tolist(), ["ok", "error", "error", "error", "error", "error"])
        self.assertEqual(preview.iloc[0]["part_number"], "00123")
        added, skipped = svc.import_parts(preview, actor="tester", db_path=self.db)
        self.assertEqual((added, skipped), (1, 5))
        self.assertEqual(len(svc.list_parts(db_path=self.db)), 2)
        self.assertIn("BULK_IMPORT", svc.audit_df(db_path=self.db)["action"].tolist())

    def test_excel_template_round_trip(self):
        preview = svc.validate_import(svc.read_upload(svc.import_template_bytes(), "template.xlsx"), self.db)
        self.assertEqual(preview["status"].tolist(), ["ok", "ok"])
        self.assertEqual(svc.import_parts(preview, db_path=self.db), (2, 0))

    def test_errors(self):
        with self.assertRaises(svc.InventoryError):
            svc.read_upload(b"x", "notes.txt")
        with self.assertRaises(svc.InventoryError):
            svc.read_upload(b"not really excel", "broken.xlsx")
        with self.assertRaises(svc.InventoryError):
            svc.validate_import(svc.read_upload(b"foo,bar\n1,2\n", "x.csv"), self.db)

    def test_html_in_names_is_stored_as_text(self):
        preview = svc.validate_import(svc.read_upload(b"Part Name\n<b>x</b>\n", "x.csv"), self.db)
        svc.import_parts(preview, db_path=self.db)
        self.assertIn("<b>x</b>", svc.list_parts(db_path=self.db)["part_name"].tolist())
