import React from 'react';
import Badge from './Badge';
import { isPlatformFailure } from '../../utils/submissionStatus';

// The status badge of a submission row, plus "Platform error" when the platform, not the
// code, failed. The pair never wraps, so a phone-width row keeps one line
export default function SubmissionStatusBadges({ submission }) {
  return (
    <span className="inline-flex items-center gap-1.5 flex-shrink-0">
      <Badge status={submission.status} />
      {isPlatformFailure(submission) && <Badge status="failed_infra" />}
    </span>
  );
}
