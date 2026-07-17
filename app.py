"""CDK application entrypoint for the object backup system."""

import aws_cdk as cdk

from stacks.cleaner_stack import CleanerStack
from stacks.replicator_stack import ReplicatorStack
from stacks.storage_stack import StorageStack


app = cdk.App()

storage = StorageStack(app, "StorageStack")
ReplicatorStack(
    app,
    "ReplicatorStack",
    src_bucket=storage.src_bucket,
    dst_bucket=storage.dst_bucket,
    table=storage.table,
)
CleanerStack(
    app,
    "CleanerStack",
    dst_bucket=storage.dst_bucket,
    table=storage.table,
)

app.synth()
