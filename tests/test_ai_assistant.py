import os
import tempfile
import unittest

from src import ai_assistant as ai
from src import inventory_service as svc
from src.database import init_db


class AssistantTests(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self.db)
        a = svc.add_part(part_name="Contactor 25A", category="Contactor", part_number="LC1D25", quantity=2,
                         min_stock=3, location="MCC Panel 1", db_path=self.db)
        svc.add_part(part_name="VFD 15kW", category="VFD / Drive", part_number="ACS580", quantity=5,
                     min_stock=1, location="Drive Room", db_path=self.db)
        svc.record_transaction(a, "Stock Out", 1, reference="WO-9", db_path=self.db)

    def tearDown(self):
        os.remove(self.db)

    def ask(self, q, **kw):
        return ai.answer_question(q, api_key=None, db_path=self.db, **kw)

    def test_language_detection(self):
        self.assertEqual(ai.detect_language("how many contactors"), "English")
        self.assertEqual(ai.detect_language("contactor kitne hain"), "Roman Urdu")
        self.assertEqual(ai.detect_language("کنٹیکٹر کتنے ہیں"), "Urdu")

    def test_low_stock(self):
        self.assertIn("Contactor 25A", self.ask("which parts are low stock?"))
        self.assertIn("کم اسٹاک", self.ask("کم stock والے پارٹس low stock دکھاؤ"))

    def test_totals(self):
        self.assertIn("6 units", self.ask("what is the total stock quantity"))
        self.assertIn("**2**", self.ask("how many parts do we have in total parts"))

    def test_search_by_part_number_and_category(self):
        self.assertIn("LC1D25", self.ask("lc1d25 available?"))
        self.assertIn("ACS580", self.ask("how many vfd do we have"))

    def test_not_found(self):
        self.assertIn("No matching spare part", self.ask("do we have xyz999 in stock"))

    def test_history_and_consumption(self):
        self.assertIn("WO-9", self.ask("show transaction history of lc1d25"))
        self.assertIn("Consumed", self.ask("most used parts"))

    def test_technical_question_goes_to_ai_and_reports_missing_key(self):
        reply = self.ask("why does a VFD trip on overcurrent")
        self.assertIn("GEMINI_API_KEY", reply)

    def test_prompt_contains_snapshot_and_history(self):
        prompt = ai.build_prompt("why vfd trips", "English", [{"role": "user", "content": "hello"}], self.db)
        self.assertIn("ACS580", prompt)
        self.assertIn("RECENT CONVERSATION", prompt)

    def test_speech_text_strips_markdown(self):
        self.assertNotIn("|", ai.speech_text("| a | b |\n|---|---|\n| **x** | y |"))


class GeminiHandlingTests(unittest.TestCase):
    """No network: the Gemini client is replaced by a fake."""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self.db)
        ai._clients.clear()
        ai._working_model.clear()

    def tearDown(self):
        os.remove(self.db)
        ai._clients.clear()
        ai._working_model.clear()

    def _install(self, behaviour):
        calls = []

        class Models:
            def generate_content(_self, model, contents):
                calls.append(model)
                return behaviour(model)

        class Client:
            models = Models()

        ai._clients["SECRETKEY123"] = Client()
        return calls

    def test_classify_errors(self):
        c = ai.classify_error
        self.assertEqual(c(Exception("400 INVALID_ARGUMENT. API key not valid")), "key")
        self.assertEqual(c(Exception("401 ACCESS_TOKEN_TYPE_UNSUPPORTED Expected OAuth 2 access token")), "authkey")
        self.assertEqual(c(Exception("404 NOT_FOUND models/x is not found")), "model")
        self.assertEqual(c(Exception("429 RESOURCE_EXHAUSTED quota")), "quota")
        self.assertEqual(c(Exception("ConnectError: getaddrinfo failed")), "network")
        self.assertEqual(c(ImportError("No module named 'google'")), "sdk")

    def test_success_returns_text(self):
        class R:
            text = "Check the DC bus."

        self._install(lambda m: R())
        self.assertEqual(ai.answer_question("why vfd trips", api_key="SECRETKEY123", db_path=self.db),
                         "Check the DC bus.")

    def test_falls_back_when_model_missing(self):
        class R:
            text = "ok"

        def behaviour(model):
            if model == "bad-model":
                raise Exception("404 NOT_FOUND model is not found")
            return R()

        calls = self._install(behaviour)
        reply = ai.answer_question("why vfd trips", api_key="SECRETKEY123", model="bad-model", db_path=self.db)
        self.assertEqual(reply, "ok")
        self.assertEqual(calls[0], "bad-model")
        self.assertEqual(ai._working_model["SECRETKEY123"], calls[-1])

    def test_error_message_is_friendly_and_hides_key(self):
        def behaviour(model):
            raise Exception("401 API key not valid: SECRETKEY123")

        self._install(behaviour)
        reply = ai.answer_question("why vfd trips", api_key="SECRETKEY123", db_path=self.db)
        self.assertIn("rejected the API key", reply)
        self.assertNotIn("SECRETKEY123", reply)

    def test_authkey_message(self):
        def behaviour(model):
            raise Exception("401 ACCESS_TOKEN_TYPE_UNSUPPORTED")

        self._install(behaviour)
        reply = ai.answer_question("why vfd trips", api_key="SECRETKEY123", db_path=self.db)
        self.assertIn("pip install --upgrade google-genai", reply)

    def test_connection_test(self):
        class R:
            text = "OK"

        self._install(lambda m: R())
        self.assertTrue(ai.test_connection("SECRETKEY123")["ok"])
        self.assertFalse(ai.test_connection(None)["ok"])
