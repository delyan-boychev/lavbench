# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately:

- **GitHub Advisory**: https://github.com/delyan-boychev/lavbench/security/advisories/new
- **Email**: [delyan.boychev05@gmail.com](mailto:delyan.boychev05@gmail.com)

Please do **not** open a public issue for security vulnerabilities.

## Response Timeline

- We will acknowledge your report within 48 hours.
- We will provide a fix timeline within 5 business days.
- You can expect regular updates on the remediation progress.

## Supported Versions

| Version | Security fixes |
| --- | --- |
| Latest release | Yes |
| Older releases | No; upgrade to the latest release |

Fixes land on `main` first and ship in the next release.

## Security Notifications

Every security fix ships in a release and is announced as a GitHub security
advisory. To hear about them, deployers should:

- Watch the repository with **Watch > Custom > Releases**, or follow the
  [releases feed](https://github.com/delyan-boychev/lavbench/releases.atom).
- Check the published
  [security advisories](https://github.com/delyan-boychev/lavbench/security/advisories),
  which name the affected and fixed versions.

## Automated Security Checks

CI audits pinned Python and production npm dependencies and scans the repository
and built container images for high and critical vulnerabilities, leaked secrets,
and configuration problems. Workflows run with a read-only token by default, pin
every action by commit SHA and are checked with zizmor. Run the dependency checks
locally with:

```bash
cd backend && pip-audit -r requirements.txt
cd ../frontend && npm run audit:security
```

The npm check has no allowlisted advisories; the previous React Router RSC-mode
exception was removed when the frontend migrated to `react-router@8.3.0`, which
patches it and the follow-up `GHSA-qwww-vcr4-c8h2`. If server rendering or React
Server Components are ever introduced, re-audit the router pin before shipping.

Generated `.env`, `worker.env`, administrator credentials, API tokens, and private
keys must use mode `0600`. Setup scripts create them under `umask 077`; copied
credentials must retain the same permissions.
