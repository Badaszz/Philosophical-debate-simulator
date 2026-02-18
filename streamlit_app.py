import streamlit as st
import requests

API_URL = "http://127.0.0.1:8000/debate"

st.set_page_config(
    page_title="Philosophical Debate Simulator",
    page_icon="🧠",
    layout="wide"
)

st.title("🧠 Philosophical Debate Simulator")

topic = st.text_input(
    "Enter a philosophical topic",
    placeholder="e.g. Utilitarianism vs Kantian Ethics"
)

if st.button("Start Debate"):

    if not topic:
        st.warning("Please enter a topic.")
    else:
        with st.spinner("Philosophers are debating..."):

            response = requests.post(
                API_URL,
                json={"topic": topic},
                timeout=600
            )

            if response.status_code == 200:
                dialogue = response.json()["dialogue"]

                st.subheader("Debate Output")
                st.markdown(dialogue)

            else:
                st.error("API error")
