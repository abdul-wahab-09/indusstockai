"""ElectroBot: inventory question answering (English, Urdu, Roman Urdu) with Gemini fallback.

Inventory questions (stock levels, low stock, history, consumption) are answered directly
and exactly from the database. Everything else (engineering and troubleshooting questions)
is sent to Gemini together with a live snapshot of the inventory.

This module has no Streamlit dependency and imports the Gemini SDK lazily, so it is testable.
"""
from __future__ import annotations

import json
import logging
import re
import time

import pandas as pd

from . import inventory_service as svc
from .config import ASSISTANT_NAME, GEMINI_MODEL, SITE_NAME

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ language handling
ROMAN_URDU_WORDS = {
    "kitne", "kitna", "kitni", "majood", "maujood", "hai", "hain", "batao", "dikhao", "kya",
    "kul", "kam", "khatam", "mila", "kar", "ka", "ki", "ke", "mein", "kahan", "chahiye",
    "batayein", "nikalo", "istemal", "hua", "hue", "huay", "mujhe", "kab",
}


def detect_language(question: str) -> str:
    if any("\u0600" <= ch <= "\u06FF" for ch in question):
        return "Urdu"
    words = set(re.findall(r"[a-zA-Z]+", question.lower()))
    return "Roman Urdu" if words & ROMAN_URDU_WORDS else "English"


