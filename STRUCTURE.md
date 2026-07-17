# Detailed Design

This document covers the data model, the no-scan access patterns, the lambda logic, and the CDK stack architecture. Deployment and demo steps live in [STEPS.md](STEPS.md).

## Table of Contents

- [Table T Schema](#table-t-schema)
- [DisownedIndex (GSI)](#disownedindex-gsi)
- [Access Patterns — No Scan](#access-patterns--no-scan)
- [Copy Naming](#copy-naming)
- [Lambda Logic](#lambda-logic)
- [CDK Architecture](#cdk-architecture)
- [IAM Grants](#iam-grants)
- [Trigger Wiring](#trigger-wiring)
- [Edge Cases & Tradeoffs](#edge-cases--tradeoffs)

---

## Table T Schema

One DynamoDB item represents one physical copy in `Bucket Dst`. An object with three live copies has three items sharing the same partition key.

| Attribute | Type | Present when | Meaning |
|---|---|---|---|
| `pk` | String | always | Original object name, e.g. `Assignment1.txt`. Partition key. |
| `sk` | String | always | The copy's unique key in `Bucket Dst` (`copyKey`). Sort key. |
| `createdAt` | Number | always | Epoch milliseconds when the copy was made. Used to find the oldest. |
| `state` | String | always | `ACTIVE` or `DISOWNED`. Kept mainly for demo readability. |
| `disownedAt` | Number | disowned only | Epoch ms when the original was deleted. GSI sort key. |
| `gsiPk` | String | disowned only | Constant `"DISOWNED"`. GSI partition key (see below). |

Design goals:

- **Query all copies of an object** → they share `pk`, so a single `Query` on the base table returns them.
- **Uniquely address one copy** for update/delete → `(pk, sk)` where `sk = copyKey`.
- **Find the oldest copy** → compare `createdAt` across the (at most four) returned items in memory. No extra index needed at this scale.

---

## DisownedIndex (GSI)

```
DisownedIndex
  partition key : gsiPk       (String, constant "DISOWNED")
  sort key      : disownedAt  (Number, epoch ms)
  projection    : KEYS_ONLY
```

`gsiPk` and `disownedAt` are written **only when an item is disowned**, which makes this a **sparse index**: active copies carry no `gsiPk` attribute and therefore never appear in the index. The Cleaner can query the index and receive *only* disowned copies, with no `FilterExpression` and no `Scan`.

`KEYS_ONLY` projects the GSI keys plus the base-table keys (`pk`, `sk`). That is exactly what the Cleaner needs: `sk` (= `copyKey`) to delete the S3 object, and `(pk, sk)` to delete the item.

---

## Access Patterns — No Scan

Every operation resolves to a `Query`:

| # | Caller | Purpose | Index | Key condition |
|---|---|---|---|---|
| 1 | Replicator (PUT) | Count copies of an object, find the oldest | Base table | `pk = :name` with `ConsistentRead=true` |
| 2 | Replicator (DELETE) | Mark every copy of an object as disowned | Base table | `pk = :name` |
| 3 | Cleaner | Find copies disowned longer than 10 s | `DisownedIndex` | `gsiPk = "DISOWNED" AND disownedAt < :cutoff` |

`ConsistentRead=true` on pattern 1 matters: the Replicator writes the new item and then immediately counts, so a strongly consistent read is needed to avoid undercounting and mis-trimming.

There is no operation that must inspect items outside the partition it already knows the key for — hence no `Scan`.

---

## Copy Naming

Each PUT must produce a **new, unique** copy so that up to three coexist. Suggested scheme:

```
copyKey = "<originalName>/<createdAt>-<random>"
   e.g.   "Assignment1.txt/1721145600123-a1b2c3"
```

- Embedding `createdAt` makes the copies visibly ordered in the console — helpful during the demo when the TA inspects `Bucket Dst`.
- The random suffix guarantees uniqueness if two PUTs land in the same millisecond (so `sk` never collides).
- `createdAt` in the item, not just the key, is the authoritative ordering field used to pick the oldest.

---

## Lambda Logic

Pseudocode — the actual handlers are written separately. `now()` is epoch milliseconds.

### Replicator — PUT

```
name    = event.object.key
copyKey = f"{name}/{now()}-{rand()}"

s3.copy(src=Src/name, dst=Dst/copyKey)
ddb.put({ pk: name, sk: copyKey, createdAt: now(), state: "ACTIVE" })

items = ddb.query(pk = name, ConsistentRead = true)
active = [i for i in items if i.state == "ACTIVE"]

if len(active) > 3:
    oldest = min(active, key = createdAt)
    s3.delete(Dst/oldest.sk)
    ddb.delete(pk = name, sk = oldest.sk)
```

Order is deliberate: **put first, then count**, so the count includes the new copy. After the 4th PUT `len(active) == 4 > 3`, one oldest copy is removed, leaving exactly three.

### Replicator — DELETE

```
name  = event.object.key
items = ddb.query(pk = name)          # active copies of this object

for i in items where i.state == "ACTIVE":
    ddb.update(pk = name, sk = i.sk,
               SET state = "DISOWNED",
                   disownedAt = now(),
                   gsiPk = "DISOWNED")
# copies in Bucket Dst are NOT deleted here
```

### Cleaner

```
cutoff = now() - 10000                # disowned longer than 10 s

items = query(DisownedIndex,
              gsiPk = "DISOWNED" AND disownedAt < cutoff)
# paginate with LastEvaluatedKey until exhausted

for i in items:
    s3.delete(Dst/i.sk)
    ddb.delete(pk = i.pk, sk = i.sk)  # removes item from base table + GSI
```

Deleting the item removes it from both the base table and the sparse index, so future queries no longer return it. If an audit trail is preferred, replace the delete with an update that sets `state = "DELETED"` and **removes** `gsiPk` — the sparse index drops the item either way. The assignment leaves the marking scheme to the implementer; both are acceptable.

The Cleaner ignores the event payload, so it behaves identically whether fired by the schedule or invoked manually during the demo.

---

## CDK Architecture

```
StorageStack
  ├── SrcBucket   (eventBridgeEnabled: true, removalPolicy: DESTROY, autoDeleteObjects: true)
  ├── DstBucket   (removalPolicy: DESTROY, autoDeleteObjects: true)
  └── BackupTable (pk, sk; DisownedIndex; removalPolicy: DESTROY)
        exposes: srcBucket, dstBucket, table  (public readonly)

ReplicatorStack(props: srcBucket, dstBucket, table)
  ├── Replicator lambda
  └── S3EventsRule → Replicator

CleanerStack(props: dstBucket, table)
  ├── Cleaner lambda
  └── CleanerSchedule (rate 1 min) → Cleaner
```

Cross-stack references flow **one way**: the storage constructs are passed as props into the lambda stacks, and CDK auto-generates the exports and stack dependency. `StorageStack` must **not** import the lambdas — doing so would create a circular dependency through the S3 notification.

Illustrative wiring (Python):

```python
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
```

---

## IAM Grants

Use the CDK `grant*` helpers rather than hand-written policies. Note that `grant*Data` on a table automatically includes the index ARNs, so GSI queries are covered.

| Lambda | Grants | Why |
|---|---|---|
| Replicator | `srcBucket.grantRead`, `dstBucket.grantReadWrite`, `table.grantReadWriteData` | Read source for the copy; write copies and delete the oldest; put/query/update/delete items (and query `DisownedIndex`). |
| Cleaner | `dstBucket.grantReadWrite` (or `grantDelete`), `table.grantReadWriteData` | Delete copies; query the GSI and delete/update items. |

---

## Trigger Wiring

**Recommended — S3 via EventBridge.** Set `eventBridgeEnabled: true` on `SrcBucket`. In `ReplicatorStack`, create a rule matching the source bucket:

```python
events.Rule(
    self,
    "S3EventsRule",
    event_pattern=events.EventPattern(
        source=["aws.s3"],
        detail_type=["Object Created", "Object Deleted"],
        detail={"bucket": {"name": [src_bucket.bucket_name]}},
    ),
    targets=[targets.LambdaFunction(replicator)],
)
```

The handler reads `event.detail.bucket.name` and `event.detail.object.key`, and branches on `event['detail-type']` (`Object Created` → PUT, `Object Deleted` → DELETE). This is **different** from the native S3 notification shape (`event.Records[0].s3...`) — make sure the handler parses the EventBridge structure.

**Cleaner schedule.**

```python
events.Rule(
    self,
    "CleanerSchedule",
    schedule=events.Schedule.rate(Duration.minutes(1)),
    targets=[targets.LambdaFunction(cleaner)],
)
```

**Alternative — native S3 notification.** Instead of EventBridge, call `srcBucket.addEventNotification(OBJECT_CREATED / OBJECT_REMOVED, new LambdaDestination(replicator))` from `ReplicatorStack`. This works cross-stack via a CDK-managed custom resource and leaves only the schedule as an EventBridge rule.

---

## Edge Cases & Tradeoffs

- **No infinite loop.** Only `SrcBucket` has a trigger; `DstBucket` has none, so writing copies never re-fires the Replicator.
- **Count only `ACTIVE` copies.** If an object is deleted, not yet cleaned, then re-uploaded under the same name, stale disowned items still share `pk`. Filtering the copy-cap count to `state == "ACTIVE"` keeps the "three copies" rule correct. (The graded demo does delete → wait → clean → done, so it never hits this, but the guard is cheap.)
- **At-least-once delivery.** S3/EventBridge may deliver an event more than once. Because `copyKey` includes a timestamp, a duplicate PUT event would create an extra copy. Acceptable at demo scale; worth mentioning in code review as a known tradeoff (a dedupe/idempotency key would resolve it).
- **Teardown readiness.** `removalPolicy: DESTROY` on all stateful resources plus `autoDeleteObjects: true` on both buckets is required so `cdk destroy` succeeds even when buckets are non-empty — see [STEPS.md](STEPS.md#teardown).
- **Lambda timeout.** The default 3 s is too tight for an S3 copy plus several DynamoDB calls; set 10–30 s.
