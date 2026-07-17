"""Cleaner stack placeholder for scheduled disowned-copy cleanup."""

from typing import Any

from aws_cdk import Stack
from constructs import Construct


class CleanerStack(Stack):
    """Defines the Cleaner lambda and schedule rule."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        dst_bucket: Any,
        table: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.dst_bucket = dst_bucket
        self.table = table
        # TODO: implement per STRUCTURE.md
