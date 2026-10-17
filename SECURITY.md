# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 2.0.x   | Yes (current)      |
| < 2.0   | No; upgrade to 2.0.x |

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
- `riskforge` CLI: arbitrary code execution, path traversal, file permission bypasses
- Integrity: a change to a project, an export, a signature or a receipt that `riskforge verify` does not detect
- Supply chain: dependency vulnerabilities in published wheels

Out of scope:
- Vulnerabilities in the user's AI system being assessed (not our code)
- Social engineering attacks
- Physical access attacks

## Security Design Decisions

RiskForge is designed with security in mind:

- **Zero outbound calls in CLI mode**: enforced by the `pytest-socket` CI gate, including the CLI processes the tests start
- **File permissions**: project files written with `chmod 600`; `.riskforge/` directory with `chmod 700`; private keys from `riskforge keygen` with `chmod 600` (Linux and macOS)
- **No secrets in project files**: RiskForge does not read or store API keys or other credentials
- **Audit trail integrity**: SHA-256 hash chain with register fingerprints; `riskforge verify` exits 2 when the log, the head file and the registers disagree, and every command that changes data refuses such a project; a full rewrite is caught only by a receipt kept outside the project (see docs/audit-chain-design.md section 3.2)
- **Git warning**: inside a git repository, `riskforge init` warns when `riskforge.yaml` is not git-ignored; it does not edit `.gitignore`
- **Supply chain**: `pip-audit` gate on every release; CycloneDX SBOM and a GitHub build-provenance attestation (Sigstore) with every release

## Known Limitations

- Risk management files contain sensitive system architecture information. Do not commit `.riskforge/` to public repositories; add `.riskforge/` and `riskforge.yaml` to `.gitignore`. `riskforge init` warns inside a git repository when the manifest is not git-ignored.
- Signing keys from `riskforge keygen` are not encrypted. Keep them outside the project and out of version control. On Linux and macOS, RiskForge refuses a private key file that other users can read, and one passed as a symbolic link. On Windows it makes neither check and does not read the file's access control list (ACL), so restrict the key file's ACL yourself so that only your user account can read it.
