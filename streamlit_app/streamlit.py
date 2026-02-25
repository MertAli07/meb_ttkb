import uuid
import hmac
import hashlib
from datetime import datetime, timezone
import streamlit as st
import boto3
import logging
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = boto3.client(
    service_name="bedrock-agent-runtime",
    region_name=st.secrets["aws"]["region"],
    aws_access_key_id=st.secrets["aws"]["access_key_id"],
    aws_secret_access_key=st.secrets["aws"]["secret_access_key"],
)

AGENT_ID = "CHUW9WFEUR"
AGENT_ALIAS_ID = "SDC3Y4SEIM"
DYNAMODB_TABLE_NAME = "goaltech-poc"
NO_FEEDBACK_MESSAGES = {
    "Hi! I'm a basic Streamlit chatbot. Ask me anything.",
    "Chat cleared. How can I help?",
}

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
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": "Hi! I'm a basic Streamlit chatbot. Ask me anything.",
            }
        ]
    for message in st.session_state.messages:
        if "id" not in message:
            message["id"] = str(uuid.uuid4())


def _looks_like_document_reference(value: str) -> bool:
    lowered = value.lower()
    if lowered.startswith(("s3://", "http://", "https://", "file://", "arn:aws:s3:::")):
        return True
    if lowered.endswith(
        (
            ".pdf",
            ".doc",
            ".docx",
            ".txt",
            ".md",
            ".csv",
            ".xlsx",
            ".json",
            ".html",
            ".ppt",
            ".pptx",
        )
    ):
        return True
    if "/" in value and "." in value.rsplit("/", 1)[-1]:
        return True
    return False


def _extract_document_references(trace_payload) -> list[str]:
    document_references: list[str] = []
    seen: set[str] = set()
    interesting_keys = (
        "uri",
        "url",
        "path",
        "file",
        "source",
        "location",
        "document",
        "reference",
    )

    def walk(node, parent_key: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, key)
            return

        if isinstance(node, list):
            for item in node:
                walk(item, parent_key)
            return

        if not isinstance(node, str):
            return

        lowered_parent_key = parent_key.lower()
        is_interesting_field = any(token in lowered_parent_key for token in interesting_keys)
        if is_interesting_field and _looks_like_document_reference(node) and node not in seen:
            seen.add(node)
            document_references.append(node)

    walk(trace_payload)
    return document_references


def _extract_retrieved_chunks(trace_payload) -> list[str]:
    retrieved_chunks: list[str] = []
    seen: set[str] = set()
    content_keys = (
        "text",
        "content",
        "snippet",
        "chunk",
        "passage",
        "excerpt",
    )
    ignored_exact_values = {"orchestrationtrace", "preprocessingtrace", "postprocessingtrace"}

    def walk(node, parent_key: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, key)
            return

        if isinstance(node, list):
            for item in node:
                walk(item, parent_key)
            return

        if not isinstance(node, str):
            return

        cleaned = " ".join(node.split())
        lowered_parent_key = parent_key.lower()
        is_content_key = any(token in lowered_parent_key for token in content_keys)
        looks_like_chunk = len(cleaned) >= 40 and not _looks_like_document_reference(cleaned)
        is_not_noise = cleaned.lower() not in ignored_exact_values
        if is_content_key and looks_like_chunk and is_not_noise and cleaned not in seen:
            seen.add(cleaned)
            retrieved_chunks.append(cleaned)

    walk(trace_payload)
    return retrieved_chunks


