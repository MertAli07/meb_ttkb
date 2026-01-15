from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(page_title="Diagram", page_icon="🧭", layout="wide")

st.title("Diagram")
st.write("A simple flow of the chatbot interaction.")

html_path = Path(__file__).with_name("index.html")
html_content = html_path.read_text(encoding="utf-8")

wrapped_html = f"""
<style>
  html, body, .stApp {{ background-color: #ffffff; }}
  .diagram-wrapper {{ background-color: #ffffff; width: 100%; }}
</style>
<div class="diagram-wrapper">
  {html_content}
</div>
"""

components.html(wrapped_html, height=1100, scrolling=True)
