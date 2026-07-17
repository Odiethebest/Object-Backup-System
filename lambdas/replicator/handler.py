"""Replicate source bucket object events into managed destination copies."""

import os
import time
import uuid
from typing import Any

import boto3


ACTIVE = "ACTIVE"
DISOWNED = "DISOWNED"
MAX_ACTIVE_COPIES = 3
DISOWNED_GSI_PK = "DISOWNED"


def now_ms() -> int:
    """Return the current epoch time in milliseconds."""
    return int(time.time() * 1000)


def random_suffix() -> str:
    """Return a short random suffix for unique destination copy keys."""
    return uuid.uuid4().hex[:12]


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle source bucket object events from EventBridge."""
    table_name = required_env("TABLE_NAME")
    dst_bucket_name = required_env("DST_BUCKET_NAME")
    table = boto3.resource("dynamodb").Table(table_name)
    s3_client = boto3.client("s3")

    return process_event(
        event,
        s3_client=s3_client,
        table=table,
        dst_bucket_name=dst_bucket_name,
        current_ms=now_ms(),
        suffix=random_suffix(),
    )


def required_env(name: str) -> str:
    """Return a required Lambda environment variable."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


def process_event(
    event: dict[str, Any],
    *,
    s3_client: Any,
    table: Any,
    dst_bucket_name: str,
    current_ms: int,
    suffix: str,
) -> dict[str, Any]:
    """Process one EventBridge S3 object event."""
    detail_type = event["detail-type"]
    detail = event["detail"]
    src_bucket_name = detail["bucket"]["name"]
    object_key = detail["object"]["key"]

    if detail_type == "Object Created":
        return replicate_put(
            s3_client=s3_client,
            table=table,
            src_bucket_name=src_bucket_name,
            dst_bucket_name=dst_bucket_name,
            object_key=object_key,
            current_ms=current_ms,
            suffix=suffix,
        )
    if detail_type == "Object Deleted":
        return mark_disowned(table=table, object_key=object_key, current_ms=current_ms)

    raise ValueError(f"Unsupported detail-type: {detail_type}")


def replicate_put(
    *,
    s3_client: Any,
    table: Any,
    src_bucket_name: str,
    dst_bucket_name: str,
    object_key: str,
    current_ms: int,
    suffix: str,
) -> dict[str, Any]:
    """Copy a source object, record it, then trim active copies to the cap."""
    copy_key = f"{object_key}/{current_ms}-{suffix}"
    s3_client.copy_object(
        Bucket=dst_bucket_name,
        Key=copy_key,
        CopySource={"Bucket": src_bucket_name, "Key": object_key},
    )
    table.put_item(
        Item={
            "pk": object_key,
            "sk": copy_key,
            "createdAt": current_ms,
            "state": ACTIVE,
        }
    )

    items = query_copies(table, object_key, consistent_read=True)
    active_items = active_copies(items)
    deleted_copy_key = None

    if len(active_items) > MAX_ACTIVE_COPIES:
        oldest = min(active_items, key=lambda item: item["createdAt"])
        deleted_copy_key = oldest["sk"]
        s3_client.delete_object(Bucket=dst_bucket_name, Key=deleted_copy_key)
        table.delete_item(Key={"pk": object_key, "sk": deleted_copy_key})

    return {
        "action": "replicated",
        "copyKey": copy_key,
        "activeCount": min(len(active_items), MAX_ACTIVE_COPIES),
        "deletedCopyKey": deleted_copy_key,
    }


def mark_disowned(*, table: Any, object_key: str, current_ms: int) -> dict[str, Any]:
    """Mark all active copies for an object as disowned."""
    items = query_copies(table, object_key, consistent_read=False)
    active_items = active_copies(items)

    for item in active_items:
        table.update_item(
            Key={"pk": object_key, "sk": item["sk"]},
            UpdateExpression="SET #state = :state, disownedAt = :disownedAt, gsiPk = :gsiPk",
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues={
                ":state": DISOWNED,
                ":disownedAt": current_ms,
                ":gsiPk": DISOWNED_GSI_PK,
            },
        )

    return {"action": "disowned", "markedCount": len(active_items)}


def query_copies(
    table: Any, object_key: str, *, consistent_read: bool
) -> list[dict[str, Any]]:
    """Query all table items for one original object name."""
    response = table.query(
        KeyConditionExpression="#pk = :pk",
        ExpressionAttributeNames={"#pk": "pk"},
        ExpressionAttributeValues={":pk": object_key},
        ConsistentRead=consistent_read,
    )
    return list(response.get("Items", []))


def active_copies(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only active copy records."""
    return [item for item in items if item.get("state") == ACTIVE]