MESSAGES = {
    "no_low": {
        "English": "Good news! No spare part is at or below its minimum stock level.",
        "Roman Urdu": "Achhi khabar! Kisi bhi spare part ka stock minimum level se kam nahi hai.",
        "Urdu": "اچھی خبر! کسی بھی اسپیئر پارٹ کا اسٹاک کم از کم حد سے کم نہیں ہے۔",
    },
    "low_title": {
        "English": "🚨 **Low stock / reorder alerts**",
        "Roman Urdu": "🚨 **Low stock / reorder alerts**",
        "Urdu": "🚨 **کم اسٹاک / دوبارہ آرڈر الرٹس**",
    },
    "no_consumption": {
        "English": "No stock consumption records were found.",
        "Roman Urdu": "Abhi database mein stock consumption ka koi record mojood nahi hai.",
        "Urdu": "ابھی ڈیٹابیس میں اسٹاک کے استعمال کا کوئی ریکارڈ موجود نہیں ہے۔",
    },
    "consumption_title": {
        "English": "📊 **Spare parts consumption report**",
        "Roman Urdu": "📊 **Spare parts consumption report**",
        "Urdu": "📊 **اسپیئر پارٹس کے استعمال کی رپورٹ**",
    },
    "no_history": {
        "English": "No matching transaction history was found in the database.",
        "Roman Urdu": "Is spare part ki koi transaction history database mein nahi mili.",
        "Urdu": "اس اسپیئر پارٹ کی کوئی ٹرانزیکشن ہسٹری ڈیٹابیس میں نہیں ملی۔",
    },
    "history_title": {
        "English": "📋 **Transaction history** (latest {n})",
        "Roman Urdu": "📋 **Transaction history** (latest {n})",
        "Urdu": "📋 **ٹرانزیکشن ہسٹری** (تازہ ترین {n})",
    },
    "total_stock": {
        "English": "Total available stock quantity: **{n} units**.",
        "Roman Urdu": "Database mein kul available stock quantity **{n} units** hai.",
        "Urdu": "ڈیٹابیس میں کل دستیاب اسٹاک کی مقدار **{n} یونٹس** ہے۔",
    },
    "total_parts": {
        "English": "Total active spare part records in inventory: **{n}**.",
        "Roman Urdu": "Inventory mein kul **{n}** spare part records mojood hain.",
        "Urdu": "انوینٹری میں کل **{n}** اسپیئر پارٹس کے ریکارڈ موجود ہیں۔",
    },
    "search_title": {
        "English": "🔎 **Matching spare parts**",
        "Roman Urdu": "🔎 **Matching spare parts**",
        "Urdu": "🔎 **ملتے جلتے اسپیئر پارٹس**",
    },
    "not_found": {
        "English": "No matching spare part was found in the inventory database.",
        "Roman Urdu": "Aapka required spare part inventory database mein nahi mila.",
        "Urdu": "آپ کا مطلوبہ اسپیئر پارٹ انوینٹری ڈیٹابیس میں نہیں ملا۔",
    },
    "ai_unavailable": {
        "English": "The AI service is not configured. Add `GEMINI_API_KEY` to `.streamlit/secrets.toml` to enable "
                   "engineering questions. Inventory questions still work.",
        "Roman Urdu": "AI service configure nahi hai. `.streamlit/secrets.toml` mein `GEMINI_API_KEY` add karein. "
                      "Inventory ke sawalat phir bhi kaam karte hain.",
        "Urdu": "AI سروس سیٹ اپ نہیں ہے۔ `.streamlit/secrets.toml` میں `GEMINI_API_KEY` شامل کریں۔",
    },
    "ai_err_key": {
        "English": "❌ Gemini rejected the API key. Make sure the **complete** key is copied (new Google keys start with "
                   "`AQ.`, older ones with `AIza`) and that it was created in Google AI Studio "
                   "(https://aistudio.google.com/apikey). Then update the library with `pip install -U google-genai`, "
                   "paste the key in **🔑 Gemini connection & key setup** and press **Test connection**.",
        "Roman Urdu": "❌ Gemini ne API key reject kar di. Pori key copy karein (nayi keys `AQ.` se shuru hoti hain, "
                      "purani `AIza` se) jo Google AI Studio se bani ho. Phir `pip install -U google-genai` chalayein, "
                      "**🔑 Gemini connection & key setup** mein key paste karke **Test connection** dabayein.",
    },
    "ai_err_authkey": {
        "English": "❌ Google rejected this key type (`ACCESS_TOKEN_TYPE_UNSUPPORTED`). New AI Studio keys start with "
                   "`AQ.` and work with the normal Gemini API, but need an up-to-date library. Run "
                   "`pip install --upgrade google-genai` (or run `run_app.bat` again). If it still fails, create a "
                   "new key in Google AI Studio for a project that has the Gemini API enabled, and make sure it is "
                   "not a Vertex AI / Cloud key.",
        "Roman Urdu": "❌ Google ne yeh key type reject kiya (`ACCESS_TOKEN_TYPE_UNSUPPORTED`). Naye AI Studio keys "
                      "`AQ.` se shuru hote hain aur naya library chahiye. `pip install --upgrade google-genai` "
                      "chalayein (ya `run_app.bat` dobara). Phir bhi na chale to AI Studio mein naya key banayein.",
    },
    "ai_err_model": {
        "English": "❌ The Gemini model name is not available for this key. Open **🔑 Gemini connection & key setup** "
                   "and choose another model, e.g. `gemini-3.5-flash`.",
        "Roman Urdu": "❌ Yeh Gemini model is key ke liye available nahi. **🔑 Gemini connection & key setup** mein "
                      "doosra model likhein, jaise `gemini-3.5-flash`.",
    },
    "ai_err_quota": {
        "English": "⏳ Gemini quota or rate limit reached. Wait a minute and try again, or enable billing in Google AI Studio.",
        "Roman Urdu": "⏳ Gemini ki quota / rate limit poori ho gayi. Ek minute baad dobara koshish karein.",
    },
    "ai_err_network": {
        "English": "🌐 Could not reach Google's Gemini servers. Check the internet connection, firewall, proxy or VPN.",
        "Roman Urdu": "🌐 Google Gemini server tak connection nahi bana. Internet, firewall, proxy ya VPN check karein.",
    },
    "ai_err_busy": {
        "English": "⏳ Gemini is busy right now. Please try again in a few seconds.",
        "Roman Urdu": "⏳ Gemini abhi busy hai. Chand seconds baad dobara koshish karein.",
    },
    "ai_err_sdk": {
        "English": "📦 The Gemini library is not installed. Run `pip install google-genai` inside the project's "
                   "virtual environment (or run `run_app.bat` again).",
        "Roman Urdu": "📦 Gemini library install nahi hai. Project ke virtual environment mein "
                      "`pip install google-genai` chalayein (ya `run_app.bat` dobara chalayein).",
    },
    "ai_err_region": {
        "English": "🌍 The Gemini API is not available from this location or network.",
        "Roman Urdu": "🌍 Gemini API is location ya network se available nahi.",
    },
    "ai_err_unknown": {
        "English": "⚠️ Gemini returned an unexpected error. Open **🔑 Gemini connection & key setup** and press "
                   "**Test connection** for details.",
        "Roman Urdu": "⚠️ Gemini se unexpected error aaya. **🔑 Gemini connection & key setup** mein "
                      "**Test connection** dabayein.",
        "Urdu": "⚠️ Gemini سے غیر متوقع خرابی آئی۔ **Gemini connection & key setup** میں Test connection دبائیں۔",
    },
}