def _save_answer_to_dynamodb(
    *,
    session_id: str,
    username: str | None,
    user_prompt: str,
    assistant_message_id: str,
    assistant_answer: str,
    consulted_documents: list[str],
    retrieved_chunks: list[str],
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        dynamodb = boto3.resource(
            service_name="dynamodb",
            region_name=st.secrets["aws"]["region"],
            aws_access_key_id=st.secrets["aws"]["access_key_id"],
            aws_secret_access_key=st.secrets["aws"]["secret_access_key"],
        )
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        table.put_item(
            Item={
                "sessionId": session_id,
                "messageId": assistant_message_id,
                "answerTimestamp": timestamp,
                "username": username or "anonymous",
                "userQuestion": user_prompt,
                "modelAnswer": assistant_answer,
                "consultedDocuments": consulted_documents,
                "retrievedChunks": retrieved_chunks,
            }
        )
    except Exception:
        logger.exception("Failed to save assistant answer to DynamoDB")


def _save_feedback_to_dynamodb(
    *,
    session_id: str,
    message_id: str,
    point: int,
    feedback_note: str,
) -> None:
    try:
        dynamodb = boto3.resource(
            service_name="dynamodb",
            region_name=st.secrets["aws"]["region"],
            aws_access_key_id=st.secrets["aws"]["access_key_id"],
            aws_secret_access_key=st.secrets["aws"]["secret_access_key"],
        )
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        table.update_item(
            Key={"sessionId": session_id, "messageId": message_id},
            UpdateExpression="SET #point = :point, #feedbackNote = :feedback_note, #feedbackUpdatedAt = :feedback_updated_at",
            ExpressionAttributeNames={
                "#point": "point",
                "#feedbackNote": "feedbackNote",
                "#feedbackUpdatedAt": "feedbackUpdatedAt",
            },
            ExpressionAttributeValues={
                ":point": point,
                ":feedback_note": feedback_note,
                ":feedback_updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception:
        logger.exception("Failed to save feedback to DynamoDB")


def stream_agent_response(prompt: str):
    try:
        response = client.invoke_agent(
            agentId=AGENT_ID,
            agentAliasId=AGENT_ALIAS_ID,
            sessionId=st.session_state.session_id,
            inputText=prompt,
            enableTrace=True,
            streamingConfigurations={"streamFinalResponse": True},
        )

        # The 'completion' key contains the EventStream
        event_stream = response.get("completion")
        if not event_stream:
            yield {"type": "chunk", "data": "No streaming response received."}
            return

        for event in event_stream:
            # 1. Handle the chunk event (this is the actual text)
            if "chunk" in event:
                data = event["chunk"]["bytes"].decode("utf-8")
                yield {"type": "chunk", "data": data}

            # 2. Handle the trace event (if enableTrace=True)
            elif "trace" in event:
                trace_data = event.get("trace", {})
                doc_refs = _extract_document_references(trace_data)
                if doc_refs:
                    yield {"type": "documents", "data": doc_refs}
                trace_chunks = _extract_retrieved_chunks(trace_data)
                if trace_chunks:
                    yield {"type": "retrieved_chunks", "data": trace_chunks}

    except ClientError as e:
        yield {"type": "chunk", "data": f"Client error: {e}"}
    except Exception as e:
        yield {"type": "chunk", "data": f"An error occurred: {e}"}


st.set_page_config(page_title="Chatbot Home", page_icon="💬", layout="centered")

if not check_password():
    st.stop()

st.markdown(
    """
    <style>
    /* Keep the unfilled track neutral, make only filled part blue. */
    div[data-baseweb="slider"] > div > div > div:nth-child(1) {
        background-color: #1e88e5 !important;
    }
    div[data-baseweb="slider"] > div > div > div:nth-child(2) {
        background-color: #eef2f7 !important;
    }
    div[data-baseweb="slider"] [role="slider"] {
        background-color: #1e88e5 !important;
        border-color: #1e88e5 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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

for message_idx, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("documents"):
            with st.expander("Getirilen belgeler", expanded=False):
                for document in message["documents"]:
                    st.markdown(f"- `{document}`")
        if message["role"] == "assistant" and message.get("retrieved_chunks"):
            with st.expander("Getirilen metinler", expanded=False):
                for chunk_idx, chunk_text in enumerate(message["retrieved_chunks"], start=1):
                    st.markdown(f"**Chunk {chunk_idx}**")
                    st.caption(chunk_text)
        if message["role"] == "assistant" and message.get("content") not in NO_FEEDBACK_MESSAGES:
            feedback = message.get("feedback", {})
            feedback_form_id = f"feedback_form_{message['id']}"
            score_key = f"feedback_score_{message['id']}"
            note_key = f"feedback_note_{message['id']}"

            with st.form(feedback_form_id):
                st.caption("Bu cevabı değerlendirin")
                score = st.slider(
                    "Puan",
                    min_value=0,
                    max_value=10,
                    value=feedback.get("score", 5),
                    key=score_key,
                )
                note = st.text_area(
                    "Geri Bildirim",
                    value=feedback.get("note", ""),
                    key=note_key,
                )
                submitted = st.form_submit_button("Gönder")

            if submitted:
                st.session_state.messages[message_idx]["feedback"] = {
                    "score": score,
                    "note": note.strip(),
                }
                _save_feedback_to_dynamodb(
                    session_id=st.session_state.session_id,
                    message_id=message["id"],
                    point=score,
                    feedback_note=note.strip(),
                )
                st.success("Feedback saved.")

user_prompt = st.chat_input("Type your message")
if user_prompt:
    st.session_state.messages.append(
        {"id": str(uuid.uuid4()), "role": "user", "content": user_prompt}
    )
    with st.chat_message("user"):
        st.markdown(user_prompt)
    with st.chat_message("assistant"):
        placeholder = st.empty()
        content = ""
        consulted_documents: list[str] = []
        seen_documents: set[str] = set()
        retrieved_chunks: list[str] = []
        seen_chunks: set[str] = set()
        for event in stream_agent_response(user_prompt):
            if event["type"] == "chunk":
                chunk = event["data"]
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8", errors="replace")
                content += chunk
            elif event["type"] == "documents":
                for document in event["data"]:
                    if document not in seen_documents:
                        seen_documents.add(document)
                        consulted_documents.append(document)
            elif event["type"] == "retrieved_chunks":
                for chunk_text in event["data"]:
                    if chunk_text not in seen_chunks:
                        seen_chunks.add(chunk_text)
                        retrieved_chunks.append(chunk_text)
            placeholder.markdown(content)
        if consulted_documents:
            with st.expander("Documents consulted", expanded=False):
                for document in consulted_documents:
                    st.markdown(f"- `{document}`")
        if retrieved_chunks:
            with st.expander("Retrieved chunks", expanded=False):
                for idx, chunk_text in enumerate(retrieved_chunks, start=1):
                    st.markdown(f"**Chunk {idx}**")
                    st.caption(chunk_text)
    assistant_message = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": content,
        "documents": consulted_documents,
        "retrieved_chunks": retrieved_chunks,
    }
    st.session_state.messages.append(assistant_message)
    _save_answer_to_dynamodb(
        session_id=st.session_state.session_id,
        username=st.session_state.get("username"),
        user_prompt=user_prompt,
        assistant_message_id=assistant_message["id"],
        assistant_answer=assistant_message["content"],
        consulted_documents=assistant_message["documents"],
        retrieved_chunks=assistant_message["retrieved_chunks"],
    )
    st.rerun()
