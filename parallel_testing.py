import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import local

import boto3
import pandas as pd
from botocore.exceptions import ClientError
import tqdm

INPUT_FILE = "./dataset/TTKB TEST.xlsx"
OUTPUT_FILE = "./dataset/TTKB TEST_answered.xlsx"
SHEET_NAME = "dataset"
QUESTION_COLUMN = "Question"
ANSWER_COLUMN = "System Answer After the Update"
RETRIEVED_DOCUMENTS_COLUMN = "Retrieved Documents"
RETRIEVED_CHUNKS_COLUMN = "Retrieved Chunks"

AGENT_ID = "CHUW9WFEUR"
AGENT_ALIAS_ID = "OS4IDX7EMV"
MAX_WORKERS = 10
_thread_local = local()


def build_client():
    return boto3.client(
        service_name="bedrock-agent-runtime",
        region_name=os.getenv("AWS_REGION", "eu-central-1"),
    )


def ask_agent(client, question: str) -> tuple[str, list[str], list[str]]:
    response = client.invoke_agent(
        agentId=AGENT_ID,
        agentAliasId=AGENT_ALIAS_ID,
        sessionId=str(uuid.uuid4()),
        inputText=question,
        enableTrace=True,
        streamingConfigurations={"streamFinalResponse": False},
    )

    completion = response.get("completion")
    if not completion:
        return "", [], []

    answer_parts = []
    retrieved_documents: list[str] = []
    retrieved_chunks: list[str] = []
    seen_documents: set[str] = set()
    seen_chunks: set[str] = set()

    for event in completion:
        if "chunk" in event and "bytes" in event["chunk"]:
            answer_parts.append(event["chunk"]["bytes"].decode("utf-8", errors="replace"))
        elif "trace" in event:
            trace_payload = event.get("trace", {})
            doc_refs = _extract_document_references(trace_payload)
            for doc_ref in doc_refs:
                if doc_ref not in seen_documents:
                    seen_documents.add(doc_ref)
                    retrieved_documents.append(doc_ref)

            chunks = _extract_retrieved_chunks(trace_payload)
            for chunk in chunks:
                if chunk not in seen_chunks:
                    seen_chunks.add(chunk)
                    retrieved_chunks.append(chunk)

    return "".join(answer_parts).strip(), retrieved_documents, retrieved_chunks


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
    extracted_chunks: list[str] = []
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
            extracted_chunks.append(cleaned)

    walk(trace_payload)
    return extracted_chunks


def get_thread_client():
    if not hasattr(_thread_local, "client"):
        _thread_local.client = build_client()
    return _thread_local.client


def process_question(idx: int, question_text: str) -> tuple[int, str, str, str]:
    try:
        answer, documents, chunks = ask_agent(get_thread_client(), question_text)
    except ClientError as exc:
        answer = f"ClientError: {exc}"
        documents = []
        chunks = []
    except Exception as exc:
        answer = f"Error: {exc}"
        documents = []
        chunks = []
    return idx, answer, " | ".join(documents), " | ".join(chunks)


def main():
    df = pd.read_excel(INPUT_FILE, sheet_name=SHEET_NAME)
    if QUESTION_COLUMN not in df.columns:
        raise ValueError(f"'{QUESTION_COLUMN}' column not found in '{SHEET_NAME}' sheet.")

    if ANSWER_COLUMN not in df.columns:
        df[ANSWER_COLUMN] = None
    if RETRIEVED_DOCUMENTS_COLUMN not in df.columns:
        df[RETRIEVED_DOCUMENTS_COLUMN] = None
    if RETRIEVED_CHUNKS_COLUMN not in df.columns:
        df[RETRIEVED_CHUNKS_COLUMN] = None

    pending_tasks: list[tuple[int, str]] = []
    for idx, question in df[QUESTION_COLUMN].items():
        if pd.isna(question):
            continue
        question_text = str(question).strip()
        if question_text:
            pending_tasks.append((idx, question_text))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_question, idx, question_text) for idx, question_text in pending_tasks]
        for future in tqdm.tqdm(as_completed(futures), total=len(futures)):
            idx, answer, retrieved_documents, retrieved_chunks = future.result()
            df.at[idx, ANSWER_COLUMN] = answer
            df.at[idx, RETRIEVED_DOCUMENTS_COLUMN] = retrieved_documents
            df.at[idx, RETRIEVED_CHUNKS_COLUMN] = retrieved_chunks

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl", mode="w") as writer:
        df.to_excel(writer, sheet_name=SHEET_NAME, index=False)

    print(
        f"Done. Answers saved to '{ANSWER_COLUMN}' in '{OUTPUT_FILE}' "
        f"using {MAX_WORKERS} parallel workers."
    )


if __name__ == "__main__":
    main()