def _t(key: str, language: str, **kwargs) -> str:
    return MESSAGES[key].get(language, MESSAGES[key]["English"]).format(**kwargs)


# ------------------------------------------------------------------ intent keywords
LOW_STOCK_WORDS = [
    "low stock", "reorder", "re-order", "below minimum", "out of stock", "kam stock", "stock kam",
    "khatam", "minimum se kam", "low quantity", "kam quantity", "shortage",
]
CONSUMPTION_WORDS = ["consumed", "consumption", "used parts", "most used", "usage", "istemal",
                     "kitna use", "kitne use", "fast moving"]
HISTORY_WORDS = [
    "transaction history", "recent transactions", "stock in history", "stock out history",
    "movement history", "transaction records", "history dikhao", "history batao", "transactions dikhao",
    "stock history", "previous history", "complete history", "purchase history", "kab purchase",
    "kab add hua", "kab stock in", "quantity issue", "previous transaction", "last transaction",
]
TOTAL_STOCK_WORDS = ["total stock quantity", "total available quantity", "total units", "total quantity",
                     "total stock", "kul stock", "kul quantity", "kitna stock", "available stock"]
TOTAL_PARTS_WORDS = ["total parts", "how many parts", "parts count", "kitne parts", "kitni parts",
                     "kitne spare parts", "kul spare parts", "number of spare parts", "total spare part",
                     "records in inventory", "how many total", "kitne spare parts hain"]
INVENTORY_HINTS = [
    "available", "availability", "in stock", "how many", "quantity of", "find part", "show me",
    "spare part", "inventory", "part number", "location of", "stock of", "search part", "kitne", "kitna",
    "kitni", "majood", "maujood", "stock hai", "part hai", "do we have", "where is",
]
TECHNICAL_HINTS = [
    "how to", "how do", "why", "explain", "difference", "troubleshoot", "fault", "error", "wiring",
    "calculate", "what is", "what does", "replace with", "compatible", "alternative", "setting",
    "parameter", "kyun", "kaise", "kia hota", "matlab", "wajah",
]
STOP_WORDS = {
    "how", "many", "much", "what", "which", "where", "show", "find", "search", "tell", "me", "the", "is",
    "are", "a", "an", "in", "of", "for", "please", "available", "availability", "stock", "quantity", "part",
    "parts", "spare", "spares", "current", "check", "do", "we", "have", "there", "any", "give", "details",
    "about", "can", "you", "does", "our", "mill", "inventory", "location", "number", "kitne", "kitna",
    "kitni", "majood", "maujood", "hain", "hai", "batao", "dikhao", "kya", "kul", "kam", "ka", "ki", "ke",
    "mein", "kahan", "chahiye", "mujhe", "transaction", "transactions", "history", "recent", "previous",
    "complete", "purchase", "out", "when", "was", "were", "its", "issue", "issued", "kab", "hua", "hui", "hue",
    "ko", "and", "or", "to", "with", "on", "it", "this", "that", "list", "all",
}


