# Validation — v0.7.2

302 automated tests pass; full log: `test-output-v0.7.2.txt`. New tests cover IPv4/IPv6 CIDR boundaries, invalid networks and event IPs, cased wildcards, literal field references, rejected bindings/modifier stacks, new versus legacy presence semantics, and nonmutating corpus reporting.

`benchmarks/sigma-import-v0.7.2.json` reports compilation of the one bundled sample rule. This is not an upstream-corpus test or full Sigma compatibility proof. Python compilation passed. No new throughput benchmark was run; all published HTTP throughput remains historical 0.7 evidence. Existing native rules do not use these new predicates.

No live provider, replicated infrastructure, remote immutability, browser rendering or OCSF conformance test was added. The production acceptance gates remain open. Earlier release evidence is preserved in the versioned validation reports.
