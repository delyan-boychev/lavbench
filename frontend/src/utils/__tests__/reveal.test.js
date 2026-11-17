import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  firstField,
  focusField,
  focusTargetFor,
  isSingleColumn,
  returnToTrigger,
  revealElement,
  scrollToElement,
  stickyOffset,
} from '../reveal';

/** Give an element a fixed layout box, since the DOM in tests has no layout. */
function placeAt(el, { top = 0, bottom = top + 40 } = {}) {
  el.getBoundingClientRect = () => /** @type {DOMRect} */ ({ top, bottom, left: 0, right: 0 });
  return el;
}

function mount(html) {
  const root = document.createElement('div');
  root.innerHTML = html;
  document.body.appendChild(root);
  return root;
}

/** @param {boolean} wide */
function stubViewport(wide) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: wide })),
  );
}

describe('reveal helpers', () => {
  beforeEach(() => {
    vi.mocked(window.scrollTo).mockClear();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  describe('firstField', () => {
    it('returns null without a container', () => {
      expect(firstField(null)).toBeNull();
      expect(firstField(undefined)).toBeNull();
    });

    it('skips disabled, aria-hidden, hidden and tabIndex -1 inputs', () => {
      const root = mount(`
        <input id="disabled" disabled />
        <input id="hidden-type" type="hidden" />
        <div aria-hidden="true"><input id="in-hidden" /></div>
        <div hidden><input id="in-hidden-attr" /></div>
        <input id="untabbable" tabindex="-1" />
        <input id="usable" />
      `);
      expect(firstField(root)?.id).toBe('usable');
    });

    it('finds a role=combobox control', () => {
      const root = mount(`
        <select aria-hidden="true" tabindex="-1"></select>
        <button type="button" role="combobox" id="combo">Pick</button>
      `);
      expect(firstField(root)?.id).toBe('combo');
    });

    it('returns null when nothing is usable', () => {
      const root = mount('<input disabled /><p>text</p>');
      expect(firstField(root)).toBeNull();
    });
  });

  describe('focusTargetFor', () => {
    it('returns a usable field itself', () => {
      const root = mount('<input id="plain" />');
      const input = root.querySelector('#plain');
      expect(focusTargetFor(input)).toBe(input);
    });

    it("maps a SelectField's hidden select to its combobox", () => {
      // The markup SelectField renders: a combobox and a hidden native select beside it
      const root = mount(`
        <div class="field">
          <span>Label</span>
          <div><button type="button" role="combobox" id="combo">Pick</button></div>
          <select aria-hidden="true" tabindex="-1" required><option value=""></option></select>
        </div>
      `);
      expect(focusTargetFor(root.querySelector('select'))).toBe(root.querySelector('#combo'));
    });

    it("maps a FileUploader's hidden input to its file input", () => {
      const root = mount(`
        <div class="uploader">
          <label><input type="file" id="file" /></label>
          <input type="text" aria-hidden="true" tabindex="-1" id="proxy" required />
        </div>
      `);
      expect(focusTargetFor(root.querySelector('#proxy'))).toBe(root.querySelector('#file'));
    });

    it('falls back to the element when no usable field is near', () => {
      const root = mount('<div><div><div><input id="lonely" disabled /></div></div></div>');
      const input = root.querySelector('#lonely');
      expect(focusTargetFor(input)).toBe(input);
    });
  });

  describe('stickyOffset', () => {
    it('is 0 without sticky headers', () => {
      expect(stickyOffset()).toBe(0);
    });

    it('is the lowest bottom of the [data-sticky-header] bars', () => {
      const root = mount('<nav data-sticky-header></nav><div data-sticky-header></div>');
      const [navbar, bar] = root.querySelectorAll('[data-sticky-header]');
      placeAt(navbar, { top: 0, bottom: 56 });
      placeAt(bar, { top: 56, bottom: 96 });
      expect(stickyOffset()).toBe(96);
    });
  });

  describe('isSingleColumn', () => {
    it('follows the 1024px breakpoint', () => {
      stubViewport(false);
      expect(isSingleColumn()).toBe(true);
      stubViewport(true);
      expect(isSingleColumn()).toBe(false);
    });

    it('is false without matchMedia', () => {
      vi.stubGlobal('matchMedia', undefined);
      expect(isSingleColumn()).toBe(false);
    });
  });

  describe('scrollToElement', () => {
    it('does nothing for a missing element', () => {
      scrollToElement(null);
      expect(window.scrollTo).not.toHaveBeenCalled();
    });

    it('does not scroll when the top is already visible', () => {
      const el = placeAt(mount('<section></section>'), { top: 100 });
      scrollToElement(el);
      expect(window.scrollTo).not.toHaveBeenCalled();
    });

    it('scrolls an off-screen element to just below the sticky bars', () => {
      const header = mount('<div data-sticky-header></div>').firstElementChild;
      placeAt(header, { top: 0, bottom: 64 });
      const el = placeAt(mount('<section></section>'), { top: 2000 });
      scrollToElement(el);
      expect(window.scrollTo).toHaveBeenCalledWith({
        top: window.scrollY + 2000 - 64 - 16,
        behavior: 'smooth',
      });
    });

    it('scrolls an element hidden under the sticky bars', () => {
      const header = mount('<div data-sticky-header></div>').firstElementChild;
      placeAt(header, { top: 0, bottom: 64 });
      const el = placeAt(mount('<section></section>'), { top: 30 });
      scrollToElement(el);
      expect(window.scrollTo).toHaveBeenCalledTimes(1);
    });

    it('scrolls a visible element with force and never above the page top', () => {
      const el = placeAt(mount('<section></section>'), { top: 10 });
      scrollToElement(el, { force: true });
      expect(window.scrollTo).toHaveBeenCalledWith({
        top: Math.max(0, window.scrollY + 10 - 16),
        behavior: 'smooth',
      });
    });
  });

  describe('revealElement', () => {
    it('focuses the first field with focus "field"', () => {
      const root = mount('<input id="a" disabled /><input id="b" />');
      revealElement(root, { focus: 'field' });
      expect(document.activeElement?.id).toBe('b');
    });

    it('falls back to the heading when there is no field', () => {
      const root = mount('<h2>Details</h2><p>Read only</p>');
      revealElement(root, { focus: 'field' });
      const heading = root.querySelector('h2');
      expect(heading).toHaveAttribute('tabindex', '-1');
      expect(heading).toHaveFocus();
    });

    it('focuses a [data-reveal-heading] element with focus "heading"', () => {
      const root = mount('<span data-reveal-heading>Submission 7</span><input />');
      revealElement(root, { focus: 'heading' });
      expect(root.querySelector('[data-reveal-heading]')).toHaveFocus();
    });

    it('focuses the h1-h3 heading with focus "heading", not the field', () => {
      const root = mount('<input /><h2>Details</h2>');
      revealElement(root, { focus: 'heading' });
      expect(root.querySelector('h2')).toHaveFocus();
    });

    it('keeps an existing tabindex on the heading', () => {
      const root = mount('<h3 tabindex="0">Title</h3>');
      revealElement(root, { focus: 'heading' });
      expect(root.querySelector('h3')).toHaveAttribute('tabindex', '0');
    });

    it('focuses the element itself with focus "self"', () => {
      const root = mount('<div tabindex="-1" id="panel"><input /></div>');
      const panel = root.querySelector('#panel');
      revealElement(panel, { focus: 'self' });
      expect(panel).toHaveFocus();
    });

    it('scrolls without moving the focus by default', () => {
      const root = placeAt(mount('<input id="x" />'), { top: 3000 });
      revealElement(root);
      expect(window.scrollTo).toHaveBeenCalledTimes(1);
      expect(root.querySelector('#x')).not.toHaveFocus();
    });

    it('does nothing in a two-column layout with singleColumnOnly', () => {
      stubViewport(true);
      const root = placeAt(mount('<input id="x" />'), { top: 3000 });
      revealElement(root, { focus: 'field', singleColumnOnly: true });
      expect(window.scrollTo).not.toHaveBeenCalled();
      expect(root.querySelector('#x')).not.toHaveFocus();
    });

    it('reveals in a single-column layout with singleColumnOnly', () => {
      stubViewport(false);
      const root = placeAt(mount('<input id="x" />'), { top: 3000 });
      revealElement(root, { focus: 'field', singleColumnOnly: true });
      expect(window.scrollTo).toHaveBeenCalledTimes(1);
      expect(root.querySelector('#x')).toHaveFocus();
    });

    it('ignores a missing element', () => {
      expect(() => revealElement(null, { focus: 'field' })).not.toThrow();
      expect(window.scrollTo).not.toHaveBeenCalled();
    });
  });

  describe('focusField', () => {
    it('focuses a plain input', () => {
      const root = mount('<div><input id="name" /></div>');
      focusField(root.querySelector('#name'));
      expect(root.querySelector('#name')).toHaveFocus();
    });

    it('focuses the combobox for a hidden select and scrolls to its field', () => {
      const root = mount(`
        <div>
          <div id="trigger-box"><button type="button" role="combobox" id="combo">Pick</button></div>
          <select aria-hidden="true" tabindex="-1"></select>
        </div>
      `);
      placeAt(root.querySelector('#combo'), { top: 5000 });
      focusField(root.querySelector('select'));
      expect(root.querySelector('#combo')).toHaveFocus();
      expect(window.scrollTo).toHaveBeenCalledTimes(1);
    });

    it('ignores a missing element', () => {
      expect(() => focusField(null)).not.toThrow();
    });
  });

  describe('returnToTrigger', () => {
    it('focuses the [data-return-id] trigger', () => {
      const root = mount('<button data-return-id="edit-7">Edit</button>');
      returnToTrigger('edit-7');
      expect(root.querySelector('button')).toHaveFocus();
    });

    it('scrolls to an off-screen trigger', () => {
      const button = mount('<button data-return-id="edit-7">Edit</button>').firstElementChild;
      placeAt(button, { top: 4000 });
      returnToTrigger('edit-7');
      expect(window.scrollTo).toHaveBeenCalledTimes(1);
    });

    it('is a no-op when the trigger is absent or the id is empty', () => {
      const root = mount('<button data-return-id="other">Other</button>');
      returnToTrigger('edit-7');
      returnToTrigger(null);
      returnToTrigger('');
      expect(root.querySelector('button')).not.toHaveFocus();
      expect(window.scrollTo).not.toHaveBeenCalled();
    });
  });
});