def _extract_words(text: str) -> list[str]:
    words = []
    for word in re.findall(r"[a-zA-Z0-9_\-]+", text.lower()):
        if word in STOP_WORDS or len(word) < 2:
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]  # contactors -> contactor
        words.append(word)
    return list(dict.fromkeys(words))


# ------------------------------------------------------------------ markdown formatting
def _md_table(headers: list[str], rows: list[list]) -> str:
    def cell(value) -> str:
        return str(value).replace("|", "/").replace("\n", " ")

    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def _parts_table(df: pd.DataFrame) -> str:
    rows = [[r.part_name, r.category, r.part_number, f"{r.quantity} {r.unit}", r.min_stock, r.location or "-", r.status]
            for r in df.itertuples()]
    return _md_table(["Part", "Category", "Part No.", "Available", "Min", "Location", "Status"], rows)


# ------------------------------------------------------------------ database answers
def _answer_low_stock(language: str, db_path) -> str:
    df = svc.low_stock_parts(db_path=db_path)
    if df.empty:
        return _t("no_low", language)
    rows = [[r.part_name, r.part_number, r.quantity, r.min_stock, r.suggested_reorder, r.location or "-", r.status]
            for r in df.itertuples()]
    table = _md_table(["Part", "Part No.", "Available", "Min", "Suggested reorder", "Location", "Status"], rows)
    return f"{_t('low_title', language)}\n\n{table}"


def _answer_consumption(language: str, db_path) -> str:
    df = svc.consumption(top_n=15, db_path=db_path)
    if df.empty:
        return _t("no_consumption", language)
    rows = [[r.part_name, r.part_number, f"{r.consumed} units", r.issues] for r in df.itertuples()]
    return f"{_t('consumption_title', language)}\n\n" + _md_table(["Part", "Part No.", "Consumed", "Issues"], rows)


def _answer_history(question: str, language: str, db_path) -> str:
    df = svc.history_for_words(_extract_words(question), limit=30, db_path=db_path)
    if df.empty:
        return _t("no_history", language)
    rows = [[r.part_name, r.part_number, r.transaction_type, r.quantity, r.date, r.time, r.reference or "-"]
            for r in df.itertuples()]
    table = _md_table(["Part", "Part No.", "Type", "Qty", "Date", "Time", "Reference"], rows)
    return f"{_t('history_title', language, n=len(df))}\n\n{table}"


def _answer_search(words: list[str], language: str, db_path) -> str | None:
    df = svc.search_parts_text(words, db_path=db_path)
    if df.empty:
        return None
    return f"{_t('search_title', language)}\n\n{_parts_table(df)}"


# ------------------------------------------------------------------ Gemini
# Tried in this order if the configured model is missing for the API key.
# (gemini-2.0-* models are shut down and intentionally not listed.)
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.1-flash-lite",
                   "gemini-2.5-flash-lite", "gemini-2.5-flash"]

_clients: dict[str, object] = {}
_working_model: dict[str, str] = {}


def _gemini_client(api_key: str):
    if api_key not in _clients:
        from google import genai  # imported lazily so the module works without the SDK

        try:
            from google.genai import types

            _clients[api_key] = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=45000))
        except Exception:  # older SDKs without HttpOptions(timeout=...)
            _clients[api_key] = genai.Client(api_key=api_key)
    return _clients[api_key]


