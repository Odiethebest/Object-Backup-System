## A. Graded correctness invariants — non-negotiable
1. NO DynamoDB `Scan`, anywhere, ever. Every access is a `Query` — either on the base table by partition key `pk`, or on the `DisownedIndex` GSI. No `FilterExpression`-as-a-substitute-for-a-key either. A scan is an automatic point loss.
2. Table T schema must match `STRUCTURE.md` exactly: keys `pk` (original name) + `sk` (copyKey); attributes `createdAt`, `state`, and (disowned-only) `disownedAt`, `gsiPk`. GSI `DisownedIndex` = partition `gsiPk`, sort `disownedAt`, projection `KEYS_ONLY`, and it must be SPARSE (write `gsiPk`/`disownedAt` only when disowned).
3. Copy cap = 3, using put-then-count: write the new copy/item FIRST, then a SINGLE `Query pk` with `ConsistentRead=true` that returns the items (at least `sk`, `createdAt`, `state`) — do NOT do a count-only query and then re-query. Process the (at most ~4) items in memory: keep only `state == "ACTIVE"`, and if that ACTIVE count > 3 delete exactly the oldest by `min(createdAt)` WITHIN THE ACTIVE SUBSET (never over the full set including disowned) — from both `Bucket Dst` and the table.
4. DELETE events mark items `DISOWNED` (set `state`, `disownedAt`, `gsiPk`) and do NOT delete any copy. Physical deletion belongs only to the Cleaner.
5. Cleaner queries `DisownedIndex` for `disownedAt < now-10000ms`, paginating on `LastEvaluatedKey`. For each item, delete the S3 copy FIRST and only on success delete/tombstone the table item — NEVER the reverse (a failed S3 delete after the item is already gone leaves an orphan copy that can never be reclaimed). `DeleteObject` on a missing key is idempotent, so repeated or manual Cleaner invocations are safe. Ignore the event payload (must work when invoked manually).
6. Only `SrcBucket` has a trigger; `DstBucket` has none (no re-trigger loop).

## B. Architecture rules
7. Exactly three stacks with one-way dependency: `ReplicatorStack` and `CleanerStack` receive `SrcBucket`/`DstBucket`/`BackupTable` from `StorageStack` via props. `StorageStack` must never import the lambdas (avoids circular dependency).
8. Construct/stack names must match `README.md`'s Resource Inventory table exactly (`SrcBucket`, `DstBucket`, `BackupTable`, `Replicator`, `Cleaner`, `S3EventsRule`, `CleanerSchedule`).
9. All stateful resources get `removalPolicy: DESTROY`; both buckets get `auto_delete_objects=True` so `cdk destroy` succeeds on non-empty buckets. `SrcBucket` gets `event_bridge_enabled=True`.
10. IAM via CDK `grant*` helpers only (`grant_read`, `grant_read_write`, `grant_read_write_data`) — least privilege, no hand-written wildcard policies unless a grant genuinely can't express it (and then justify it in a comment).
11. Lambda timeout 10–30s (not the 3s default). Every AWS resource is defined in CDK; if anything is ever created manually, document it in `README.md`.
12. `app.py` must resolve a concrete account + region for the stacks (explicit `env=cdk.Environment(account, region)` or the `CDK_DEFAULT_ACCOUNT`/`CDK_DEFAULT_REGION` env vars). `auto_delete_objects=True` provisions a custom-resource Lambda that cannot deploy under an env-agnostic stack, so do not leave these stacks environment-agnostic.

## C. Code quality
13. Type hints on all functions; short, single-responsibility functions; module/function docstrings. Format with `ruff`, keep `mypy` clean.
14. No secrets, credentials, or account IDs committed. No hardcoded bucket/table physical names in handler logic — pass them via Lambda environment variables set in CDK.
15. Handlers must parse the EventBridge S3 event shape (`event['detail']['bucket']['name']`, `event['detail']['object']['key']`, branch on `event['detail-type']`) — not the native `Records[0].s3` shape.
16. Each handler ships with minimal unit tests covering its core logic: Replicator put-then-count trim (4th PUT leaves exactly 3), DELETE disown-marking, and Cleaner 10s cutoff + `LastEvaluatedKey` pagination. Use `moto` or mocks (add `moto` to `requirements-dev.txt` if used). Tests must pass before the slice is committed.

## D. Working discipline
17. `STRUCTURE.md` is the design source of truth. Do not deviate from it silently. If implementation reveals the design must change, propose the change, get my approval, and update `STRUCTURE.md` in the SAME commit as the code change.
18. Before any multi-file change, state a short plan and wait for approval. Implement incrementally in dependency order — (1) StorageStack, (2) Replicator handler + ReplicatorStack + tests, (3) Cleaner handler + CleanerStack + tests — running `cdk synth` and making an atomic, conventional-message commit (`feat:`, `fix:`, `docs:`, `chore:`) after each slice. Never write all three stacks in one pass.
19. NEVER run commands that mutate a real AWS account (`cdk deploy`, `cdk destroy`, `aws ... delete/put`) unless I explicitly ask. `cdk synth` for validation is always fine.
20. Keep `README.md` / `STRUCTURE.md` / `STEPS.md` consistent with the code at all times. If behavior changes, update the docs in the same PR/commit.