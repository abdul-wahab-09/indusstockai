"""Gemini connection panel: shows status, tests the connection and saves the API key."""
import streamlit as st

from .. import ai_assistant
from ..config import GEMINI_MODEL, SECRETS_PATH, get_secret, save_secret


def render_panel(expanded: bool = False, key_prefix: str = "gem") -> None:
    api_key = get_secret("GEMINI_API_KEY")
    with st.expander("🔑 Gemini connection & key setup", expanded=expanded or not api_key):
        if api_key:
            st.success(f"API key found ({len(api_key)} characters). Press **Test connection** to verify it.")
        else:
            st.warning("No Gemini API key found. Paste one below, or add it to `.streamlit/secrets.toml`.")

        new_key = st.text_input("Gemini API key", type="password", key=f"{key_prefix}_key",
                                placeholder="Paste key from https://aistudio.google.com/apikey")
        model = st.text_input("Model", value=get_secret("GEMINI_MODEL", GEMINI_MODEL) or GEMINI_MODEL,
                              key=f"{key_prefix}_model", help="Default: gemini-3.5-flash-lite")

        c1, c2, _ = st.columns([1, 1, 2])
        if c1.button("🧪 Test connection", key=f"{key_prefix}_test"):
            key_to_use = (new_key or "").strip() or api_key
            with st.spinner("Contacting Gemini..."):
                result = ai_assistant.test_connection(key_to_use, (model or GEMINI_MODEL).strip())
            if result["ok"]:
                st.success(result["message"])
            else:
                st.error(result["message"])

        if c2.button("💾 Save key & model", key=f"{key_prefix}_save"):
            key_to_use = (new_key or "").strip()
            if key_to_use:
                st.session_state["override_GEMINI_API_KEY"] = key_to_use
            st.session_state["override_GEMINI_MODEL"] = (model or GEMINI_MODEL).strip()
            try:
                if key_to_use:
                    save_secret("GEMINI_API_KEY", key_to_use)
                save_secret("GEMINI_MODEL", (model or GEMINI_MODEL).strip())
                st.success(f"Saved to {SECRETS_PATH.name}. It is active now.")
            except OSError as error:
                st.warning(f"Active for this session, but the file could not be written: {error}")
        st.caption("Both key formats work: older `AIza...` keys and new AI Studio `AQ....` keys "
                   "(the `AQ.` format needs an up-to-date `google-genai` library).")
        st.caption("Keep the key private. On Streamlit Cloud or other hosts, put it in the host's Secrets "
                   "settings instead; files written by the app may not persist there.")
