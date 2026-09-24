# Object Lock archive — v0.6

The new adapter targets AWS S3 Object Lock **COMPLIANCE** mode with versioning and an explicit AWS KMS key. Local filesystem archival remains a development option and is not immutable. No live AWS operation or retention-enforcement test was possible here; an SDK installation attempt returned no available package from the runtime's package source.

## Configuration

Provision/review the bucket, versioning, Object Lock and KMS permissions in your own environment. `deploy/retention/` contains JSON policy/default-lock templates with placeholders. They are not applied automatically or validated by AWS here. Review the resulting effective bucket/IAM/KMS policies and test them with the actual writer principal. The default-lock example is 30 days; choose the required period deliberately before uploading COMPLIANCE objects.

Install the optional SDK (`requirements-aws.txt`) and set:

```bash
export NOVA_ARCHIVE_MODE=s3-object-lock
export NOVA_ARCHIVE_BUCKET=your-archive-bucket
export NOVA_ARCHIVE_OWNER=123456789012
export NOVA_ARCHIVE_KMS_ARN=arn:aws:kms:REGION:ACCOUNT:key/KEY_ID
export NOVA_RETENTION_DAYS=30
```

AWS authentication uses the standard SDK credential chain. Do not put access keys into payloads or connector definitions. The optional container build is `docker build --build-arg NOVA_WITH_AWS=1 -f Dockerfile.lab .`; the image and AWS dependency set still require actual build/security validation and a deployment lockfile.

For the distributed profile, run the updated `init` migration before app roles. The archive worker uses a separate `nova-archive-worm-v1` consumer group, beginning at the earliest retained Kafka data for missing offsets. Old filesystem receipts do **not** imply immutable retention: `locked_at` and versioned object receipts are separate. Immutable archive backlog/age are reported, and required-but-pending immutable archival makes distributed health require attention. Raw events already deleted by Kafka retention require independent backfill; a new group cannot recover them.

For local mode, an operator can archive existing raw records with:

```bash
python3 -m nova.retention --db data/nova.db
```

The local command creates separate archive receipts and audit records only after remote verification. Repeat it under your supervisor to archive newly accepted rows. Ordinary local ingestion acknowledgements are SQLite durability acknowledgements, not WORM confirmations.

## Write and retry semantics

Keys include hashed tenant identity, event ID and a SHA-256 digest of the canonical raw envelope. The adapter uses a conditional create, an explicit SHA-256 checksum algorithm/value, COMPLIANCE retention and KMS encryption. It then retrieves the exact object version, checks its mode/deadline/encryption key, and compares its bytes before returning a receipt. Only an explicit conditional-write conflict may reuse an existing object, followed by the same verification. Other failures stop progress.

Retention runs from Nova's accepted `received` time plus configured days. An event already outside this interval is refused rather than silently discarded or assigned a misleading policy. Operators must choose an appropriate longer policy when archiving older backlog. Changing the configured duration does not rewrite already completed archive receipts automatically.

Distributed verification receipts and `locked_at` update in one metadata transaction before Kafka offset commit. A crash can leave remote objects without local receipts; redelivery verifies the existing version and safely records it. Object Lock does not make the entire pipeline exactly-once. Raw payloads are canonical parsed JSON, not byte-for-byte original network frames. Local/metadata receipt indexes themselves are not WORM-protected.

The adapter also provides `ObjectLockArchive.hold(key, version_id)`: it sets legal hold ON for an explicit version and verifies it. It has no release/delete operation, case-based hold UI or automatic expired-object deletion. Retention expiry alone does not guarantee that an object is deleted.

## Required live proof

With an isolated test bucket and the real writer principal, verify accepted version IDs/content, retry reuse, expiry boundaries, failed policy/owner/KMS checks, and rejection of version deletion/retention shortening during the COMPLIANCE interval. Test legal hold separately, retain API evidence outside Nova, and test backup access to the KMS key and versioned object inventory. None of these remote enforcement tests ran in this environment. Mock tests validate request/acknowledgement logic, not AWS enforcement or IAM correctness.

Official references: [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html), [PutObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html), [Object Lock considerations](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-managing.html). Object Lock protects object versions; it does not protect against losing encryption keys or replace operational recovery controls.

## Executable probe added in 0.7

`python tools/qualify_retention.py --output result.json` writes a **not_run** report without contacting AWS. With the documented environment variables pointed at a dedicated test bucket, the explicit `--execute-isolated-probe` flag writes a unique synthetic COMPLIANCE object, verifies duplicate reuse, attempts exact-version deletion/retention shortening, and checks content afterward. The object is deliberately not cleaned up and persists at least until retention expiry. The report distinguishes a 403 AccessDenied observation from independent Object Lock enforcement proof; an IAM deny alone can produce the same observation. Only synthetic objects created by that invocation are targeted. No live probe ran here.
