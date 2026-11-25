/* Availability enhances the ordinary POST form; checking times works without JS. */
(() => {
  document.querySelectorAll('[data-reservation-form]').forEach(form => {
    const date = form.elements.namedItem('date');
    const guests = form.elements.namedItem('guests');
    const zone = form.elements.namedItem('zone');
    const time = form.elements.namedItem('time');
    const status = form.querySelector('#availability-message');
    const submit = form.querySelector('[data-request-submit]');
    let controller;
    let revision = 0;
    let timer;
    function choices(slots, previous = '') {
      time.replaceChildren(new Option('Choose a time', ''));
      slots.forEach(slot => time.add(new Option(slot.label, slot.value)));
      if (slots.some(slot => slot.value === previous)) time.value = previous;
    }
    async function refresh() {
      const version = ++revision;
      if (controller) controller.abort();
      const previous = time.value;
      choices([]);
      if (!date.value || !guests.value || !zone.value) {
        time.disabled = false;
        submit.disabled = false;
        status.textContent = 'Choose a date, party size and seating zone to see available times.';
        return;
      }
      controller = new AbortController();
      const current = controller;
      const timeout = setTimeout(() => current.abort(), 10000);
      time.disabled = true;
      submit.disabled = true;
      status.textContent = 'Checking available times...';
      try {
        const url = new URL(form.dataset.availabilityUrl, location.origin);
        url.search = new URLSearchParams({date: date.value, guests: guests.value, zone: zone.value});
        const response = await fetch(url, {signal: current.signal, credentials: 'same-origin', redirect: 'error'});
        if (!response.ok && response.status !== 400) throw new Error('Availability unavailable');
        const data = await response.json();
        if (version !== revision) return;
        choices(data.times, previous);
        status.textContent = data.message;
      } catch (error) {
        if (version === revision) status.textContent = 'Times could not be refreshed. Use Check available times below; your details are kept.';
      } finally {
        clearTimeout(timeout);
        if (version === revision) { time.disabled = false; submit.disabled = false; }
      }
    }
    [date, guests, zone].forEach(input => input.addEventListener('change', () => {
      // Invalidate stale results immediately, including during the debounce interval.
      revision++;
      if (controller) controller.abort();
      choices([]);
      clearTimeout(timer);
      timer = setTimeout(refresh, 180);
    }));
    if (date.value && guests.value && zone.value) refresh();
  });
})();
