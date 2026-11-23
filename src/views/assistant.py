import json

import streamlit as st
import streamlit.components.v1 as components

from .. import ai_assistant, auth
from ..config import ASSISTANT_NAME, GEMINI_MODEL, SITE_NAME, get_secret
from .gemini_panel import render_panel

try:  # voice input is optional
    from streamlit_mic_recorder import speech_to_text
except Exception:  # pragma: no cover
    speech_to_text = None

QUICK_QUESTIONS = [
    "Which parts are low on stock?",
    "Show most consumed parts",
    "Show recent transactions",
    "What is the total stock quantity?",
]
VOICE_LANGUAGES = {"English": "en", "اردو (Urdu)": "ur-PK"}


def _speak(text: str) -> None:
    payload = json.dumps(ai_assistant.speech_text(text)).replace("</", "<\\/")
    language = "ur-PK" if any("\u0600" <= ch <= "\u06FF" for ch in text) else "en-US"
    components.html(
        f"""<script>
            const text = {payload};
            if ("speechSynthesis" in window && text) {{
                window.speechSynthesis.cancel();
                const u = new SpeechSynthesisUtterance(text);
                u.lang = "{language}"; u.rate = 1;
                window.speechSynthesis.speak(u);
            }}
        </script>""",
        height=0,
    )


def render() -> None:
    st.header(f"🤖 {ASSISTANT_NAME}")
    st.caption(f"AI assistant | Electrical and Electronic Spare Parts | {SITE_NAME} | English, اردو and Roman Urdu")

    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("last_voice_text", "")

    api_key = get_secret("GEMINI_API_KEY")
    if auth.is_admin():
        render_panel(key_prefix="assistant")  # key setup is an administrator task
    if not api_key:
        st.info("Engineering questions need a Gemini API key"
                + ("." if auth.is_admin() else ": ask the administrator to set it up.")
                + " Inventory questions work without it.")

    c1, c2 = st.columns([1, 1])
    speak_answers = c1.checkbox("🔊 Speak answers", value=True)
    voice_language = c2.selectbox("Voice input language", list(VOICE_LANGUAGES), label_visibility="collapsed")

    question = None
    quick_cols = st.columns(len(QUICK_QUESTIONS))
    for col, text in zip(quick_cols, QUICK_QUESTIONS):
        if col.button(text, key=f"quick_{text}"):
            question = text

    voice_text = None
    if speech_to_text is not None:
        voice_text = speech_to_text(
            language=VOICE_LANGUAGES[voice_language], start_prompt="🎤 Start speaking",
            stop_prompt="⏹️ Stop recording", just_once=True, key="voice_input",
        )
    else:
        st.caption("Voice input unavailable: install `streamlit-mic-recorder`.")

    typed = st.chat_input(f"Ask {ASSISTANT_NAME} about spare parts, stock, or electrical engineering...")
    if typed:
        question = typed
    elif question is None and voice_text and voice_text != st.session_state["last_voice_text"]:
        question = voice_text
        st.session_state["last_voice_text"] = voice_text

    if question:
        history = list(st.session_state["messages"])
        st.session_state["messages"].append({"role": "user", "content": question})
        with st.spinner(f"{ASSISTANT_NAME} is checking the inventory..."):
            answer = ai_assistant.answer_question(
                question, api_key=api_key, model=get_secret("GEMINI_MODEL", GEMINI_MODEL) or GEMINI_MODEL,
                history=history,
            )
        st.session_state["messages"].append({"role": "assistant", "content": answer})
        st.session_state["speak_text"] = answer
        st.rerun()

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    pending = st.session_state.pop("speak_text", None)  # speak each answer only once
    if pending and speak_answers:
        _speak(pending)

    if st.session_state["messages"] and st.button("🗑️ Clear chat"):
        st.session_state["messages"] = []
        st.session_state["last_voice_text"] = ""
        st.rerun()
