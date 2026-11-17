export const WORKSPACE_WINDOW = 'lavbench-workspace';

/**
 * Open or reuse the workspace tab; call it before any await so pop-up blockers allow it.
 * @param {string} [message] Shown in a new blank tab while the launch request runs
 * @returns {{ win: Window | null, fresh: boolean }} `fresh` is false for a reused workspace tab
 */
export function openWorkspaceWindow(message = '') {
  // An empty URL reuses an open workspace tab without reloading it
  const win = window.open('', WORKSPACE_WINDOW);
  if (!win) return { win: null, fresh: false };
  let fresh = false;
  try {
    // The Hub page must not reach back into LavBench; the tab name still targets it
    win.opener = null;
    fresh = win.location.href === 'about:blank';
    if (fresh && message) {
      win.document.title = message;
      win.document.body.textContent = message;
    }
  } catch {
    // The reused tab holds the Hub, on another origin
  }
  win.focus();
  return { win, fresh };
}

/**
 * Hand the single-use launch token to the Hub in the workspace tab, with a form POST.
 * @param {{ launch_url: string, launch_token: string }} launch
 */
export function postLaunchForm(launch) {
  const form = document.createElement('form');
  form.method = 'POST';
  form.action = launch.launch_url;
  // No rel="noreferrer": the Hub refuses a launch whose Origin is null
  form.target = WORKSPACE_WINDOW;
  form.style.display = 'none';
  const token = document.createElement('input');
  token.type = 'hidden';
  token.name = 'launch_token';
  token.value = launch.launch_token;
  form.appendChild(token);
  document.body.appendChild(form);
  form.submit();
  form.remove();
}
