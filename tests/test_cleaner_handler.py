"""Tests for the Cleaner Lambda handler logic."""

from typing import Any

from lambdas.cleaner.handler import clean_disowned_copies


class FakeS3Client:
    """In-memory S3 client that records delete calls."""

    def __init__(self, operations: list[tuple[str, str]]) -> None:
        self.operations = operations

    def delete_object(self, **kwargs: str) -> None:
        """Record an S3 delete request before the table delete."""
        self.operations.append(("s3_delete", kwargs["Key"]))


class FakeTable:
    """In-memory DynamoDB table with paginated GSI query behavior."""

    def __init__(
        self,
        items: list[dict[str, Any]],
        operations: list[tuple[str, str]],
        page_size: int,
    ) -> None:
        self.items = {(item["pk"], item["sk"]): dict(item) for item in items}
        self.operations = operations
        self.page_size = page_size
        self.queries: list[dict[str, Any]] = []

    def query(self, **kwargs: Any) -> dict[str, Any]:
        """Return expired disowned items in deterministic pages."""
        self.queries.append(kwargs)
        cutoff = kwargs["ExpressionAttributeValues"][":cutoff"]
        start_key = kwargs.get("ExclusiveStartKey")
        expired_items = sorted(
            [
                item
                for item in self.items.values()
                if item.get("gsiPk") == "DISOWNED" and item["disownedAt"] < cutoff
            ],
            key=lambda item: (item["disownedAt"], item["sk"]),
        )
        start_index = self.start_index(expired_items, start_key)
        page = expired_items[start_index : start_index + self.page_size]
        response: dict[str, Any] = {"Items": [dict(item) for item in page]}

        next_index = start_index + self.page_size
        if next_index < len(expired_items):
            next_item = expired_items[next_index - 1]
            response["LastEvaluatedKey"] = {
                "pk": next_item["pk"],
                "sk": next_item["sk"],
                "gsiPk": next_item["gsiPk"],
                "disownedAt": next_item["disownedAt"],
            }

        return response

    def delete_item(self, *, Key: dict[str, str]) -> None:
        """Delete one table item after its S3 object is deleted."""
        self.operations.append(("table_delete", Key["sk"]))
        self.items.pop((Key["pk"], Key["sk"]))

    @staticmethod
    def start_index(
        expired_items: list[dict[str, Any]], start_key: dict[str, Any] | None
    ) -> int:
        """Resolve the next page start index from LastEvaluatedKey."""
        if start_key is None:
            return 0
        for index, item in enumerate(expired_items):
            if item["pk"] == start_key["pk"] and item["sk"] == start_key["sk"]:
                return index + 1
        raise AssertionError("ExclusiveStartKey did not match an expired item")


def test_cleaner_deletes_expired_items_after_s3_delete() -> None:
    """Expired disowned copies are deleted from S3 before table rows."""
    operations: list[tuple[str, str]] = []
    table = FakeTable(
        items=[
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/1000-a",
                "disownedAt": 1000,
                "gsiPk": "DISOWNED",
            },
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/2000-b",
                "disownedAt": 2000,
                "gsiPk": "DISOWNED",
            },
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/20500-too-new",
                "disownedAt": 20_500,
                "gsiPk": "DISOWNED",
            },
        ],
        operations=operations,
        page_size=10,
    )
    s3_client = FakeS3Client(operations)

    result = clean_disowned_copies(
        s3_client=s3_client,
        table=table,
        dst_bucket_name="destination-bucket",
        current_ms=30_000,
    )

    assert result == {"deletedCount": 2}
    assert operations == [
        ("s3_delete", "Assignment1.txt/1000-a"),
        ("table_delete", "Assignment1.txt/1000-a"),
        ("s3_delete", "Assignment1.txt/2000-b"),
        ("table_delete", "Assignment1.txt/2000-b"),
    ]
    assert ("Assignment1.txt", "Assignment1.txt/20500-too-new") in table.items
    assert table.queries[0]["IndexName"] == "DisownedIndex"
    assert table.queries[0]["ExpressionAttributeValues"] == {
        ":gsiPk": "DISOWNED",
        ":cutoff": 20_000,
    }
    assert "FilterExpression" not in table.queries[0]


def test_cleaner_paginates_disowned_index_until_exhausted() -> None:
    """Cleaner follows LastEvaluatedKey across GSI query pages."""
    operations: list[tuple[str, str]] = []
    table = FakeTable(
        items=[
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/1000-a",
                "disownedAt": 1000,
                "gsiPk": "DISOWNED",
            },
            {
                "pk": "Assignment1.txt",
                "sk": "Assignment1.txt/2000-b",
                "disownedAt": 2000,
                "gsiPk": "DISOWNED",
            },
            {
                "pk": "Assignment2.txt",
                "sk": "Assignment2.txt/3000-c",
                "disownedAt": 3000,
                "gsiPk": "DISOWNED",
            },
        ],
        operations=operations,
        page_size=1,
    )
    s3_client = FakeS3Client(operations)

    result = clean_disowned_copies(
        s3_client=s3_client,
        table=table,
        dst_bucket_name="destination-bucket",
        current_ms=20_000,
    )

    assert result == {"deletedCount": 3}
    assert len(table.queries) == 3
    assert "ExclusiveStartKey" not in table.queries[0]
    assert table.queries[1]["ExclusiveStartKey"]["sk"] == "Assignment1.txt/1000-a"
    assert table.queries[2]["ExclusiveStartKey"]["sk"] == "Assignment1.txt/2000-b"
    assert operations == [
        ("s3_delete", "Assignment1.txt/1000-a"),
        ("table_delete", "Assignment1.txt/1000-a"),
        ("s3_delete", "Assignment1.txt/2000-b"),
        ("table_delete", "Assignment1.txt/2000-b"),
        ("s3_delete", "Assignment2.txt/3000-c"),
        ("table_delete", "Assignment2.txt/3000-c"),
    ]
