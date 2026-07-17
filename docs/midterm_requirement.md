# Midterm Requirement

This document restates the assignment prompt in a cleaner format so the deliverables, constraints, and demo checks are easy to follow.

## Goal

Build an object backup system with:

- a source S3 bucket: `Bucket Src`
- a destination S3 bucket: `Bucket Dst`
- a DynamoDB table: `Table T`
- two Lambda functions: `Replicator` and `Cleaner`

The system maintains copies of source-bucket objects in the destination bucket and records original-to-copy mappings in DynamoDB.

## Required Runtime Behavior

### Replicator

`Replicator` is triggered by events from `Bucket Src`.

For a `PUT` event on an object such as `MyObj`:

- create a copy of `MyObj` in `Bucket Dst`
- if there are now more than three copies of `MyObj` in `Bucket Dst`, delete the oldest copy and keep the more recent ones
- update `Table T` so it records the mapping from the original object to the new copy

For a `DELETE` event on an object:

- mark the related item or items in `Table T` so they indicate the original object has been deleted and the remaining copies are now disowned
- do not delete the copies in `Bucket Dst`
- leave physical deletion to `Cleaner`

### Cleaner

`Cleaner` is triggered periodically every 1 minute.

When it runs:

- query `Table T` for copies that have been disowned for more than 10 seconds
- delete those copies from `Bucket Dst`
- update `Table T` so those deleted copies are not returned by future queries

## Data Model Constraint

Design `Table T`, including any needed indexes, so the required operations do not need a DynamoDB `Scan`.

- using `Scan` loses points
- partial credit is still possible if `Scan` is used

## Infrastructure Constraint

- all AWS resources must be created by CDK, except for the S3 objects used during the demo
- if anything is created manually in the AWS console, document it in `README.md`
- the CDK app must have at least three stacks:
  - one storage stack for the S3 buckets and DynamoDB table
  - one stack for `Replicator`
  - one stack for `Cleaner`

## Submission

Submit on GradeScope before `6pm`.

Your submission should include:

- the Lambda handler code
- the CDK code
- one or more `.zip` files

## Demo Script

### Step 0

Before the demo:

- run `cdk destroy` to delete all stacks and associated resources
- deploy the stacks again
- it is acceptable to manually upload the Lambda code to an S3 bucket

In CloudFormation, show:

- the stacks and their creation timestamps
- the Resources tabs across the stacks

The TA should be able to verify that the deployment collectively contains:

- two Lambda functions
- two S3 buckets
- one DynamoDB table
- one or two EventBridge rules

### Step 1

Create an object named `Assignment1.txt` in the source bucket.

### Step 2

Create an object named `Assignment2.txt` in the source bucket.

The TA should verify:

- there is one copy of each object in the destination bucket
- the DynamoDB table contains records mapping each original object to its copy

### Step 3

Re-upload `Assignment1.txt`.

The TA should verify:

- there are now two copies of `Assignment1.txt` in the destination bucket
- the DynamoDB records have been updated to point to the new copy

### Step 4

Re-upload `Assignment1.txt`.

### Step 5

Re-upload `Assignment1.txt` again.

The TA should verify:

- there are only three copies of `Assignment1.txt` in the destination bucket
- the oldest copy has been deleted
- the DynamoDB records have been updated to point to the latest copy

### Step 6

Delete `Assignment1.txt` from the source bucket, wait more than 10 seconds, then manually invoke `Cleaner`.

The TA should verify:

- all copies of `Assignment1.txt` have been deleted from the destination bucket

### Step 7

Repeat Step 6 for `Assignment2.txt`.

### Step 8

Code review.

## Original Intent

If anything in the implementation or supporting docs is ambiguous, treat this file as the assignment source of truth.
