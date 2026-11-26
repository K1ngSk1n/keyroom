'use strict';
const $ = id => document.getElementById(id);
const isFilePreview = window.location.protocol === 'file:';
const views = ['setup', 'loading', 'scan', 'fetching', 'results', 'error'];
let timer, devices = [], generation = 0, currentView = 'setup';
function show(view, step = 0) {
  currentView = view;
  views.forEach(id => { $(id).hidden = id !== view; });
  $('stage').textContent = `STEP 0${step + 1} / 03`;
  document.querySelectorAll('#steps li').forEach((li, i) => {
    li.classList.toggle('active', i === step); li.classList.toggle('done', i < step);
  });
}
async function api(url, options = {}) {
  if (isFilePreview) throw new Error('This is a layout preview. Open the running web app to sign in.');
  const r = await fetch(url, {cache: 'no-store', ...options});
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Unable to connect. Please try again.');
  }
  return r.status === 204 ? null : r.json();
}
function clearLocal() {
  clearTimeout(timer); devices = []; $('devices').replaceChildren(); $('qr').removeAttribute('src');
  $('search').value = ''; $('timer').hidden = true;
}
function fail(message, title = 'Let’s try that again.') {
  clearLocal(); $('error-title').textContent = title; $('error-text').textContent = message;
  $('session-actions').hidden = false; show('error');
}
async function endSession() {
  generation++; clearLocal();
  try { await api('/api/session', {method:'DELETE'}); }
  catch (_) { fail('Could not reach the server to clear this session. It will expire automatically within 10 minutes.'); return; }
  $('consent').checked = false; $('start').disabled = true;
  $('session-actions').hidden = true; show('setup');
}
async function poll(g) {
  if (g !== generation) return;
  try {
    const data = await api('/api/session');
    if (g !== generation) return;
    $('timer').hidden = false;
    $('timer').textContent = `Session ${Math.floor(data.expires_in / 60)}:${String(data.expires_in % 60).padStart(2, '0')}`;
    if (data.state === 'waiting') {
      if (currentView !== 'scan') { $('qr').src = '/api/qr'; show('scan', 1); }
    } else if (data.state === 'fetching') { $('qr').removeAttribute('src'); show('fetching', 2); }
    else if (data.state === 'ready') {
      if (currentView !== 'results') {
        devices = data.devices; show('results', 2); render();
        $('warning').hidden = !data.warnings.length;
        $('warning').textContent = `Some data could not be retrieved in: ${data.warnings.join(', ')}. Results may be incomplete; try that region again.`;
      }
    } else if (data.state === 'expired') { fail('That QR code expired. Start a fresh session and scan it again.', 'Your QR code timed out.'); return; }
    else if (data.state === 'error') { fail('Xiaomi could not complete the request. Try again, or select a different region.'); return; }
    timer = setTimeout(() => poll(g), data.state === 'ready' ? 5000 : 2000);
  } catch (e) { if (g === generation) fail(e.message); }
}
async function start() {
  clearLocal(); const g = ++generation;
  $('session-actions').hidden = false; show('loading', 1);
  try {
    await api('/api/session', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({region:$('region').value, consent:$('consent').checked})});
    if (g === generation) poll(g);
  } catch (e) { if (g === generation) fail(e.message); }
}
function text(tag, value, className) {
  const el = document.createElement(tag); el.textContent = value;
  if (className) el.className = className; return el;
}
async function copy(value) {
  try { await navigator.clipboard.writeText(value); $('status').textContent = 'Copied'; }
  catch (_) { $('status').textContent = 'Copy unavailable. Reveal and select the value.'; }
  setTimeout(() => { $('status').textContent = ''; }, 3500);
}
function render() {
  const query = $('search').value.toLowerCase();
  const filtered = devices.filter(d => [d.name, d.model, d.mac, d.id].some(v => v.toLowerCase().includes(query)));
  $('count').textContent = `${devices.length} device${devices.length === 1 ? '' : 's'} found. Keys stay hidden until you need them.`;
  $('empty').hidden = filtered.length > 0;
  $('download').disabled = devices.length === 0;
  $('devices').replaceChildren();
  filtered.forEach(d => {
    const card = text('article', '', 'device'); card.append(text('h3', d.name), text('div', `${d.model} · ${d.region.toUpperCase()}`, 'model'));
    const list = document.createElement('dl');
    [['ID', d.id, false], ['MAC', d.mac, false], ['Token', d.token, true], ['BLE key', d.ble_key, true]].forEach(([label, value, secret]) => {
      const row = text('div', '', 'row'), dd = text('dd', value ? (secret ? '••••••••••••••••' : value) : 'Unavailable');
      row.append(text('dt', label), dd);
      if (value) {
        const buttons = text('div', '', 'buttons');
        if (secret) {
          const reveal = text('button', 'Reveal'); reveal.type = 'button'; reveal.setAttribute('aria-label', `Reveal ${label} for ${d.name}`);
          reveal.addEventListener('click', () => { const hidden = reveal.textContent === 'Reveal'; dd.textContent = hidden ? value : '••••••••••••••••'; reveal.textContent = hidden ? 'Hide' : 'Reveal'; }); buttons.append(reveal);
        }
        const c = text('button', 'Copy'); c.type = 'button'; c.setAttribute('aria-label', `Copy ${label} for ${d.name}`); c.addEventListener('click', () => copy(value)); buttons.append(c); row.append(buttons);
      }
      list.append(row);
    });
    card.append(list); $('devices').append(card);
  });
}
$('consent').addEventListener('change', () => { $('start').disabled = isFilePreview || !$('consent').checked; });
$('start').addEventListener('click', start); $('end').addEventListener('click', endSession);
$('retry').addEventListener('click', endSession); $('search').addEventListener('input', render);
$('download').addEventListener('click', () => {
  const blob = new Blob([JSON.stringify({devices}, null, 2)], {type:'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'xiaomi-device-keys.json'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
// Session state is deliberately absent from localStorage, URLs, and analytics.
window.addEventListener('pagehide', clearLocal);
window.addEventListener('pageshow', e => { if (e.persisted) { generation++; $('session-actions').hidden = true; show('setup'); } });

if (isFilePreview) {
  $('preview-note').hidden = false;
  $('consent').disabled = true;
  $('region').disabled = true;
  $('start').disabled = true;
  $('start').textContent = 'Layout preview';
  document.querySelector('.brand').href = 'index.html';
  const source = document.querySelector('a[href="/source"]');
  source.href = '../../TRACEABILITY.md';
  source.textContent = 'Source & provenance';
  const build = document.querySelector('a[href="/api/build"]');
  build.removeAttribute('href');
  build.textContent = 'Local layout preview';
}
