(() => {
  const form = document.getElementById('customer-checkout');
  if (form) {
    const data = JSON.parse(document.getElementById('checkout-data').textContent);
    const kind = form.elements.fulfilment, area = form.elements.delivery_area;
    const labels = {jazzcash: 'JazzCash', easypaisa: 'Easypaisa', card: 'Card (Visa / Mastercard)', cod: 'Cash on delivery', cash: 'Cash at pickup / cafe'};
    const money = value => 'Rs. ' + Number(value).toLocaleString('en-PK', {maximumFractionDigits: 2});
    function update(rebuild) {
      const delivery = kind.value === 'delivery';
      document.querySelectorAll('.delivery-field').forEach(el => {el.hidden = !delivery;});
      const fee = delivery ? data.areas[area.value] : '0';
      document.getElementById('delivery-fee').textContent = fee === undefined ? 'Calculated for your area' : money(fee);
      document.getElementById('checkout-total').textContent = fee === undefined ? 'Select a delivery area' : money(Number(data.subtotal) + Number(fee));
      if (rebuild) {
        const options = document.getElementById('payment-options');
        const selected = options.querySelector('input:checked')?.value;
        options.replaceChildren();
        (data.methods[kind.value] || []).forEach(method => {
          const label = document.createElement('label');label.className = 'payment-option';
          const input = document.createElement('input');input.type = 'radio';input.name = 'payment_method';input.value = method.id;input.setAttribute('form', 'customer-checkout');input.required = true;input.checked = String(method.id) === selected;
          const text = document.createElement('span');text.textContent = labels[method.code];label.append(input, text);options.append(label);
        });
        if (!options.children.length) options.textContent = 'No payment methods available for this option.';
      }
    }
    kind.addEventListener('change', () => update(true));area.addEventListener('change', () => update(false));update(false);
  }
  document.querySelector('[data-copy-receiver]')?.addEventListener('click', async event => {
    const button = event.currentTarget;
    try {await navigator.clipboard.writeText(button.dataset.copyReceiver);button.textContent = 'Copied';}
    catch {button.textContent = 'Select and copy the number above';}
  });
})();
