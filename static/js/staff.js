/* Refresh only the queue, preserving forms, scroll and keyboard focus. */
(() => {
  const region = document.querySelector('[data-live-queue]');
  if (!region) return;
  const status = document.getElementById('refresh-status');
  const button = document.getElementById('refresh-queue');
  button.hidden = false;
  let dirty = false;
  let inFlight = false;
  let revision = 0;
  document.addEventListener('input', event => {
    if (event.target.closest('form')) { dirty = true; revision++; }
  });
  document.addEventListener('change', event => {
    if (event.target.closest('form')) { dirty = true; revision++; }
  });
  document.addEventListener('focusin', () => { revision++; });
  const busy = () => {
    const active = document.activeElement;
    return dirty || document.hidden || region.contains(active) ||
      (active && active.closest('main form'));
  };
  async function refresh(manual = false) {
    if (inFlight || (!manual && busy())) {
      if (!inFlight && !document.hidden) status.textContent = 'Updates paused while you work';
      return;
    }
    // A manual refresh still never replaces a focused row or an active form.
    if (region.contains(document.activeElement) || document.activeElement.closest('main form')) return;
    inFlight = true;
    const before = revision;
    const url = new URL(window.location.href);
    url.searchParams.set('fragment', '1');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(url, {credentials: 'same-origin', signal: controller.signal, redirect: 'error'});
      if (!response.ok) throw new Error('Queue unavailable');
      const html = await response.text();
      if (before !== revision || (!manual && busy()) || region.contains(document.activeElement)) return;
      const scroll = region.querySelector('.table-scroll')?.scrollLeft || 0;
      region.innerHTML = html;
      const table = region.querySelector('.table-scroll');
      if (table) table.scrollLeft = scroll;
      status.textContent = 'Queue updated. Refreshes every 20 seconds while idle.';
    } catch (error) {
      status.textContent = 'Update unavailable. Use Refresh queue to try again.';
    } finally {
      clearTimeout(timeout);
      inFlight = false;
    }
  }
  button.addEventListener('click', () => refresh(true));
  setInterval(() => refresh(), 20000);
})();
