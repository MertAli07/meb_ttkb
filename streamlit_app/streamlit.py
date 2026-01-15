import streamlit as st


def init_chat_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Hi! I'm a basic Streamlit chatbot. Ask me anything.",
            }
        ]


def handle_user_message(prompt: str) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})
    response = f"You said: {prompt}\n\nI'm a simple demo bot for now."
    st.session_state.messages.append({"role": "assistant", "content": response})


st.set_page_config(page_title="Chatbot Home", page_icon="💬", layout="centered")

st.title("Home")
st.write("Welcome to the basic chatbot demo. This is the Home page.")

init_chat_state()

with st.sidebar:
    st.subheader("Controls")
    if st.button("Clear chat"):
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Chat cleared. How can I help?",
            }
        ]

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

user_prompt = st.chat_input("Type your message")
if user_prompt:
    handle_user_message(user_prompt)
    st.rerun()
