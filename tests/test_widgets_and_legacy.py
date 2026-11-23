import os
import sqlite3
import tempfile
import unittest

import pandas as pd

from src import ai_assistant as ai
from src import inventory_service as svc
from src import widgets as w
from src.database import init_db

EVIL = '<img src=x onerror=alert(1)><script>alert(2)</script>"&'


class WidgetEscapingTests(unittest.TestCase):
    def assert_safe(self, markup):
        self.assertNotIn("<script", markup)
        self.assertNotIn("<img", markup)

    def test_all_builders_escape_user_text(self):
        parts = pd.DataFrame([{"part_name": EVIL, "part_number": EVIL, "quantity": 0, "min_stock": 3,
                               "status": "Out of Stock", "suggested_reorder": 6}])
        tx = pd.DataFrame([{"part_name": EVIL, "transaction_type": "Stock Out", "quantity": 1, "reference": EVIL,
                            "date": EVIL, "time": EVIL, "performed_by": EVIL}])
        for markup in (w.kpi_card("x", EVIL, EVIL, EVIL), w.pill(EVIL), w.bar_list([(EVIL, 2, EVIL)]),
                       w.attention_list(parts), w.timeline(tx), w.user_chip(EVIL, EVIL),
                       w.brand_lockup(EVIL, EVIL), w.greeting_banner(EVIL, EVIL, [(EVIL, EVIL)]),
                       w.empty_state(EVIL, EVIL, EVIL), w.donut([(EVIL, 1, "green")], EVIL, EVIL),
                       w.section_title(EVIL, EVIL), w.auth_hero(EVIL, EVIL, EVIL, [(EVIL, EVIL, EVIL)])):
            self.assert_safe(markup)

    def test_donut_handles_zero_and_meter_bounds(self):
        self.assertIn("rgba(128,128,128", w.donut([("a", 0, "green")], "0", "parts"))
        self.assertIn("width:100%", w.stock_meter(500, 2))
        self.assertIn("width:0%", w.stock_meter(0, 2))

    def test_initials(self):
        self.assertEqual(w.initials("Abdul Wahab"), "AW")
        self.assertEqual(w.initials("ali.khan"), "AK")
        self.assertEqual(w.initials(""), "?")


class LegacyNullDataTests(unittest.TestCase):
    """Rows from very old databases can contain NULLs; nothing may crash (also on pandas 2.x)."""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self.db)
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO spare_parts (part_name,category,part_number,quantity,min_stock,location) "
                     "VALUES ('Old part',NULL,NULL,3,1,NULL)")
        conn.execute("INSERT INTO spare_parts (part_name,category,part_number,quantity,min_stock,location) "
                     "VALUES (NULL,NULL,NULL,NULL,NULL,NULL)")
        conn.execute("INSERT INTO transactions (part_id,transaction_type,quantity) VALUES (1,'Stock Out',1)")
        conn.commit()
        conn.close()
        init_db(self.db)

    def tearDown(self):
        os.remove(self.db)

    def test_services_survive_nulls(self):
        parts = svc.list_parts(db_path=self.db)
        self.assertEqual(parts["category"].tolist(), ["Other", "Other"])
        self.assertFalse(parts.isna().any().any())
        self.assertEqual(len(svc.search_parts_text(["old"], db_path=self.db)), 1)
        self.assertEqual(svc.consumption(db_path=self.db).iloc[0]["part_number"], "")
        svc.stock_cover(90, db_path=self.db)
        svc.category_summary(db_path=self.db)
        svc.low_stock_parts(db_path=self.db)
        svc.to_excel_bytes({"P": svc.pretty_parts(parts)})

    def test_assistant_survives_nulls(self):
        self.assertIn("Old part", ai.answer_question("old part available", db_path=self.db))
        ai.build_prompt("q", "English", None, self.db)


if __name__ == "__main__":
    unittest.main()
