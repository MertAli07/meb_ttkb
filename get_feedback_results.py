import os
from typing import Optional

import boto3
import pandas as pd
from boto3.dynamodb.types import TypeDeserializer


def get_dynamodb_table_as_df(
    table_name: str = "goaltech-poc",
    region_name: Optional[str] = None,
    profile_name: Optional[str] = None,
) -> pd.DataFrame:
    """
    Read all items from a DynamoDB table and return them as a pandas DataFrame.

    Args:
        table_name: DynamoDB table name.
        region_name: AWS region (for example, "ap-southeast-1"). If None, boto3 defaults are used.
        profile_name: Optional AWS profile name from local credentials.

    Returns:
        pandas.DataFrame containing all table items.
    """
    if table_name.endswith("\n"):
        table_name = table_name.strip()

    session_kwargs = {}
    if profile_name:
        session_kwargs["profile_name"] = profile_name

    session = boto3.Session(**session_kwargs)
    dynamodb = session.client("dynamodb", region_name=region_name)

    deserializer = TypeDeserializer()
    items = []
    scan_kwargs = {"TableName": table_name}

    while True:
        response = dynamodb.scan(**scan_kwargs)
        raw_items = response.get("Items", [])

        for raw_item in raw_items:
            item = {k: deserializer.deserialize(v) for k, v in raw_item.items()}
            items.append(item)

        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_evaluated_key

    if not items:
        return pd.DataFrame()

    # Normalize nested objects when present.
    return pd.json_normalize(items)


if __name__ == "__main__":
    # You can override these with env vars if needed:
    # export AWS_REGION=ap-southeast-1
    # export AWS_PROFILE=your-profile
    # export DYNAMODB_TABLE=goaltech-poc
    df = get_dynamodb_table_as_df(
        table_name=os.getenv("DYNAMODB_TABLE", "goaltech-poc"),
        region_name=os.getenv("AWS_REGION"),
        profile_name=os.getenv("AWS_PROFILE"),
    )

    output_file = os.getenv("OUTPUT_XLSX", "feedback_results.xlsx")
    df.to_excel(output_file, index=False)

    print(f"Rows fetched: {len(df)}")
    print(f"Saved to Excel: {output_file}")
    print(df.head())
