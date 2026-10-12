# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.0.x   | Yes (current)      |
| 0.1.x   | Security fixes only until 2026-08-02 |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email `security@aiexponent.com` with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

**Response timeline:**
- Acknowledgement within 48 hours
- Status update within 7 days
- Fix for critical issues within 14 days

We follow coordinated disclosure: we will work with you to understand and fix the issue before public disclosure.

## Scope

In scope:
- `riskforge` CLI — arbitrary code execution, path traversal, file permission bypasses
- Audit chain integrity — hash chain bypass or forgery
- Supply chain — dependency vulnerabilities in published wheels

Out of scope:
- Vulnerabilities in the user's AI system being assessed (not our code)
- Social engineering attacks
- Physical access attacks

## Security Design Decisions

RiskForge is designed with security in mind:

- **Zero outbound calls in CLI mode** — enforced by `pytest-socket` CI gate
- **File permissions** — project files written with `chmod 600`; `.riskforge/` directory with `chmod 700`
- **No secrets in project files** — API keys handled via OS keychain (`keyring`) or environment variables
- **Audit trail integrity** — SHA-256 hash chain; `riskforge verify` exits code 2 on tampering
- **Git protection** — `riskforge init` auto-adds `.riskforge/` to `.gitignore`
- **Supply chain** — `pip-audit` gate on every release; CycloneDX SBOM and Sigstore attestation attached to every release

## Known Limitations

- Risk management files contain sensitive system architecture information. Do not commit `.riskforge/` to public repositories. RiskForge adds this to `.gitignore` automatically on `init`.
