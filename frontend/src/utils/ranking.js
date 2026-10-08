/**
 * Close the rank gaps left by filtering out entries (e.g. baselines) while
 * keeping ties: entries that share a backend rank keep sharing a display rank.
 * Input must already be in backend rank order.
 */
export function compactRanks(entries) {
  let position = 0;
  let prevBackendRank = null;
  let prevDisplayRank = null;
  return entries.map((entry) => {
    if (!entry.has_submitted || entry.rank == null) {
      return { ...entry, rank: null };
    }
    position += 1;
    const displayRank =
      prevBackendRank != null && entry.rank === prevBackendRank ? prevDisplayRank : position;
    prevBackendRank = entry.rank;
    prevDisplayRank = displayRank;
    return { ...entry, rank: displayRank };
  });
}
