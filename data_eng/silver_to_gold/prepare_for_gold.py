import argparse
import io
import json
import logging
from typing import Iterable, Tuple

import boto3


def list_silver_objects(s3_client, bucket: str, silver_prefix: str) -> Iterable[str]:
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=silver_prefix):
        for item in page.get("Contents", []):
            yield item["Key"]


def read_object_bytes(s3_client, bucket: str, key: str) -> bytes:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def transform_payload(raw_bytes: bytes) -> Tuple[bytes, str]:
    """
    Placeholder transform.

    Replace this with real logic that converts silver data into gold data.
    Return (payload_bytes, content_type).
    """
    # Example: passthrough as JSON Lines if already JSONL.
    # TODO: implement real transformation.
    return raw_bytes, "application/json"


def gold_key_for(silver_key: str, silver_prefix: str, gold_prefix: str) -> str:
    suffix = silver_key[len(silver_prefix) :] if silver_key.startswith(silver_prefix) else silver_key
    return f"{gold_prefix}{suffix}"


def write_object_bytes(s3_client, bucket: str, key: str, payload: bytes, content_type: str) -> None:
    s3_client.put_object(Bucket=bucket, Key=key, Body=payload, ContentType=content_type)


def process_bucket(bucket: str, silver_prefix: str, gold_prefix: str) -> None:
    s3_client = boto3.client("s3")

    for silver_key in list_silver_objects(s3_client, bucket, silver_prefix):
        if silver_key.endswith("/"):
            continue
        logging.info("Processing %s", silver_key)

        raw_bytes = read_object_bytes(s3_client, bucket, silver_key)
        payload, content_type = transform_payload(raw_bytes)

        gold_key = gold_key_for(silver_key, silver_prefix, gold_prefix)
        write_object_bytes(s3_client, bucket, gold_key, payload, content_type)
        logging.info("Wrote %s", gold_key)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transform silver data to gold in S3.")
    parser.add_argument(
        "--bucket",
        default="goaltech-poc-ai-assistant",
        help="S3 bucket name.",
    )
    parser.add_argument("--silver-prefix", default="silver/", help="Source prefix in bucket.")
    parser.add_argument("--gold-prefix", default="gold/", help="Target prefix in bucket.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    process_bucket(args.bucket, args.silver_prefix, args.gold_prefix)


if __name__ == "__main__":
    main()
