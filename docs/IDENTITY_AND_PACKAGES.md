# Optional identity and package trust

Install `requirements-security.txt` first. Production pin: cryptography 50.0.1, selected from upstream's current release. The environment could not install it; tests used installed 46.0.0. Deployment-pin validation and dependency auditing are open gates. Default local collection/search works without this optional dependency.

## Ed25519 signatures

Generate operator-owned keys in a private directory outside the source tree:

```bash
python3 -m nova.packages keygen --private-key /private/nova-signing.pem --trust /private/nova-trust.json --key-id operator-1
python3 -m nova.packages sign --private-key /private/nova-signing.pem --key-id operator-1 --package integrations/auth-json.json
python3 -m nova.packages verify --trust /private/nova-trust.json --package integrations/auth-json.json
```

Sign **every** integration and rule JSON file before enabling required mode. Signatures are stored in each package directory's `signatures/` subdirectory. Private keys are never bundled with this project. The signed message binds a Nova domain string, package basename and SHA-256 of the exact file bytes.

```bash
export NOVA_PACKAGE_TRUST=/private/nova-trust.json
export NOVA_REQUIRE_SIGNED_PACKAGES=1
python3 run.py
```

Missing/invalid signatures fail startup in required mode. A present signature always requires a trusted public key and successful verification. Unsigned default packages explicitly report unsigned-development. The operator controls trust-file contents and file permissions. Signatures authenticate packages, but do not provide key revocation distribution, anti-rollback guarantees, a marketplace or isolation for executable plugins. Packages here are declarative.

## JWT access-token validation

This is a narrowly scoped resource-server capability, **not complete OIDC browser login**. It accepts only RS256 tokens with header `typ: at+jwt` and a known `kid`. Generic JWT/ID-token types are rejected. No token-specified URL is fetched.

Create a private configuration file:

```json
{"issuer":"https://identity.example/realms/security","audience":"nova-api","jwks_file":"jwks.json","clock_skew_seconds":30}
```

Supply `jwks.json` from your trusted issuer through your normal verified configuration process. It must contain RSA signing keys (2048–8192 bits) with unique key IDs. The path is relative to the configuration file unless absolute. Set `NOVA_OIDC_CONFIG` to the configuration path and restart the gateway.

Add a local credential grant to credentials.json:

```json
{"name":"soc-analyst","tenant":"customer-a","role":"analyst","oidc_sub":"EXACT-ISSUER-SUBJECT"}
```

The bearer token's issuer, audience, signature, expiry, subject and optional nbf/iat are checked. Tenant and role claims from the token are ignored: this local grant defines authorization. Duplicate subject grants are refused. You can paste a valid access token into the existing console or use it through the API. Request rates are tracked per configured grant, so minting a new token does not reset its budget.

Opaque and subject grants can coexist. Optional `expires_at` (Unix seconds) and `revoked: true` apply to either type. Configuration changes require restart. There is no token introspection, issuer logout propagation, JWKS refresh, automatic key rotation, discovery, refresh-token handling, PKCE/login redirect flow, or tested identity-provider deployment. Use a dedicated Nova API audience and short-lived tokens. HTTP remains loopback-only by default; this does not make the development server a public enterprise gateway.

## Request controls

The server permits at most 32 concurrent request handlers, enforces body limits, and applies a per-grant token bucket (100 requests/sec, burst 200). Excess requests receive 429/503 and Retry-After. These are local bounds, not distributed quotas or a WAF. Host/origin restrictions and CSP remain enabled.
