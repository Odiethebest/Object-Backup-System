"""Replicator stack for S3 EventBridge processing."""

from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from constructs import Construct


class ReplicatorStack(Stack):
    """Defines the Replicator lambda and S3 event rule."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        src_bucket: s3.IBucket,
        dst_bucket: s3.IBucket,
        table: dynamodb.ITable,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.src_bucket = src_bucket
        self.dst_bucket = dst_bucket
        self.table = table
        self.replicator = lambda_.Function(
            self,
            "Replicator",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambdas/replicator"),
            timeout=Duration.seconds(30),
            environment={
                "DST_BUCKET_NAME": dst_bucket.bucket_name,
                "TABLE_NAME": table.table_name,
            },
        )

        src_bucket.grant_read(self.replicator)
        dst_bucket.grant_read_write(self.replicator)
        table.grant_read_write_data(self.replicator)

        self.s3_events_rule = events.Rule(
            self,
            "S3EventsRule",
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=["Object Created", "Object Deleted"],
                detail={"bucket": {"name": [src_bucket.bucket_name]}},
            ),
            targets=[targets.LambdaFunction(self.replicator)],
        )
