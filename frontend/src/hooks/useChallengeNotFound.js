import { useApp } from '../context/AppContext';

/**
 * Whether a challenge id from the URL is unknown once the challenge list has loaded.
 *
 * Returns false while loading so a valid deep link never flashes a not-found state.
 *
 * @param {string | undefined} challengeId
 * @returns {boolean}
 */
export default function useChallengeNotFound(challengeId) {
  const { challenges, challengesLoading } = useApp();
  if (!challengeId || challengesLoading !== false || !Array.isArray(challenges)) return false;
  return !challenges.some((c) => String(c.id) === String(challengeId));
}
