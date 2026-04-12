'use strict';
const BASE = window.location.origin;

function akey() {
  return typeof S !== 'undefined' ? (S.internalKey ?? null) : null;
}

function escHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-AU', {day:'2-digit',month:'short'});
}

function fmtDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-AU', {day:'2-digit',month:'short'}) + ' ' +
         d.toLocaleTimeString('en-AU', {hour:'2-digit',minute:'2-digit',hour12:false});
}

let _toastTimer;
function showToast(msg, isErr = false) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.className = isErr ? 'err' : 'ok';
  el.style.display = 'block';
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.style.display = 'none'; }, 3000);
}

// Throwing api variant used by the profiles panel — extracts detail from error body
async function apiCall(path, opts = {}) {
  const k = akey(); if (!k) return null;
  try {
    const r = await fetch(BASE + path, {
      credentials: 'include',
      headers: { 'X-API-Key': k, 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts
    });
    if (r.status === 204) return { ok: true };
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.detail || 'HTTP ' + r.status);
    }
    return await r.json();
  } catch (e) {
    console.warn('[apiCall]', path, e.message);
    throw e;
  }
}
