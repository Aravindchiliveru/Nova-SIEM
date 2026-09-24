# Durable file collection

Linux, Python 3.12. Start Nova, activate Authentication JSON in the console, then run:

```bash
python3 -m nova.collector run --spool data/collector.db --source example-ssh --adapter openssh-json --file examples/openssh.ndjson --tokens-json data/local-tokens.json
```

This tails complete newline-terminated records, stages each record durably, and sends batches to the loopback gateway. Ctrl+C stops the loop. A subsequent run resumes from the stored cursor. The collector is tied to one source and one adapter. Only one process can open a spool at a time.

For separate staging and delivery:

```bash
python3 -m nova.collector import --spool data/collector.db --source example-ssh --adapter openssh-json --file examples/openssh.ndjson
python3 -m nova.collector status --spool data/collector.db --source example-ssh --adapter openssh-json
python3 -m nova.collector send --spool data/collector.db --source example-ssh --adapter openssh-json --tokens-json data/local-tokens.json
```

`--token-file` accepts a private file containing a plain collector token instead of `--tokens-json`. Remote URLs require HTTPS. The provided gateway itself remains a loopback development service and has no built-in TLS listener. No token is passed as a command-line argument or printed. HTTP redirects are refused.

## Input contracts

| Adapter | Input | Supported scope |
|---|---|---|
| auth-json | timestamp, user, src_ip, status, message | Existing Nova authentication JSON |
| openssh-json | timestamp and message | Failed password, Accepted password, Accepted publickey messages with user, IP and port |
| windows-security-json | timestamp, event_id, TargetUserName, IpAddress | Exported JSON events 4624/4625; not native EVTX/XML or an endpoint agent |
| cloudtrail-console-json | One CloudTrail event object per line | signin.amazonaws.com / ConsoleLogin with Success or Failure |

Examples live in `examples/`. Source timestamps must include timezone. Missing or non-IP addresses are rejected; local Windows logons often have no meaningful remote IP, so not every 4624/4625 record can pass this adapter. CloudTrail Records arrays must be expanded to one event per line before input. The adapters do not fetch cloud accounts or Windows hosts themselves.

Additional adapters preserve the original parsed source object inside `original`. Successful records preserve JSON content, not exact original wire bytes. Invalid source lines are kept in spool quarantine as hexadecimal bytes, with a diagnostic reason.

## Delivery and error behavior

- File cursor and queued record commit in one FULL-durability SQLite transaction.
- A source line is limited to 64 KiB; normalized payload to 32 KiB. Incomplete trailing lines wait for a newline. Oversized lines stop at the retained cursor.
- Logical queued payload budget is 256 MiB. It does not cap SQLite metadata/WAL overhead; provision and monitor filesystem space separately.
- At most 500 records and approximately 900 KiB are sent per request.
- Deletion follows a validated acknowledgement containing the expected event IDs and acceptance/duplicate counts. Timeouts or malformed replies retain the records.
- Retry uses exponential delay plus jitter; eight unconfirmed deliveries park a record in failed state. No background retry occurs after that until `retry` is invoked. A bad record is not automatically discarded.
- After fixing the gateway/credential issue: `python3 -m nova.collector retry --spool data/collector.db --source example-ssh --adapter openssh-json`.
- Malformed-source quarantine requires inspection/correction and import through a new input file. There is no automatic quarantine rewrite or deletion command.
- File rotation, truncation, or changed committed prefix is refused rather than silently skipped. Automatic inode rotation handling is not implemented. Maintain a stable append-only file for this collector.
- Partial successful HTTP ingestion followed by a lost acknowledgement is safe to retry against Nova's idempotent ingress.
