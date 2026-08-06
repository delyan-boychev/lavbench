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

Only the latest release of the `main` branch receives security patches.

## Automated Security Checks

CI audits pinned Python and production npm dependencies and scans the repository
and built container images for high and critical vulnerabilities, leaked secrets,
and configuration problems. Run the dependency checks locally with:

```bash
cd backend && pip-audit -r requirements.txt
cd ../frontend && npm run audit:security
```

The npm check contains one narrow exception for advisory `1124282`, expiring on
2026-12-31. That advisory affects React Router's React Server Components action
handler; LavBench is a client-only Vite SPA and does not import or deploy the RSC
server runtime. The exception must be removed if server rendering or React Server
Components are introduced, or when a compatible patched React Router release is
available.

Generated `.env`, `worker.env`, administrator credentials, API tokens, and private
keys must use mode `0600`. Setup scripts create them under `umask 077`; copied
credentials must retain the same permissions.
