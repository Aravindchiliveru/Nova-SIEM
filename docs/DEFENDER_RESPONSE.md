# Microsoft Defender for Endpoint response

## Supported actions

This connector implements **Full isolation** and **release from isolation** for explicitly granted machine IDs through the public `api.security.microsoft.com` endpoint. It does not implement regional/government endpoints, unmanaged-device containment, live scripts, OAuth enrollment/refresh or all Defender response actions. Provider interaction was tested using API contract doubles, not a Microsoft tenant.

Copy `examples/defender-connectors.json` to a deployment-owned configuration path. Replace the synthetic machine ID with IDs obtained from your Defender tenant; each Nova tenant has a separate explicit asset allowlist. Set `NOVA_SOAR_CONFIG` to that file. Keep the bearer access token in the absolute `token_file`; refresh it using your existing secret-management process. Do not include credentials in parameters or source control. Obtain the relevant Microsoft API permissions (`Machine.Isolate` for actions; the documented machine-action read permission for polling) through your administrator. Machine eligibility and licensing remain provider requirements.

In **External response actions**, choose the Defender connector and related alert. The UI fills a sample parameter object:

```json
{"action":"isolate","machine_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

Use `unisolate` to release isolation. A different named administrator reviews and approves the exact request. Both submission and worker execution enforce the machine grant. Alert association does not itself prove that a machine caused the alert; the approver must confirm that relationship. The source of machine authorization is the deployment-owned allowlist, not arbitrary payload data.

## Delivery and recovery

Before POST, Nova commits a durable intent with the job ID, tenant, configuration and payload digest. A successful response must identify the same machine and action. Nova persists the operation ID, then polls `GET /api/machineactions/{id}`. Only `Succeeded` becomes completed. Pending/InProgress is polled every 30 seconds for at most 960 claims; exhausted polling becomes uncertain, not a fabricated failure of the remote action. Failed/TimeOut/Cancelled is terminal failure.

Microsoft's documented API does not provide a Nova-style idempotency acknowledgement. Therefore a crash after committing intent but before saving a valid operation receipt, an ambiguous POST timeout, or an unexpected submission response becomes **uncertain**. Nova does not automatically repeat that POST. This deliberately also stops an intent committed just before a crash that prevented transmission. It favors avoiding duplicate containment over automatic retry of an unknown effect.

If uncertain, search the provider action center for the comment `Nova job JOB_ID`, verify the machine, type and result, and record the reconciliation evidence in the case. Do not request another action until the original outcome is known. Version 0.7.1 adds the verified reconciliation transition described below. Database restoration does not undo a Defender action. Expired credentials may also leave a job requiring review; tokens are never copied into receipts.

The review panel shows the sanitized provider operation receipt. No network transaction holds the database transaction open. Existing generic webhooks retain their separate acknowledgement/idempotency contract.

## References

- [Isolate machine](https://learn.microsoft.com/en-us/defender-endpoint/api/isolate-machine)
- [Release isolation](https://learn.microsoft.com/en-us/defender-endpoint/api/unisolate-machine)
- [Get machine action](https://learn.microsoft.com/en-us/defender-endpoint/api/get-machineaction-object)
- [Machine action states](https://learn.microsoft.com/en-us/defender-endpoint/api/machineaction)

## Verified reconciliation — 0.7.1

For an uncertain approved Defender job, a different administrator opens its review panel, enters the provider operation UUID and chooses **Verify and reconcile**. Nova performs a GET against the fixed Defender API. It requires matching operation UUID, granted machine, action type and exact `requestorComment` (`Nova job JOB_ID`). A missing/changed comment is rejected; the UI does not accept a manual assertion of success.

A verified Succeeded response completes the job; a terminal provider failure marks it failed. Pending/InProgress resumes polling the existing operation ID after 30 seconds with a refreshed poll budget. No POST is sent. Tenant checks, current revision, unchanged connector configuration and matching durable intent are required. The metadata transaction updates job/receipt/audit together; a concurrent revision change rejects the stale result. Transient provider failures leave the job uncertain.

The existing manage-authorized endpoint accepts:

```json
{"id":"NOVA_JOB_ID","revision":3,"action":"reconcile","operation_id":"12345678-1234-1234-1234-123456789012"}
```

This is a narrowly scoped recovery action, not permission to reissue isolation or reconcile arbitrary vendor jobs. Test it in a vendor sandbox before deployment.
