# SARIF Security Findings Adapter

Imports a local SARIF 2.1.0 report explicitly and keeps only rule IDs,
severity, safe file/range locations, and tool metadata. Full messages and
secrets are not retained. Exact file + complete range + rule ID is required
for confirmed code mapping; absence of a finding is not a security claim.