def classify_error(exc: BaseException) -> str:
    """Map an exception to: sdk, authkey, key, model, quota, region, busy, network or unknown."""
    text = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, ImportError) or "no module named" in text:
        return "sdk"
    if "access_token_type_unsupported" in text or "expected oauth 2 access token" in text:
        return "authkey"
    if any(s in text for s in ("api_key_invalid", "api key not valid", "api key expired", "invalid api key",
                               "unauthenticated", "permission_denied", "api key was reported", "access_token_type_unsupported", "403", "401")):
        return "key"
    if "user location is not supported" in text or "failed_precondition" in text:
        return "region"
    if any(s in text for s in ("not_found", "404", "is not found", "not supported for generatecontent")):
        return "model"
    if any(s in text for s in ("resource_exhausted", "429", "quota", "rate limit")):
        return "quota"
    if any(s in text for s in ("connecterror", "connection", "timed out", "timeout", "getaddrinfo",
                               "name resolution", "network", "ssl", "proxy")):
        return "network"
    if any(s in text for s in ("unavailable", "503", "overloaded", "internal", "500")):
        return "busy"
    return "unknown"


def _sanitize(text: str, api_key: str | None) -> str:
    if api_key:
        text = text.replace(api_key, "***")
    return re.sub(r"(AIza|AQ\.)[0-9A-Za-z_.\-]{20,}", "***", text)


def explain_error(exc: BaseException, language: str, api_key: str | None) -> str:
    detail = _sanitize(f"{type(exc).__name__}: {exc}", api_key).replace("\n", " ")[:300]
    return f"{_t('ai_err_' + classify_error(exc), language)}\n\n_Technical detail: {detail}_"


def _generate(api_key: str, model: str, prompt: str) -> tuple[str, str]:
    """Call Gemini, retrying briefly on overload and trying fallback models if the model is missing."""
    client = _gemini_client(api_key)
    candidates: list[str] = []
    for name in (_working_model.get(api_key), model, *FALLBACK_MODELS):
        if name and name not in candidates:
            candidates.append(name)
    last: BaseException | None = None
    for name in candidates:
        for attempt in range(2):
            try:
                response = client.models.generate_content(model=name, contents=prompt)
                text = (response.text or "").strip()
                if not text:
                    raise RuntimeError("Gemini returned an empty response (the answer may have been blocked).")
                _working_model[api_key] = name
                return text, name
            except Exception as exc:  # noqa: BLE001 - classified below
                last = exc
                if classify_error(exc) == "busy" and attempt == 0:
                    time.sleep(1.5)
                    continue
                break
        if classify_error(last) != "model":
            raise last
    raise last  # type: ignore[misc]


def test_connection(api_key: str | None, model: str = GEMINI_MODEL) -> dict:
    """Used by the 'Test connection' buttons. Returns {ok, model, message}."""
    if not api_key:
        return {"ok": False, "model": None, "message": _t("ai_unavailable", "English")}
    try:
        text, used = _generate(api_key, model, "Reply with exactly the word: OK")
        return {"ok": True, "model": used, "message": f"Connected. Model in use: {used}. Reply: {text[:40]}"}
    except Exception as exc:  # noqa: BLE001
        log.exception("Gemini connection test failed")
        return {"ok": False, "model": None, "message": explain_error(exc, "English", api_key)}


