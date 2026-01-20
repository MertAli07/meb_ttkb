import uuid
import hmac
import hashlib
import streamlit as st
import boto3
import logging
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = boto3.client(
    service_name="bedrock-agent-runtime",
    region_name="eu-central-1",
)

AGENT_ID = "CHUW9WFEUR"
AGENT_ALIAS_ID = "YAXUOBWQ3B"

def _get_user_store():
    try:
        return st.secrets["auth"]["users"]
    except Exception:
        return None


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True

    users = _get_user_store()
    if not users:
        st.error(
            "Authentication is not configured. "
            "Please set secrets: auth.users.<username> = <sha256_password_hash>."
        )
        st.stop()

    with st.form("login"):
        st.write("Please sign in.")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        stored_hash = users.get(username)
        if stored_hash and hmac.compare_digest(_hash_password(password), stored_hash):
            st.session_state.authenticated = True
            st.session_state.username = username
            return True
        st.error("Invalid username or password.")

    return False


def init_chat_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Hi! I'm a basic Streamlit chatbot. Ask me anything.",
            }
        ]


def stream_agent_response(prompt: str):
    try:
        response = client.invoke_agent(
            agentId=AGENT_ID,
            agentAliasId=AGENT_ALIAS_ID,
            sessionId=str(uuid.uuid4()),
            inputText=prompt,
            enableTrace=False,
            streamingConfigurations={'streamFinalResponse': True}
        )

        # The 'completion' key contains the EventStream
        event_stream = response.get("completion")
        if not event_stream:
            yield "No streaming response received."
            return

        for event in event_stream:
            # 1. Handle the chunk event (this is the actual text)
            if "chunk" in event:
                data = event["chunk"]["bytes"].decode("utf-8")
                yield data

            # 2. Handle the trace event (if enableTrace=True)
            elif "trace" in event:
                # You can log traces to file instead of streaming them
                logger.debug("Trace received")

    except ClientError as e:
        yield f"Client error: {e}"
    except Exception as e:
        yield f"An error occurred: {e}"


st.set_page_config(page_title="Chatbot Home", page_icon="💬", layout="centered")

if not check_password():
    st.stop()

st.title("Home")
st.write("Welcome to the basic chatbot demo. This is the Home page.")

init_chat_state()

with st.sidebar:
    st.subheader("Controls")
    if st.button("Sign out"):
        st.session_state.authenticated = False
        st.session_state.username = None
        st.rerun()
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
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)
    with st.chat_message("assistant"):
        placeholder = st.empty()
        content = ""
        for chunk in stream_agent_response(user_prompt):
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8", errors="replace")
            content += chunk
            placeholder.markdown(content)
    st.session_state.messages.append({"role": "assistant", "content": content})
    st.rerun()
