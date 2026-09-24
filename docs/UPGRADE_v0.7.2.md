# Nova 0.7.2 — Sigma modifier and corpus tooling upgrade

Implemented CIDR matching for IPv4/IPv6, case-sensitive string matching with `cased`, and literal field-to-field comparison with `fieldref`. CIDR networks are parsed and validated at rule import and cached during matching. Invalid event IPs do not match. Field references must resolve through the operator's explicit field binding; they never interpret another field's value as a wildcard or executable expression.

Supported modifier combinations include `contains|cased`, `startswith|cased`, `endswith|cased`, `fieldref|cased` and multiple-value `all` combinations. Unsupported modifier stacks still fail explicitly. CIDR inputs require prefix notation; host bits are normalized to the containing network. Comparison across IPv4 and IPv6 families does not match.

## Corrected presence semantics and migration

The Sigma 2.1 modifier appendix defines `exists` as field presence, including a present null value. Newly compiled exists rules now emit the `present` predicate. Earlier compiled packages using the internal `exists` predicate retain their previous non-null semantics for compatibility. Recompile, sign as needed, deploy consistently and activate the new rule revision to adopt the corrected behavior. Do not assume replayed historical alerts are automatically recomputed. Optional native fields are often materialized as empty strings; a presence check cannot recover a distinction the parser already discarded.

The compiler now rejects `all` on a scalar or a one-element list, as required by the modifier specification. Existing compiled packages remain loadable. These are deliberate import behavior changes.

## Check a rule corpus before installation

```bash
python tools/check_sigma_corpus.py /path/to/rules --binding examples/sigma/binding.json --output corpus-report.json
```

The tool recursively checks up to 10,000 YAML files, each bounded to 64 KiB, against one explicit logsource/field binding. Use separate batches/bindings for different telemetry sources. It records file and compiled-rule digests plus rejection reasons. It installs/enables nothing, refuses to overwrite reports, rejects external/symlink rule paths, and exits 2 if any rule is rejected. Compiler acceptance is not proof that a rule has the expected detection behavior; fixtures and reference-result comparisons are still required.

The delivered report checks only the included sample rule. No SigmaHQ corpus download, execution or parity certification is claimed.

## Upgrade and rollback

Stop writers/workers, retain a verified backup plus prior source/packages, replace source, and restart roles together. No database schema migration is required for this change. Existing packages remain compatible. Recompile only source rules whose semantics or new modifiers you intend to change, review their simulation results and activate their exact revision per tenant. Rollback uses the prior source and prior compiled packages; the older runtime cannot load the new predicate modes.

## Still open

The engine still binds only nine native fields. Regex, encoding transformations, numeric/time modifiers, neq, full correlation/filter semantics and complete OCSF support are not implemented. Broad vendor integrations, production topology/cross-store restore and live HA/immutability proof remain open. This release closes specific detection gaps, not the enterprise target.

Reference: [Sigma modifier specification 2.1.0](https://sigmahq.io/sigma-specification/specification/sigma-appendix-modifiers.html).
