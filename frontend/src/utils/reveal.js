/** Scrolling and focus helpers shared by editors, dialogs and lists. */

const FIELD_SELECTOR = 'input, select, textarea, [role="combobox"]';

/** @param {Element} el */
function isUsableField(el) {
  const field = /** @type {HTMLInputElement} */ (el);
  return (
    !field.disabled &&
    field.tabIndex >= 0 &&
    field.type !== 'hidden' &&
    !field.closest('[aria-hidden="true"], [hidden]')
  );
}

/**
 * The first field a person can type in or pick from, skipping the hidden native inputs
 * behind SelectField and FileUploader.
 * @param {ParentNode | null | undefined} container
 * @returns {HTMLElement | null}
 */
export function firstField(container) {
  if (!container) return null;
  const fields = Array.from(container.querySelectorAll(FIELD_SELECTOR));
  return /** @type {HTMLElement | null} */ (fields.find(isUsableField) || null);
}

/**
 * The control to focus for an invalid element: itself, or the visible control of the
 * widget that wraps it (the combobox of a SelectField, the file input of a FileUploader).
 * @param {Element} el
 * @returns {HTMLElement}
 */
export function focusTargetFor(el) {
  if (isUsableField(el)) return /** @type {HTMLElement} */ (el);
  let parent = el.parentElement;
  for (let depth = 0; parent && depth < 3; depth += 1) {
    const field = firstField(parent);
    if (field) return field;
    parent = parent.parentElement;
  }
  return /** @type {HTMLElement} */ (el);
}

/** Height covered by the sticky navbar and competition bar. */
export function stickyOffset() {
  const bars = Array.from(document.querySelectorAll('[data-sticky-header]'));
  return bars.reduce((max, bar) => Math.max(max, bar.getBoundingClientRect().bottom), 0);
}

/**
 * @param {Element} el
 * @param {number} lowest  the lowest top, in pixels from the window's top, that counts as visible
 */
function topIsVisible(el, lowest) {
  const top = el.getBoundingClientRect().top;
  return top >= stickyOffset() && top <= lowest;
}

/** True when the page shows one column, so content sits below its navigation. */
export function isSingleColumn() {
  return (
    typeof window.matchMedia === 'function' && !window.matchMedia('(min-width: 1024px)').matches
  );
}

/**
 * Scroll an element's top into view below the sticky bars, unless it is already visible.
 * @param {Element | null | undefined} el
 * @param {{ force?: boolean, margin?: number, lowest?: number }} [options]
 */
export function scrollToElement(el, { force = false, margin = 16, lowest = undefined } = {}) {
  if (!el || (!force && topIsVisible(el, lowest ?? window.innerHeight - 48))) return;
  const top = window.scrollY + el.getBoundingClientRect().top - stickyOffset() - margin;
  window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
}

/**
 * Bring an element into view and optionally move the focus into it.
 * @param {Element | null | undefined} el
 * @param {{ focus?: 'field' | 'heading' | 'self' | null, singleColumnOnly?: boolean }} [options]
 */
export function revealElement(el, { focus = null, singleColumnOnly = false } = {}) {
  if (!el || (singleColumnOnly && !isSingleColumn())) return;
  // New content starting in the lower half would show too little of itself
  scrollToElement(el, { lowest: window.innerHeight / 2 });
  let target = null;
  if (focus === 'field') target = firstField(el);
  if (focus === 'heading' || (focus === 'field' && !target)) {
    target = el.querySelector('[data-reveal-heading]') || el.querySelector('h1, h2, h3');
    if (target && !target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
  }
  if (focus === 'self') target = el;
  /** @type {HTMLElement | null} */ (target)?.focus({ preventScroll: true });
}

/**
 * Scroll to and focus a field, or the visible control of the widget that wraps it.
 * @param {Element | null | undefined} el
 */
export function focusField(el) {
  if (!el) return;
  const target = focusTargetFor(el);
  // The margin keeps the field's label in view above it
  scrollToElement(target, { margin: 40 });
  target.focus({ preventScroll: true });
}

/**
 * Scroll to and focus the trigger that carries `data-return-id={id}`, when it is on screen.
 * @param {string | null | undefined} id
 */
export function returnToTrigger(id) {
  if (!id) return;
  const selector = `[data-return-id="${typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(id) : id}"]`;
  const trigger = /** @type {HTMLElement | null} */ (document.querySelector(selector));
  if (!trigger) return;
  scrollToElement(trigger);
  trigger.focus({ preventScroll: true });
}
