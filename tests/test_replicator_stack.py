"""Tests for the Replicator CDK stack."""

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.replicator_stack import ReplicatorStack
from stacks.storage_stack import StorageStack


def synthesize_replicator_template() -> Template:
    """Synthesize ReplicatorStack with storage dependencies."""
    app = cdk.App()
    storage = StorageStack(app, "StorageStack")
    replicator = ReplicatorStack(
        app,
        "ReplicatorStack",
        src_bucket=storage.src_bucket,
        dst_bucket=storage.dst_bucket,
        table=storage.table,
    )
    return Template.from_stack(replicator)


def test_replicator_stack_defines_lambda_and_s3_event_rule() -> None:
    """ReplicatorStack defines the lambda and source-bucket EventBridge rule."""
    template = synthesize_replicator_template()

    template.resource_count_is("AWS::Lambda::Function", 1)
    template.resource_count_is("AWS::Events::Rule", 1)
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "handler.handler",
            "Runtime": "python3.12",
            "Timeout": 30,
            "Environment": {
                "Variables": {
                    "DST_BUCKET_NAME": Match.any_value(),
                    "TABLE_NAME": Match.any_value(),
                }
            },
        },
    )
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {
                "source": ["aws.s3"],
                "detail-type": ["Object Created", "Object Deleted"],
                "detail": {"bucket": {"name": [Match.any_value()]}},
            },
            "Targets": Match.array_with(
                [
                    Match.object_like(
                        {
                            "Arn": {
                                "Fn::GetAtt": [
                                    Match.string_like_regexp("Replicator"),
                                    "Arn",
                                ]
                            }
                        }
                    )
                ]
            ),
        },
    )
