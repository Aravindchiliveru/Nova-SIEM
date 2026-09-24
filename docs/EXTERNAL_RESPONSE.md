> 0.7 addition: see [Defender response](DEFENDER_RESPONSE.md) for the vendor connector and uncertain-state semantics. The generic webhook contract below still applies to connectors without a kind.

# External response activities — v0.6

Nova now executes approved HTTPS JSON activities through fixed, operator-configured endpoints. It is a generic webhook adapter, not a prebuilt EDR/firewall/IAM vendor action catalog, workflow compensation engine or exactly-once guarantee.

Configure a private file such as `/etc/nova/connectors.json`:

```json
{
  "response-service": {
    "url": "https://response.example/actions",
    "token_file": "/run/secrets/response-token",
    "tenants": ["demo"]
  }
}
```

Set `NOVA_SOAR_CONFIG=/etc/nova/connectors.json` before starting `python3 run.py` or the distributed gateway. The secret file contains only the bearer token. Use a trusted HTTPS certificate; set the runtime CA trust if needed. Endpoints, tenant grants and credential paths are operator configuration, not request parameters. No configured connector means no available external actions.

In **External actions**, an analyst selects an alert/connector and enters connector-specific parameters. A different named administrator reviews the snapshot and approves. Alternatively use:

- `GET /api/connectors` and `GET /api/external`
- `POST /api/external`: `{request_key, connector, alert_id, parameters}`
- `POST /api/external/transition`: `{id, revision, action}` where action is `approve` or `cancel`

Only jobs awaiting approval can be cancelled. Approved/running work cannot be assumed cancellable; use an independently reviewed compensating action if your provider supports one. Failed requests have no automatic operator retry button; reconcile possible remote effects before creating a new request key.

Approval is bound to the request snapshot, tenant, configured endpoint and connector grants. Changes require a new request; token content may rotate at its fixed path. Revision checks reject stale decisions. Request-key reuse with different parameters is rejected. The adapter sends no arbitrary local shell commands.

The worker commits a 60-second lease before network I/O and does not hold a database transaction across the request. It uses a stable job ID as `Idempotency-Key`; each claim increments attempts. Network errors and selected transient HTTP failures retry with bounded backoff, up to five claims including abandoned leases. Other provider rejections/configuration changes fail. Lease tokens fence stale database completion; they cannot undo a remote effect. Independent workers can overlap after lease expiry, so provider idempotency is mandatory. Socket timeout is 15 seconds, not a strict total wall-clock deadline against a trickling peer.

The endpoint receives `{tenant, alert, parameters}`. The alert is a snapshot taken when requested. A successful response must be HTTP 200 with:

```json
{"idempotency_key":"the exact request Idempotency-Key","status":"completed"}
```

The receiving service must persist deduplication **atomically with its action** and return the same completion for retries. Nova cannot make an arbitrary third-party API exactly-once. Build/review provider adapters for authentication, asset ownership, least privilege and compensation before enabling real containment. Redirects and ambient HTTP proxies are disabled. Results are not echoed into generic error logs; the linked audit records lifecycle transitions.

New external job counts and worker errors appear in authenticated health/metrics. Local and distributed gateways have a separate response worker thread, so a slow endpoint does not block event normalization. PostgreSQL uses row locks/leases but has not been tested against a real service here. The approval model separates configured names, not independently verified human identities; shared accounts undermine it.

Validation includes a real local TLS exchange, approval/RBAC/tenant tests, retry/lease/configuration-change tests and an actual process kill after a durable simulated provider effect. The simulator honored idempotency. No real vendor action was executed.
