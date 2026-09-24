# Nova 0.7: response and qualification upgrade

This is a development release. It does not complete production HA/DR, remote Object Lock proof, full OCSF/Sigma compatibility, or a broad vendor response catalog.

## Changes

- Microsoft Defender for Endpoint: isolate/unisolate a tenant-authorized machine, two-operator approval, durable submission intent, operation-ID polling, provider receipt display and explicit uncertain outcome handling. Only provider `Succeeded` completes a job.
- Sigma: wildcard/escape matching (including Windows paths), null, existence, integer-to-string equality, `1/all of` selection patterns and condition lists. Existing strict source bindings and expression limits remain.
- HA qualification: requires a separate fault verifier before and after service checks, sends ten new events during each fault, checks all twenty pre-/during-fault events through immutable archival, and records service recovery separately from cleanup time.
- Retention qualification: explicit opt-in unique synthetic COMPLIANCE object, conditional retry verification, exact-version deletion/shortening probes, and post-probe content verification. IAM denial is not labeled independent proof of Object Lock enforcement.

## Upgrade steps

1. Stop writers and workers and make a verified snapshot with matching source/packages. Retain the prior release for rollback.
2. Replace the source. Local startup creates `nova_vendor_operations`. For distributed mode, run the existing `init` migration before restarting roles; the updated shared schema includes the same table. Do not mix worker versions.
3. Existing generic connector files and imported Sigma packages remain accepted. Expanded syntax requires recompiling source Sigma rules, signing packages where required, restarting detector roles and activating the exact revision for the intended tenant.
4. Configure Defender only for an isolated test tenant first; see `DEFENDER_RESPONSE.md`. No vendor call is made merely by installing this release.
5. Update HA scenario configuration with `verify_fault_argv`; old configurations deliberately fail validation. Run the nonexecuting commands before provisioning a qualification environment.

## Evidence and remaining work

`VALIDATION.md` records the executed tests and limitations. Current benchmark results describe a single-host synthetic HTTP workload, not distributed sizing. OCSF remains the 1.4.0 authentication-logon projection from 0.6. Research retrieved a versioned upstream class descriptor, but no complete conformance validator or all-class runtime was delivered. Sigma still lacks regex, encodings/transformations, full correlation/filter semantics and broad field coverage. All unsupported constructs continue to fail explicitly.

Real HA/DR requires an isolated deployment with replicated PostgreSQL, Kafka and ClickHouse/Keeper, TLS identities, an S3 Object Lock bucket and recoverable KMS keys, plus operator-reviewed fault and restore commands. None is connected in this workspace. No production superiority claim is supported by these tests.
