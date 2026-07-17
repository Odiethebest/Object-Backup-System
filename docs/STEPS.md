# Deployment & Demo Steps

Everything a grader needs to deploy, exercise, and tear down the system. Design details are in [STRUCTURE.md](STRUCTURE.md).

## Table of Contents

- [Prerequisites](#prerequisites)
- [Deploy](#deploy)
- [Verify the Stacks](#verify-the-stacks)
- [Demo Sequence](#demo-sequence)
- [Manually Invoking the Cleaner](#manually-invoking-the-cleaner)
- [Teardown](#teardown)
- [Verification Checklist](#verification-checklist)

---

## Prerequisites

- Node.js 18+ and AWS CDK v2 (`npm install -g aws-cdk`, or use `npx cdk`)
- AWS credentials configured (`aws configure`) with permission to create the stacks
- Python 3.12 for the CDK app and Lambda handlers
- Lambda runtime dependencies installed if bundling locally (`boto3`)

## Local Dev

Create and activate a local virtual environment before running Python commands:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
```

The AWS CDK CLI is a Node tool. Use `npx cdk ...` or a globally installed `cdk`; the Python virtual environment only contains the CDK library and Python dev tooling.

The CDK app requires a concrete account and region via `CDK_DEFAULT_ACCOUNT` and `CDK_DEFAULT_REGION`. The CDK CLI normally supplies these from your AWS profile; for offline synthesis, export explicit non-secret values before running `npx cdk synth`.

The unit tests do not require `moto`. Both handlers keep their AWS I/O injectable in the core logic, so the tests use local fake S3 and DynamoDB objects.

---

## Deploy

```bash
npm install
npx cdk bootstrap          # first time in the account/region only
npx cdk deploy --all       # deploys StorageStack, ReplicatorStack, CleanerStack
```

`npx cdk` must resolve a concrete account and region. With a configured AWS profile, the CLI usually supplies `CDK_DEFAULT_ACCOUNT` and `CDK_DEFAULT_REGION` automatically; if it does not, export them before deploy or synth.

> The assignment permits manually uploading the lambda code to an S3 bucket during the demo. If you do that, note it here and in the README; all other resources must come from CDK.

---

## Verify the Stacks

1. Open the **CloudFormation** console.
2. Confirm three stacks are present: `StorageStack`, `ReplicatorStack`, `CleanerStack`. Note the **creation timestamps** (the TA checks these).
3. Under each stack's **Resources** tab, confirm the collective inventory:

| Resource type | Expected count |
|---|---|
| AWS::Lambda::Function | 2 (Replicator, Cleaner) |
| AWS::S3::Bucket | 2 (Src, Dst) |
| AWS::DynamoDB::Table | 1 (Table T, with `DisownedIndex`) |
| AWS::Events::Rule | 1–2 (schedule, plus S3 rule if EventBridge triggering is used) |

---

## Demo Sequence

Objects in `Bucket Src` are created/deleted manually. Expected results are noted inline.

**Step 1 — Create `Assignment1.txt` and `Assignment2.txt`.**
Upload both to `Bucket Src`.
> Expect: one copy of each in `Bucket Dst`. `Table T` has one item per original, each mapping `pk = <name>` to its `copyKey`.

**Step 2 — Re-upload `Assignment1.txt` (2nd time).**
> Expect: two copies of `Assignment1.txt` in `Bucket Dst`. `Table T` now has two items for `Assignment1.txt`; the newest points to the latest `copyKey`.

**Step 3 — Re-upload `Assignment1.txt` (3rd time).**
> Expect: three copies of `Assignment1.txt` in `Bucket Dst` (three items).

**Step 4 — Re-upload `Assignment1.txt` (4th time).**
> Expect: still only **three** copies — the oldest was deleted. `Table T` reflects the three most recent copies; the oldest item is gone.

**Step 5 — Delete `Assignment1.txt` from `Bucket Src`, wait > 10 s, then invoke Cleaner.**
On DELETE the Replicator marks all `Assignment1.txt` items `DISOWNED` (with `disownedAt`, `gsiPk`) — copies are **not** yet removed. After 10+ seconds, [invoke the Cleaner](#manually-invoking-the-cleaner).
> Expect: all copies of `Assignment1.txt` are deleted from `Bucket Dst`, and its items no longer appear in queries of `Table T`.

**Step 6 — Repeat Step 5 for `Assignment2.txt`.**
Delete it from `Bucket Src`, wait > 10 s, invoke Cleaner.
> Expect: all copies of `Assignment2.txt` are removed from `Bucket Dst` and cleared from `Table T`.

> Between an S3 action and checking results, allow a moment for the event to propagate to the lambda. The 10-second window in Step 5/6 is measured from the DELETE (when `disownedAt` is set) to the Cleaner run.

---

## Manually Invoking the Cleaner

The Cleaner ignores its event payload, so any invocation works.

Console: open the **Cleaner** lambda → **Test** → run with an empty event `{}`.

CLI:

```bash
aws lambda invoke \
  --function-name <CleanerFunctionName> \
  --payload '{}' \
  /dev/stdout
```

(The scheduled rule also fires it every minute; manual invocation just avoids waiting for the next tick.)

---

## Teardown

Run **before** redeploying for the demo, per Step 0 of the assignment:

```bash
npx cdk destroy --all
```

This succeeds on non-empty buckets only because both buckets are configured with `autoDeleteObjects: true` and every stateful resource uses `removalPolicy: DESTROY`. If `destroy` ever stalls on a non-empty bucket, confirm those settings in `StorageStack`.

---

## Verification Checklist

| Check | Where | Pass condition |
|---|---|---|
| Three stacks deployed | CloudFormation | `StorageStack`, `ReplicatorStack`, `CleanerStack` with recent timestamps |
| Resource inventory | Resources tab | 2 lambdas, 2 buckets, 1 table, 1–2 rules |
| Initial replication | `Bucket Dst` + `Table T` | 1 copy + 1 item per original after Step 1 |
| Copy growth | `Bucket Dst` + `Table T` | 2 then 3 copies after Steps 2–3 |
| Copy cap at 3 | `Bucket Dst` + `Table T` | Exactly 3 copies after Step 4; oldest removed |
| Disown on delete | `Table T` | Items marked `DISOWNED` with `disownedAt` after Step 5 DELETE; copies still present pre-clean |
| Cleaner reclaim | `Bucket Dst` + `Table T` | Copies deleted and items no longer queryable after Cleaner runs |
| No manual resources | code review | All AWS resources defined in CDK |
