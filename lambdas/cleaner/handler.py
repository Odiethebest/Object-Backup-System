"""Clean disowned destination bucket copies after the grace period."""

import os
import time
from typing import Any

import boto3


DISOWNED_GSI_PK = "DISOWNED"
DISOWNED_INDEX_NAME = "DisownedIndex"
DISOWNED_GRACE_MS = 10_000


def now_ms() -> int:
    """Return the current epoch time in milliseconds."""
    return int(time.time() * 1000)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Clean disowned copies; the event payload is intentionally ignored."""
    table_name = required_env("TABLE_NAME")
    dst_bucket_name = required_env("DST_BUCKET_NAME")
    table = boto3.resource("dynamodb").Table(table_name)
    s3_client = boto3.client("s3")

    return clean_disowned_copies(
        s3_client=s3_client,
        table=table,
        dst_bucket_name=dst_bucket_name,
        current_ms=now_ms(),
    )


def required_env(name: str) -> str:
    """Return a required Lambda environment variable."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


def clean_disowned_copies(
    *,
    s3_client: Any,
    table: Any,
    dst_bucket_name: str,
    current_ms: int,
) -> dict[str, int]:
    """Delete disowned copies older than the grace period."""
    cutoff_ms = current_ms - DISOWNED_GRACE_MS
    deleted_count = 0

    for item in query_expired_disowned_items(table=table, cutoff_ms=cutoff_ms):
        copy_key = item["sk"]
        s3_client.delete_object(Bucket=dst_bucket_name, Key=copy_key)
        table.delete_item(Key={"pk": item["pk"], "sk": copy_key})
        deleted_count += 1

    return {"deletedCount": deleted_count}


def query_expired_disowned_items(*, table: Any, cutoff_ms: int) -> list[dict[str, Any]]:
    """Query all disowned items older than the cutoff using pagination."""
    items: list[dict[str, Any]] = []
    exclusive_start_key = None

    while True:
        query_kwargs: dict[str, Any] = {
            "IndexName": DISOWNED_INDEX_NAME,
            "KeyConditionExpression": "#gsiPk = :gsiPk AND #disownedAt < :cutoff",
            "ExpressionAttributeNames": {
                "#gsiPk": "gsiPk",
                "#disownedAt": "disownedAt",
            },
            "ExpressionAttributeValues": {
                ":gsiPk": DISOWNED_GSI_PK,
                ":cutoff": cutoff_ms,
            },
        }
        if exclusive_start_key is not None:
            query_kwargs["ExclusiveStartKey"] = exclusive_start_key

        response = table.query(**query_kwargs)
        items.extend(response.get("Items", []))
        exclusive_start_key = response.get("LastEvaluatedKey")
        if exclusive_start_key is None:
            return items
