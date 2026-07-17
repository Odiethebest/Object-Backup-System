"""Tests for the Cleaner CDK stack."""

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.cleaner_stack import CleanerStack
from stacks.storage_stack import StorageStack


def synthesize_cleaner_template() -> Template:
    """Synthesize CleanerStack with storage dependencies."""
    app = cdk.App()
    storage = StorageStack(app, "StorageStack")
    cleaner = CleanerStack(
        app,
        "CleanerStack",
        dst_bucket=storage.dst_bucket,
        table=storage.table,
    )
    return Template.from_stack(cleaner)


def test_cleaner_stack_defines_lambda_and_schedule() -> None:
    """CleanerStack defines the lambda and one-minute schedule rule."""
    template = synthesize_cleaner_template()

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
            "ScheduleExpression": "rate(1 minute)",
            "Targets": Match.array_with(
                [
                    Match.object_like(
                        {
                            "Arn": {
                                "Fn::GetAtt": [
                                    Match.string_like_regexp("Cleaner"),
                                    "Arn",
                                ]
                            }
                        }
                    )
                ]
            ),
        },
    )
