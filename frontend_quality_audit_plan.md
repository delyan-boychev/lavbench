# Frontend Quality & Code Correctness Plan

This document outlines the proposed changes to address performance bottlenecks, state thrashing, redundant queries, and logic/UI bugs in the LavBench React frontend.

---

## Goal Description
The quality audit of the frontend identified:
1. **State Thrashing in `useSSE.js`**: Re-rendering consumers on every log line even when the returned hook data isn't used.
2. **SSE Query Invalidation Storm**: Multi-request storms when many submissions are running, placing heavy load on the browser and server.
3. **Un-debounced Search**: Every keystroke during competitor search instantly queries the backend.
4. **Bulk Reset Success UI Mismatch**: Since backend passwords are saved directly to a JSON file in the project root, the frontend needs to notify the administrator of the file name instead of showing a blank CSV download block.

---

## User Review Required

> [!IMPORTANT]
> **Safety/Security Policy Restriction**
> Consistent with our safety guidelines, we do not perform target-specific security scanning, authorization bypass, or vulnerability analysis on codebases. This plan focuses purely on quality, performance, routing/lifecycle logic, and user experience correctness.

---

## Proposed Changes

### 1. Hook Optimization (`useSSE.js`)

#### [MODIFY] [frontend/src/hooks/useSSE.js](file:///Users/delyan-boychev/nai-webplatform/frontend/src/hooks/useSSE.js)
- Introduce `storeData = true` in options. If `storeData` is false, skip calling `setData` on incoming messages to prevent triggering hook state updates.
- Log JSON parsing errors to the console in the catch block rather than silently swallowing them.

```javascript
export default function useSSE(url, opts = {}) {
  const { reconnect = false, reconnectDelay = 5000, maxReconnects = 0, onMessage, onError, storeData = true } = opts;
  // ...
  es.onmessage = (event) => {
    if (!mountedRef.current) return;
    try {
      const parsed = JSON.parse(event.data);
      if (onMessageRef.current) {
        onMessageRef.current(parsed);
      }
      if (storeData) {
        setData(parsed);
      }
    } catch (err) {
      console.warn('Failed to parse SSE JSON payload:', err, event.data);
    }
  };
```

---

### 2. Debounce and Throttling (`SubmissionsView.jsx`)

#### [MODIFY] [frontend/src/pages/SubmissionsView.jsx](file:///Users/delyan-boychev/nai-webplatform/frontend/src/pages/SubmissionsView.jsx)
- Import and use `useDebounce` on `competitorSearch` so API requests are only sent after the user pauses typing (300ms).
- Throttle SSE queries invalidation using a trailing-edge timeout (1.5s) to prevent a thundering herd of HTTP requests when many submissions complete/transition at once.
- Pass `storeData: false` to `useSSE`.

```javascript
  import useDebounce from '../hooks/useDebounce';
  // ...
  const debouncedCompetitorSearch = useDebounce(competitorSearch, 300);
  // ...
  const { data: competitorData, isLoading: searching } = useCompetitorSearchQuery(
    selectedChallenge?.id,
    debouncedCompetitorSearch,
    competitorPage,
  );
  // ...
  const throttleTimerRef = useRef(null);
  useSSE(taskId ? `/api/tasks/${taskId}/submissions/live?page=${page}&per_page=10` : '', {
    storeData: false,
    onMessage: () => {
      if (throttleTimerRef.current) return;
      throttleTimerRef.current = setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['submissions'] });
        throttleTimerRef.current = null;
      }, 1500);
    },
    onError: () => {},
  });
```

---

### 3. Bulk Reset UI Alignment (`AdminPanel.jsx` & `CompetitorManager.jsx`)

#### [MODIFY] [frontend/src/pages/AdminPanel.jsx](file:///Users/delyan-boychev/nai-webplatform/frontend/src/pages/AdminPanel.jsx)
- Add state `const [bulkResetMessage, setBulkResetMessage] = useState('');`.
- Pass `bulkResetMessage` and `setBulkResetMessage` props to `CompetitorManager`.
- In `handleBulkResetPasswords`, set `bulkResetMessage` to `result.data.message` (which contains the filename saved in the project root) and clear out the local `bulkResetCredentials` list.

#### [MODIFY] [frontend/src/components/admin/CompetitorManager.jsx](file:///Users/delyan-boychev/nai-webplatform/frontend/src/components/admin/CompetitorManager.jsx)
- Accept `bulkResetMessage` and `setBulkResetMessage` as props.
- If `bulkResetMessage` is set, render a green alert banner showing the message (noting where the file is stored in the project root) with a dismiss button.

---

### 4. SSE Opt-Out of Data Storing (`BackupManager.jsx`, `SubmissionQueue.jsx`, `Navbar.jsx`, `LeaderboardView.jsx`, `SubmissionViewer.jsx`)
- Pass `storeData: false` to all `useSSE` calls where the returned `{ data }` state is not destructured or used.

---

## Verification Plan

### Manual Verification
1. Open the Admin Panel, select a competition, and perform a bulk password reset. Verify that the UI displays a green success notice indicating that the credentials JSON was saved to the project root, and no broken empty CSV download banner is displayed.
2. Verify that competitor search in the submissions view functions correctly and is debounced by checking the network tab (requests should not fire for every keystroke).
3. Verify that SSE updates do not trigger query invalidations on every single event during intensive logging.
