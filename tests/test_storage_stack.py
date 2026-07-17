"""Tests for the storage CDK stack."""

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.storage_stack import StorageStack


def synthesize_storage_template() -> Template:
    """Synthesize StorageStack for resource assertions."""
    app = cdk.App()
    stack = StorageStack(
        app,
        "StorageStack",
    )
    return Template.from_stack(stack)


def test_storage_stack_defines_two_buckets() -> None:
    """StorageStack defines source and destination buckets only."""
    template = synthesize_storage_template()

    template.resource_count_is("AWS::S3::Bucket", 2)
    template.resource_count_is("Custom::S3AutoDeleteObjects", 2)
    template.resource_count_is("Custom::S3BucketNotifications", 1)
    template.has_resource_properties(
        "Custom::S3BucketNotifications",
        {"NotificationConfiguration": {"EventBridgeConfiguration": {}}},
    )


def test_storage_stack_defines_backup_table_and_disowned_index() -> None:
    """BackupTable matches the required keys and sparse-index shape."""
    template = synthesize_storage_template()

    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "KeySchema": [
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": Match.array_with(
                [
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                    {"AttributeName": "gsiPk", "AttributeType": "S"},
                    {"AttributeName": "disownedAt", "AttributeType": "N"},
                ]
            ),
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "DisownedIndex",
                    "KeySchema": [
                        {"AttributeName": "gsiPk", "KeyType": "HASH"},
                        {"AttributeName": "disownedAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                }
            ],
        },
    )
