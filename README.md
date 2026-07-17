# Object Backup System

> An event-driven S3 backup pipeline. A **Replicator** lambda mirrors objects from a source bucket into a destination bucket (capping live copies at three), and a **Cleaner** lambda reclaims orphaned copies on a one-minute schedule. Every original-to-copy mapping is tracked in a single DynamoDB table designed so that **no `Scan` is ever needed**. All infrastructure is provisioned with AWS CDK across three stacks.

[![AWS CDK](https://img.shields.io/badge/AWS%20CDK-2.x-FF9900?logo=amazonaws)](https://docs.aws.amazon.com/cdk/)
[![Lambda](https://img.shields.io/badge/AWS%20Lambda-Python%203.12-orange?logo=awslambda)](https://docs.aws.amazon.com/lambda/)
[![Amazon S3](https://img.shields.io/badge/Amazon%20S3-Buckets-569A31?logo=amazons3)](https://aws.amazon.com/s3/)
[![DynamoDB](https://img.shields.io/badge/DynamoDB-Single%20Table%20%2B%20GSI-4053D6?logo=amazondynamodb)](https://aws.amazon.com/dynamodb/)
[![EventBridge](https://img.shields.io/badge/EventBridge-Rules-FF4F8B?logo=amazoncloudwatch)](https://aws.amazon.com/eventbridge/)

**Start here:** [Assignment Requirement](docs/midterm_requirement.md) is the source-of-truth prompt for grading scope and demo expectations.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Resource Inventory](#resource-inventory)
- [Table T Design](#table-t-design)
- [Lambda Behavior](#lambda-behavior)
- [CDK Stacks](#cdk-stacks)
- [Getting Started](#getting-started)
- [Design Decisions](#design-decisions)
- [Assignment Requirement](docs/midterm_requirement.md)
- [Detailed Design](docs/STRUCTURE.md)
- [Deployment & Demo Steps](docs/STEPS.md)

---

## Overview

The system maintains up-to-date backup copies of objects placed in a **source bucket** (`Bucket Src`) inside a **destination bucket** (`Bucket Dst`), and records the mapping between each original object and its copies in a **DynamoDB table** (`Table T`).

Two lambdas do the work:

| Lambda | Trigger | Responsibility |
|---|---|---|
| **Replicator** | S3 events on `Bucket Src` | On `PUT`, copy the object into `Bucket Dst`, keep at most three copies, and record the mapping. On `DELETE`, mark the original's copies as *disowned* (but do not delete them). |
| **Cleaner** | EventBridge schedule (every 1 min) | Find copies that have been disowned for longer than 10 seconds, delete them from `Bucket Dst`, and update `Table T` so they are no longer returned by future queries. |

The central design constraint is that **every table access is a `Query`** (by primary key or by a global secondary index), never a `Scan`. See [Table T Design](#table-t-design) and [STRUCTURE.md](docs/STRUCTURE.md) for how this is achieved.

---

## Architecture

```
        Object PUT / DELETE
┌──────────────┐   events   ┌───────────────┐        ┌────────────────────────────┐
│  Bucket Src  │ ─────────▶ │  EventBridge  │ ─────▶ │        Replicator          │
│    (S3)      │            │  (S3 rule)    │        │  PUT   → copy + trim to 3  │
└──────────────┘            └───────────────┘        │  DELETE → mark disowned    │
                                                     └───────────┬────────────────┘
                                                     copy/delete │  put / query / mark
                                              ┌──────────────────┴───────────────┐
                                              ▼                                   ▼
                                     ┌──────────────┐                   ┌──────────────────┐
                                     │  Bucket Dst  │                   │     Table T      │
                                     │    (S3)      │◀───────┐          │  pk = original   │
                                     └──────────────┘        │ delete   │  sk = copyKey    │
                                                             │ copies   │  + DisownedIndex  │
┌───────────────┐   every 1 min   ┌────────────────┐        │          └────────┬─────────┘
│  EventBridge  │ ──────────────▶ │    Cleaner     │ ───────┘   query GSI        │
│  (schedule)   │                 │  reclaim >10s  │ ───────────────────────────┘
└───────────────┘                 └────────────────┘
```

**Key property:** only `Bucket Src` has an event trigger. `Bucket Dst` has none, so writing copies never re-triggers the pipeline (no infinite loop).

---

## Resource Inventory

All resources below are created by CDK. The demo expects to see, collectively across the three stacks: **2 lambdas, 2 S3 buckets, 1 DynamoDB table, and 1–2 EventBridge rules**.

| Resource | Construct id | Stack | Purpose |
|---|---|---|---|
| Source bucket | `SrcBucket` | `StorageStack` | Holds original objects; emits S3 events. |
| Destination bucket | `DstBucket` | `StorageStack` | Holds backup copies. |
| Backup table | `BackupTable` (Table T) | `StorageStack` | Original → copy mappings + disowned/GSI. |
| Replicator lambda | `Replicator` | `ReplicatorStack` | Reacts to S3 PUT/DELETE. |
| S3 event rule | `S3EventsRule` | `ReplicatorStack` | Routes `Object Created` / `Object Deleted` to Replicator. |
| Cleaner lambda | `Cleaner` | `CleanerStack` | Reclaims disowned copies. |
| Schedule rule | `CleanerSchedule` | `CleanerStack` | Fires Cleaner every 1 minute. |

> If you use a native S3 notification instead of EventBridge for the source trigger, the count becomes **1 EventBridge rule** (the schedule only). Both approaches satisfy the assignment's "one or two EventBridge rules."

---

## Table T Design

One item = one copy. All lookups use the partition key or the GSI, so **no `Scan` is required** anywhere.

| Attribute | Type | Role | Notes |
|---|---|---|---|
| `pk` | S | Partition key | Original object name (e.g. `Assignment1.txt`). |
| `sk` | S | Sort key | Unique `copyKey` of the copy in `Bucket Dst`. |
| `createdAt` | N | — | Epoch ms; used to identify the oldest copy. |
| `state` | S | — | `ACTIVE` or `DISOWNED` (human-readable for the demo). |
| `disownedAt` | N | GSI sort key | Epoch ms; written only when disowned. |
| `gsiPk` | S | GSI partition key | Constant `"DISOWNED"`; written only when disowned (sparse). |

The table is provisioned in **on-demand mode** (`PAY_PER_REQUEST`).

**Global secondary index `DisownedIndex`** — partition key `gsiPk`, sort key `disownedAt`, projection `KEYS_ONLY`. Because `gsiPk` is present only on disowned items, the index is **sparse**: active copies never appear in it, so the Cleaner's query returns only disowned copies with no filtering.

Access patterns (all `Query`):

| Operation | Table / Index | Key condition | Scan? |
|---|---|---|---|
| Count copies of an object / find oldest | Base table | `pk = <name>` (`ConsistentRead`) | No |
| Mark all copies disowned on DELETE | Base table | `pk = <name>` | No |
| Find copies disowned > 10 s ago | `DisownedIndex` | `gsiPk = "DISOWNED" AND disownedAt < now-10000` | No |

Full rationale in [STRUCTURE.md](docs/STRUCTURE.md#table-t-schema).

---

## Lambda Behavior

**Replicator — PUT.** Copy `Src/<name>` to a uniquely named `Dst/<copyKey>`, where `copyKey = "{name}/{ms}-{rand}"`, write the mapping item to `Table T`, then query all copies of that name. If the count exceeds three, delete the oldest `ACTIVE` copy from `Bucket Dst` and its item from `Table T`, leaving the three most recent.

**Replicator — DELETE.** Query all copies of the deleted object and update each item to `state = DISOWNED`, setting `disownedAt` and `gsiPk`. The copies themselves are left untouched — deletion is the Cleaner's job.

**Cleaner.** Query `DisownedIndex` for items whose `disownedAt` is older than 10 seconds, delete each copy from `Bucket Dst` first, and only then delete the corresponding item so future queries no longer return it.

Both handlers read `DST_BUCKET_NAME` and `TABLE_NAME` from Lambda environment variables set in CDK. Their core logic is structured around injectable S3/DynamoDB clients, so unit tests use local fakes rather than `moto`.

Step-by-step logic and pseudocode: [STRUCTURE.md](docs/STRUCTURE.md#lambda-logic).

---

## CDK Stacks

Three stacks, one direction of dependency (`Replicator`/`Cleaner` depend on `Storage`):

```
StorageStack      → SrcBucket, DstBucket, BackupTable (+ DisownedIndex)
ReplicatorStack   → Replicator lambda + S3 events rule   (imports Storage refs)
CleanerStack      → Cleaner lambda + schedule rule        (imports Storage refs)
```

`StorageStack` exposes its bucket and table constructs as public properties; the other two stacks receive them via props, and CDK generates the cross-stack exports and dependency automatically. `StorageStack` never references the lambdas, which avoids a circular dependency on the S3 notification. Wiring, IAM grants, and trigger configuration are detailed in [STRUCTURE.md](docs/STRUCTURE.md#cdk-architecture).

---

## Getting Started

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
export CDK_DEFAULT_ACCOUNT=<aws-account-id>
export CDK_DEFAULT_REGION=<aws-region>
npm install
npx cdk bootstrap        # first time only
npx cdk deploy --all
```

Full deployment, the graded demo sequence, and teardown are in **[STEPS.md](docs/STEPS.md)**.

---

## Design Decisions

**Sparse GSI over a status filter.** Rather than scanning and filtering on `state`, disowned items opt *into* a single-partition index via `gsiPk`. The Cleaner's query is bounded to disowned items only, and removing the attribute (or the item) drops it back out — no `Scan`, no `FilterExpression`.

**Create-then-check for the copy cap.** The Replicator writes the new copy first, then queries and trims. After the fourth PUT the count is four (> 3), so exactly one oldest copy is deleted, leaving three — matching the demo expectation.

**Cleaner owns all copy deletion.** DELETE events only mark items disowned; physical deletion is deferred to the scheduled Cleaner. This decouples the delete path, enforces the 10-second grace window, and keeps the Replicator's responsibilities narrow.

**Manually created resources:** none. Every AWS resource is defined in CDK. Lambda code may be uploaded to an S3 bucket manually during the demo, as permitted by the assignment.

---

## Course

CS 6620 Cloud Computing — Northeastern University, Summer 2026.
