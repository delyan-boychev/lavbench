import { describe, it, expect, vi, afterEach } from 'vitest';
import { WORKSPACE_WINDOW, openWorkspaceWindow, postLaunchForm } from '../workspaceLaunch';

describe('openWorkspaceWindow', () => {
  afterEach(() => vi.restoreAllMocks());

  it('opens a named blank tab and writes the waiting message into it', () => {
    const doc = document.implementation.createHTMLDocument('');
    const win = {
      location: { href: 'about:blank' },
      document: doc,
      focus: vi.fn(),
      opener: window,
    };
    const open = vi.spyOn(window, 'open').mockReturnValue(/** @type {any} */ (win));
    const result = openWorkspaceWindow('Opening your workspace...');
    expect(open).toHaveBeenCalledWith('', WORKSPACE_WINDOW);
    expect(win.opener).toBeNull();
    expect(result).toEqual({ win, fresh: true });
    expect(doc.body.textContent).toBe('Opening your workspace...');
    expect(win.focus).toHaveBeenCalled();
  });

  it('reuses an open workspace tab on the Hub without touching it', () => {
    const win = {
      get location() {
        throw new DOMException('cross-origin', 'SecurityError');
      },
      set opener(_value) {
        throw new DOMException('cross-origin', 'SecurityError');
      },
      focus: vi.fn(),
    };
    vi.spyOn(window, 'open').mockReturnValue(/** @type {any} */ (win));
    expect(openWorkspaceWindow('Opening')).toEqual({ win, fresh: false });
    expect(win.focus).toHaveBeenCalled();
  });

  it('reports a blocked pop-up', () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    expect(openWorkspaceWindow('Opening')).toEqual({ win: null, fresh: false });
  });
});

describe('postLaunchForm', () => {
  afterEach(() => vi.restoreAllMocks());

  function captureForm() {
    const forms = [];
    vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(function submit() {
      forms.push(this.cloneNode(true));
    });
    return forms;
  }

  it('POSTs the token to the Hub in the workspace tab, with the Origin kept', () => {
    const forms = captureForm();
    postLaunchForm({ launch_url: 'https://hub.example/hub/launch', launch_token: 'tok' });
    expect(forms).toHaveLength(1);
    const form = forms[0];
    expect(form.method.toLowerCase()).toBe('post');
    expect(form.action).toBe('https://hub.example/hub/launch');
    expect(form.target).toBe(WORKSPACE_WINDOW);
    expect(form.getAttribute('rel')).toBeNull();
    const input = form.querySelector('input[name=launch_token]');
    expect(input.type).toBe('hidden');
    expect(input.value).toBe('tok');
    expect(document.querySelector('form')).toBeNull();
  });
});
