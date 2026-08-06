/** Fail on production npm advisories except reviewed, unreachable code paths. */

import { spawnSync } from 'node:child_process';

// No allowlisted advisories at present. When a reviewed, non-exploitable
// advisory must be tolerated, add an entry with an expiry date here.
const allowedAdvisories = new Map();

const result = spawnSync('npm', ['audit', '--omit=dev', '--json'], {
  cwd: process.cwd(),
  encoding: 'utf8',
});

if (!result.stdout) {
  process.stderr.write(result.stderr || 'npm audit returned no JSON output\n');
  process.exit(1);
}

const report = JSON.parse(result.stdout);
const unreviewed = [];
const today = new Date().toISOString().slice(0, 10);

for (const vulnerability of Object.values(report.vulnerabilities || {})) {
  for (const advisory of vulnerability.via || []) {
    if (typeof advisory === 'string') continue;
    const exception = allowedAdvisories.get(advisory.source);
    if (!exception || exception.expires < today) {
      unreviewed.push(`${advisory.name}: ${advisory.title} (${advisory.url})`);
    }
  }
}

if (unreviewed.length > 0) {
  process.stderr.write(`Unreviewed production npm advisories:\n${unreviewed.join('\n')}\n`);
  process.exit(1);
}

for (const [source, exception] of allowedAdvisories) {
  process.stdout.write(`Reviewed npm advisory ${source} until ${exception.expires}: ${exception.reason}\n`);
}
