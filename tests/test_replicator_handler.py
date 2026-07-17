"""Tests for the Replicator Lambda handler logic."""

from typing import Any

from lambdas.replicator.handler import process_event


class FakeS3Client:
    """In-memory S3 client for Replicator tests."""

    def __init__(self) -> None:
        self.copied: list[dict[str, Any]] = []
        self.deleted: list[dict[str, str]] = []

    def copy_object(self, **kwargs: Any) -> None:
        """Record an S3 copy request."""
        self.copied.append(kwargs)

    def delete_object(self, **kwargs: str) -> None:
        """Record an S3 delete request."""
        self.deleted.append(kwargs)


class FakeTable:
    """In-memory DynamoDB table for Replicator tests."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = {(item["pk"], item["sk"]): dict(item) for item in items}
        self.queries: list[dict[str, Any]] = []

    def put_item(self, *, Item: dict[str, Any]) -> None:
        """Store one item."""
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def query(self, **kwargs: Any) -> dict[str, Any]:
        """Return all items in the requested pk partition."""
        self.queries.append(kwargs)
        pk = kwargs["ExpressionAttributeValues"][":pk"]
        items = [item for (item_pk, _), item in self.items.items() if item_pk == pk]
        return {"Items": [dict(item) for item in items], "Count": len(items)}

    def delete_item(self, *, Key: dict[str, str]) -> None:
        """Delete one item by primary key."""
        self.items.pop((Key["pk"], Key["sk"]))

    def update_item(
        self,
        *,
        Key: dict[str, str],
        UpdateExpression: str,
        ExpressionAttributeNames: dict[str, str],
        ExpressionAttributeValues: dict[str, Any],
    ) -> None:
        """Apply the disowned-state update used by Replicator."""
        item = self.items[(Key["pk"], Key["sk"])]
        item["state"] = ExpressionAttributeValues[":state"]
        item["disownedAt"] = ExpressionAttributeValues[":disownedAt"]
        item["gsiPk"] = ExpressionAttributeValues[":gsiPk"]


def eventbridge_s3_event(detail_type: str, key: str) -> dict[str, Any]:
    """Build an EventBridge S3 object event."""
    return {
        "detail-type": detail_type,
        "detail": {
            "bucket": {"name": "source-bucket"},
            "object": {"key": key},
        },
    }


def test_fourth_put_leaves_three_active_copies() -> None:
    """A fourth PUT deletes only the oldest active copy."""
    table = FakeTable(
        [
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/1000-old",
                "createdAt": 1000,
                "state": "ACTIVE",
            },
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/2000-mid",
                "createdAt": 2000,
                "state": "ACTIVE",
            },
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/3000-newer",
                "createdAt": 3000,
                "state": "ACTIVE",
            },
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/500-disowned",
                "createdAt": 500,
                "state": "DISOWNED",
            },
        ]
    )
    s3_client = FakeS3Client()

    result = process_event(
        eventbridge_s3_event("Object Created", "Assignment1.txt"),
        s3_client=s3_client,
        table=table,
        dst_bucket_name="destination-bucket",
        current_ms=4000,
        suffix="rand",
    )

    active_items = [item for item in table.items.values() if item["state"] == "ACTIVE"]
    assert result["copyKey"] == "Assignment1.txt/4000-rand"
    assert result["deletedCopyKey"] == "Assignment1.txt/1000-old"
    assert len(active_items) == 3
    assert ("Assignment1.txt", "Assignment1.txt/1000-old") not in table.items
    assert ("Assignment1.txt", "Assignment1.txt/500-disowned") in table.items
    assert table.queries[0]["ConsistentRead"] is True
    assert "FilterExpression" not in table.queries[0]
    assert s3_client.copied == [
        {
            "Bucket": "destination-bucket",
            "Key": "Assignment1.txt/4000-rand",
            "CopySource": {
                "Bucket": "source-bucket",
                "Key": "Assignment1.txt",
            },
        }
    ]
    assert s3_client.deleted == [
        {"Bucket": "destination-bucket", "Key": "Assignment1.txt/1000-old"}
    ]


def test_delete_marks_active_items_disowned_without_deleting_s3() -> None:
    """DELETE marks active records disowned and leaves copies in S3."""
    table = FakeTable(
        [
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/1000-a",
                "createdAt": 1000,
                "state": "ACTIVE",
            },
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/2000-b",
                "createdAt": 2000,
                "state": "ACTIVE",
            },
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/500-old-disowned",
                "createdAt": 500,
                "state": "DISOWNED",
                "disownedAt": 999,
                "gsiPk": "DISOWNED",
            },
        ]
    )
    s3_client = FakeS3Client()

    result = process_event(
        eventbridge_s3_event("Object Deleted", "Assignment1.txt"),
        s3_client=s3_client,
        table=table,
        dst_bucket_name="destination-bucket",
        current_ms=7000,
        suffix="ignored",
    )

    marked_items = [
        item
        for item in table.items.values()
        if item["sk"] in {"Assignment1.txt/1000-a", "Assignment1.txt/2000-b"}
    ]
    assert result == {"action": "disowned", "markedCount": 2}
    assert all(item["state"] == "DISOWNED" for item in marked_items)
    assert all(item["disownedAt"] == 7000 for item in marked_items)
    assert all(item["gsiPk"] == "DISOWNED" for item in marked_items)
    assert (
        table.items[("Assignment1.txt", "Assignment1.txt/500-old-disowned")][
            "disownedAt"
        ]
        == 999
    )
    assert table.queries[0]["ConsistentRead"] is False
    assert "FilterExpression" not in table.queries[0]
    assert s3_client.deleted == []
