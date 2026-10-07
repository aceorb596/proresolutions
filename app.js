const form = document.querySelector('#quote-form');
const quantity = document.querySelector('#quantity');
const bird = document.querySelector('#bird');
const api = (window.PRO_RESOLUTIONS_API || '').replace(/\/$/, '');
const button = form.querySelector('[type="submit"]');
const errorBox = document.querySelector('#form-error');
const money = n => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:0}).format(n);
const isBundle = () => form.elements.offer.value === 'buildings';
let summaryText = '';
let busy = false;
let pending = null;
const pendingKey = 'pro-resolutions-pending-v1';
try { pending = JSON.parse(sessionStorage.getItem(pendingKey)); } catch (_) {}
if (api) {
  document.querySelector('#site-banner').hidden = true;
  document.querySelector('#form-note').textContent = 'Send your request for review. Scope and scheduling are confirmed before booking.';
  document.querySelector('#privacy-note').textContent = 'We store these details to handle your quote and follow-up. Please leave out sensitive access codes.';
  document.querySelector('#booking-note').textContent = 'The form sends a quote request. It does not reserve a time or take payment. We confirm scope and scheduling with you.';
  button.textContent = 'Send quote request ↗';
  fetch(`${api}/ready`, {signal: AbortSignal.timeout(90000)}).catch(() => {});
}
function updateOffer(reset = false) {
  const bundle = isBundle();
  quantity.min = bundle ? '5' : '1';
  if (reset) quantity.value = bundle ? '5' : '1';
  document.querySelector('#quantity-label').textContent = bundle ? 'Number of buildings (5+)' : 'Number of stairwell cleans';
  const count = Number(quantity.value);
  const valid = Number.isInteger(count) && count >= Number(quantity.min) && count <= 500;
  document.querySelector('#total').textContent = valid ? money(count * (bundle ? 1250 : 125)) : '—';
  document.querySelector('#estimate-note').textContent = valid ? `Based on ${count} ${bundle ? 'buildings' : 'stairwell cleans'}. ${bird.checked ? 'Bird protection is quoted separately. ' : ''}Final scope confirmed in quote.` : `Enter a whole number from ${quantity.min} to 500.`;
  document.querySelector('#bird-note').textContent = bundle ? 'Bundle discount applies. Price confirmed in quote.' : 'Discount available with an order of 5+ buildings.';
}
function showForm(reset = false) {
  if (busy) return;
  if (reset) form.reset();
  form.hidden = false;
  document.querySelector('#result').hidden = true;
  errorBox.hidden = true;
  updateOffer();
}
form.querySelectorAll('[name="offer"]').forEach(radio => radio.addEventListener('change', () => updateOffer(true)));
quantity.addEventListener('input', () => updateOffer());
bird.addEventListener('change', () => updateOffer());
document.querySelectorAll('[data-offer]').forEach(link => link.addEventListener('click', () => {
  if (busy) return;
  showForm();
  const offer = link.dataset.offer;
  form.elements.offer.value = offer === 'stairs' ? 'stairs' : 'buildings';
  bird.checked = offer === 'bird';
  updateOffer(true);
}));
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !form.reportValidity()) return;
  const data = new FormData(form);
  const payload = {
    offer: data.get('offer'), quantity: Number(data.get('quantity')), bird: bird.checked,
    timing: data.get('timing'), name: data.get('name').trim(), email: data.get('email').trim(),
    locations: data.get('locations').trim(), notes: data.get('notes').trim(), website: data.get('website')
  };
  let receipt = null;
  errorBox.hidden = true;
  if (api) {
    busy = true;
    button.disabled = true;
    button.textContent = 'Sending your request…';
    const controls = [...form.querySelectorAll('input, select, textarea')];
    controls.forEach(control => { control.disabled = true; });
    try {
      // Persist only a digest and request ID, never customer details.
      const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(payload))))].map(x => x.toString(16).padStart(2, '0')).join('');
      if (!pending || pending.digest !== digest) {
        pending = {digest, id: crypto.randomUUID()};
        try { sessionStorage.setItem(pendingKey, JSON.stringify(pending)); } catch (_) {}
      }
      const response = await fetch(`${api}/api/quotes`, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': pending.id},
        body: JSON.stringify(payload), signal: AbortSignal.timeout(90000)
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.received || !result.request_id) {
        throw new Error(result.error || 'We could not confirm receipt. Please try again with the same details.');
      }
      receipt = result;
      pending = null;
      try { sessionStorage.removeItem(pendingKey); } catch (_) {}
    } catch (error) {
      errorBox.textContent = error.name === 'TimeoutError' || error.name === 'TypeError'
        ? 'We could not confirm receipt. Your details are still here. Please try again; the same request will not be saved twice.'
        : error.message;
      errorBox.hidden = false;
      errorBox.scrollIntoView({block:'center'});
      return;
    } finally {
      busy = false;
      controls.forEach(control => { control.disabled = false; });
      button.disabled = false;
      button.textContent = 'Send quote request ↗';
    }
  }
  const bundle = payload.offer === 'buildings';
  const subtotal = receipt ? receipt.subtotal : payload.quantity * (bundle ? 1250 : 125);
  summaryText = `PRO RESOLUTIONS — ${receipt ? 'REQUEST RECEIVED' : 'REQUEST PREVIEW'}\n${receipt ? `Reference: ${receipt.request_id}` : 'Not sent'} • Not a booking\n\nService: ${bundle ? 'Building pressure washing' : 'Stairwell cleaning'}\nQuantity: ${payload.quantity}\nIndicative cleaning subtotal: ${money(subtotal)}\nBird protection: ${payload.bird ? 'Requested — quoted separately' : 'Not requested'}\nTiming: ${payload.timing}\n\nName: ${payload.name}\nEmail: ${payload.email}\nProperty location(s): ${payload.locations}\nNotes: ${payload.notes || 'None added'}\n\nFinal scope, bird protection pricing, and scheduling must be confirmed with Pro Resolutions.`;
  document.querySelector('#summary').textContent = summaryText;
  document.querySelector('#result-title').textContent = receipt ? 'Request received.' : 'Review your request.';
  document.querySelector('#result-eyebrow').textContent = receipt ? 'THANK YOU' : 'YOUR REQUEST SUMMARY';
  document.querySelector('#result-note').textContent = receipt ? 'Your details have been saved for review. Keep your reference number. This is not a booking confirmation.' : 'This is a preview. Nothing has been sent.';
  document.querySelector('#edit').textContent = receipt ? 'Start a new request' : 'Edit request';
  document.querySelector('#edit').dataset.sent = receipt ? 'true' : 'false';
  form.hidden = true;
  const result = document.querySelector('#result');
  result.hidden = false;
  result.setAttribute('tabindex','-1');
  result.focus();
  result.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',block:'center'});
});
document.querySelector('#edit').addEventListener('click', event => {
  showForm(event.currentTarget.dataset.sent === 'true');
  quantity.focus();
});
document.querySelector('#download').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([summaryText], {type:'text/plain;charset=utf-8'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'pro-resolutions-request.txt';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
updateOffer();
