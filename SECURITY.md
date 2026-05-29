# Security Policy

## Reporting A Vulnerability

Please do not open a public GitHub issue for a vulnerability in Swain.

Until a dedicated security contact is published, use GitHub private vulnerability
reporting for the repository. Include:

- a short description of the issue
- affected command or workflow
- reproduction steps using a minimal fixture when possible
- whether model workers, `.swain/`, patch generation, or file selection are
  involved

Do not send customer code, real secrets, private keys, PEM files, or private
repository archives.

## Supported Versions

Public v1 work is source-first from GitHub. Security fixes target the latest
main branch until tagged releases are published.

## Security Model

Swain is a local orchestrator. It reads files from the target repo, writes
memory under `.swain/`, and calls local Claude/Codex CLIs for model-backed
analysis. See [docs/privacy-and-trust.md](docs/privacy-and-trust.md) for the
current trust model and limitations.

`swain fix <id>` returns a reviewable patch draft. It must not apply changes
silently.
