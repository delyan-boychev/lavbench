/**
 * Whether a submission failed for platform reasons (enqueue, worker, Docker, GPU) rather
 * than because of the competitor's code. Its status stays "failed"; the detailed status
 * carries the cause.
 * @param {{ detailed_status?: string | null } | null | undefined} submission
 */
export function isPlatformFailure(submission) {
  return submission?.detailed_status === 'failed_infra';
}
