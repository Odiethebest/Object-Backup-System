"""CDK application entrypoint for the object backup system."""

import os

import aws_cdk as cdk

from stacks.cleaner_stack import CleanerStack
from stacks.replicator_stack import ReplicatorStack
from stacks.storage_stack import StorageStack


def required_env(name: str) -> str:
    """Return a required environment variable for concrete stack synthesis."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set for concrete CDK stack env")
    return value


app = cdk.App()
stack_env = cdk.Environment(
    account=required_env("CDK_DEFAULT_ACCOUNT"),
    region=required_env("CDK_DEFAULT_REGION"),
)

storage = StorageStack(app, "StorageStack", env=stack_env)
ReplicatorStack(
    app,
    "ReplicatorStack",
    src_bucket=storage.src_bucket,
    dst_bucket=storage.dst_bucket,
    table=storage.table,
    env=stack_env,
)
CleanerStack(
    app,
    "CleanerStack",
    dst_bucket=storage.dst_bucket,
    table=storage.table,
    env=stack_env,
)

app.synth()
