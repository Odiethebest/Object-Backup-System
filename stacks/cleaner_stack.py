"""Cleaner stack for scheduled disowned-copy cleanup."""

from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from constructs import Construct


class CleanerStack(Stack):
    """Defines the Cleaner lambda and schedule rule."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        dst_bucket: s3.IBucket,
        table: dynamodb.ITable,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.dst_bucket = dst_bucket
        self.table = table
        self.cleaner = lambda_.Function(
            self,
            "Cleaner",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambdas/cleaner"),
            timeout=Duration.seconds(30),
            environment={
                "DST_BUCKET_NAME": dst_bucket.bucket_name,
                "TABLE_NAME": table.table_name,
            },
        )

        dst_bucket.grant_read_write(self.cleaner)
        table.grant_read_write_data(self.cleaner)

        self.cleaner_schedule = events.Rule(
            self,
            "CleanerSchedule",
            schedule=events.Schedule.rate(Duration.minutes(1)),
            targets=[targets.LambdaFunction(self.cleaner)],
        )