def build_prompt(question: str, language: str, history: list[dict] | None, db_path) -> str:
    inventory = svc.list_parts(db_path=db_path)
    truncated = len(inventory) > 150
    inventory_rows = inventory.head(150)[
        ["part_name", "category", "part_number", "quantity", "unit", "min_stock", "location", "status"]
    ].to_dict("records")
    recent = svc.transactions_df(limit=20, db_path=db_path)
    recent_rows = recent[["part_name", "transaction_type", "quantity", "date", "time"]].to_dict("records")
    context = {
        "inventory_total_records": int(len(inventory)),
        "inventory_list_truncated": truncated,
        "inventory": inventory_rows,
        "recent_transactions": recent_rows,
    }
    language_rule = {
        "Roman Urdu": "Answer ONLY in simple Pakistani Roman Urdu (Latin letters). Keep technical terms "
                      "(PLC, VFD, Motor, Contactor, Part Number) in English.",
        "Urdu": "Answer ONLY in simple Urdu script. Keep technical terms (PLC, VFD, Motor, Contactor, "
                "Part Number) in English.",
    }.get(language, "Answer in clear, simple English.")
    convo = ""
    if history:
        lines = [f"{'User' if m['role'] == 'user' else ASSISTANT_NAME}: {m['content'][:500]}" for m in history[-6:]]
        convo = "RECENT CONVERSATION:\n" + "\n".join(lines) + "\n\n"
    return f"""You are {ASSISTANT_NAME}, the AI assistant of "IndusStock AI" (Electrical and Electronic Spare Parts Intelligence) at {SITE_NAME}.

Expertise: industrial electrical engineering, PLC and automation, VFD and DC drives, motors, electrical
protection, electronic components, and spare parts inventory.

LANGUAGE: {language_rule} Do not switch languages.

LIVE DATABASE SNAPSHOT (JSON):
{json.dumps(context, ensure_ascii=False, default=str)}

RULES:
1. Use the snapshot for any inventory question. Never invent quantities, part numbers, prices or locations.
2. If information is not in the snapshot, say it is not available. The snapshot may be truncated.
3. Never claim to have performed a stock transaction; direct the user to the Stock In / Stock Out page.
4. Compatibility or replacement advice must be verified by a qualified engineer; mention relevant safety
   precautions (isolation, lock-out/tag-out) when the answer involves live equipment.
5. Be concise and practical. Use short bullet points where helpful.

{convo}USER QUESTION:
{question}
"""


def _ask_gemini(question: str, language: str, api_key: str | None, model: str,
                history: list[dict] | None, db_path) -> str:
    if not api_key:
        return _t("ai_unavailable", language)
    try:
        text, _ = _generate(api_key, model, build_prompt(question, language, history, db_path))
        return text
    except Exception as exc:  # noqa: BLE001 - network, quota, invalid key, SDK missing...
        log.exception("Gemini request failed")
        return explain_error(exc, language, api_key)


# ------------------------------------------------------------------ public entry point
def answer_question(
    question: str,
    *,
    api_key: str | None = None,
    model: str = GEMINI_MODEL,
    history: list[dict] | None = None,
    db_path=None,
) -> str:
    q = question.lower().strip()
    language = detect_language(question)

    if any(w in q for w in LOW_STOCK_WORDS):
        return _answer_low_stock(language, db_path)
    if any(w in q for w in CONSUMPTION_WORDS):
        return _answer_consumption(language, db_path)
    if any(w in q for w in HISTORY_WORDS):
        return _answer_history(question, language, db_path)
    if any(w in q for w in TOTAL_STOCK_WORDS):
        total = int(svc.list_parts(db_path=db_path)["quantity"].sum())
        return _t("total_stock", language, n=total)
    if any(w in q for w in TOTAL_PARTS_WORDS):
        return _t("total_parts", language, n=len(svc.list_parts(db_path=db_path)))

    words = _extract_words(question)
    inventory_question = any(h in q for h in INVENTORY_HINTS)
    technical_question = any(h in q for h in TECHNICAL_HINTS)

    # Look in the database first, unless this is clearly an engineering question.
    if words and (inventory_question or (len(words) <= 2 and not technical_question)):
        found = _answer_search(words, language, db_path)
        if found:
            return found
        if inventory_question:
            return _t("not_found", language)

    return _ask_gemini(question, language, api_key, model, history, db_path)


_MD_NOISE = re.compile(r"[*_`#>|]+|-{3,}")


def speech_text(markdown: str, limit: int = 600) -> str:
    """Strip Markdown symbols so the browser's text-to-speech reads naturally."""
    text = _MD_NOISE.sub(" ", markdown)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]
