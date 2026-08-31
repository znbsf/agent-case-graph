# Security

## Supported versions

Security fixes are applied to the latest release and the `main` branch.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not put
credentials, private ledgers, customer data, internal paths, or exploit details
in a public issue. If private reporting is unavailable, open a minimal public
issue that contains no sensitive material and asks the maintainers for a private
channel.

## Data boundary

Agent Case Graph stores labels, attributes, source references, and imported
evidence exactly as supplied by the caller. Review a Ledger before publishing
it. Prefer relative, de-identified source references and keep generated HTML or
JSON private when the source Ledger is private.

The runtime computes readiness and validates checkpoints. It does not execute
arbitrary shell commands or automatically replay side-effecting actions.
