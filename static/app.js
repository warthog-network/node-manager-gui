const REFRESH_MS = 5000;
let currentPage = 'dashboard';
let refreshTimer = null;
let logStream = null;
let serviceFlags = null;

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = typeof data?.detail === 'string'
      ? data.detail
      : data?.detail ? JSON.stringify(data.detail) : res.statusText;
    throw new Error(detail);
  }
  return data;
}

function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function fmtNum(n) {
  if (n == null) return '—';
  return Number(n).toLocaleString();
}

function fmtHashrate(h) {
  if (!h) return '—';
  if (h >= 1e9) return (h / 1e9).toFixed(2) + ' GH/s';
  if (h >= 1e6) return (h / 1e6).toFixed(2) + ' MH/s';
  if (h >= 1e3) return (h / 1e3).toFixed(2) + ' KH/s';
  return h.toFixed(0) + ' H/s';
}

function fmtBytes(b) {
  if (!b) return '—';
  if (b >= 1e9) return (b / 1e9).toFixed(2) + ' GB';
  if (b >= 1e6) return (b / 1e6).toFixed(2) + ' MB';
  if (b >= 1e3) return (b / 1e3).toFixed(1) + ' KB';
  return b + ' B';
}

function shortHash(h) {
  if (!h || h.length < 16) return h || '—';
  return h.slice(0, 8) + '…' + h.slice(-8);
}

function colorizeLog(line) {
  let cls = '';
  if (/\[error\]|error|closed:/i.test(line)) cls = 'line-error';
  else if (/\[warn\]|warning/i.test(line)) cls = 'line-warn';
  else if (/\[info\]/i.test(line)) cls = 'line-info';
  return `<span class="${cls}">${escHtml(line)}</span>`;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escAttr(s) {
  return escHtml(String(s)).replace(/"/g, '&quot;');
}

// ── Navigation ────────────────────────────────────────────────────────────────

function navigate(page) {
  currentPage = page;
  $$('.page').forEach(p => p.classList.remove('active'));
  $(`#page-${page}`)?.classList.add('active');
  $$('.nav button').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  loadPage(page);
}

function loadPage(page) {
  switch (page) {
    case 'dashboard': loadDashboard(); break;
    case 'peers': loadPeers(); break;
    case 'mempool': loadMempool(); break;
    case 'logs': loadLogs(); break;
    case 'service': loadService(); break;
    case 'settings': loadSettings(); break;
  }
}

// ── Config ────────────────────────────────────────────────────────────────────

async function loadConfig() {
  try {
    const cfg = await api('/api/config');
    $('#sidebar-config').innerHTML =
      `Manager: 127.0.0.1:${cfg.manager_port}<br>Node RPC: ${escHtml(cfg.node_rpc_display)}`;
    $('#svc-name-inline')?.replaceChildren(document.createTextNode(cfg.service));
  } catch (_) {}
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

async function loadDashboard() {
  try {
    const d = await api('/api/dashboard');
    updateStatusPill(d);

    const node = d.node;
    const head = node?.head;
    const info = node?.info;

    $('#card-height').textContent = head?.chainHead?.height != null ? fmtNum(head.chainHead.height) : '—';
    $('#card-synced').textContent = head?.synced ? 'Synced' : 'Syncing…';
    $('#card-synced').style.color = head?.synced ? 'var(--green)' : 'var(--accent)';
    $('#card-hashrate').textContent = fmtHashrate(head?.chainHead?.hashrate);
    $('#card-difficulty').textContent = head?.chainHead?.difficulty != null ? fmtNum(Math.round(head.chainHead.difficulty)) : '—';
    $('#card-peers').textContent = fmtNum(node?.peer_count);
    $('#card-mempool').textContent = fmtNum(node?.mempool_count);
    $('#card-minfee').textContent = node?.minfee?.minFee?.str || '—';
    $('#card-uptime').textContent = info?.uptime?.formatted || '—';
    $('#card-version').textContent = info?.version?.name || '—';
    $('#card-dbsize').textContent = fmtBytes(info?.dbSize);

    const hashEl = $('#head-hash');
    if (hashEl && head?.chainHead?.hash) {
      hashEl.textContent = head.chainHead.hash;
    }

    $('#last-refresh').textContent = new Date().toLocaleTimeString();
  } catch (e) {
    updateStatusPill({ service: { running: false }, error: e.message });
  }
}

function updateStatusPill(d) {
  const pill = $('#status-pill');
  const running = d.service?.running && !d.error;
  pill.className = `status-pill ${running ? 'online' : 'offline'}`;
  pill.querySelector('.label').textContent = running ? 'Node Online' : 'Node Offline';
}

// ── Peers ─────────────────────────────────────────────────────────────────────

async function loadPeers() {
  try {
    const [conn, banned] = await Promise.all([
      api('/api/node/peers/connected/connection'),
      api('/api/node/peers/banned'),
    ]);

    const tbody = $('#peers-table tbody');
    const peers = conn?.data || [];
    if (!peers.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">No connected peers</td></tr>';
    } else {
      tbody.innerHTML = peers.map(p => {
        const c = p;
        const since = c.since?.UTC || '—';
        const ip = c.ip || '';
        return `<tr>
          <td class="mono">${c.ip || '—'}</td>
          <td>${c.port || '—'}</td>
          <td>${since}</td>
          <td><span style="color:var(--green)">Connected</span></td>
          <td>${ip ? `<button class="btn btn-danger btn-sm" data-ban="${escAttr(ip)}">Ban</button>` : '—'}</td>
        </tr>`;
      }).join('');
      tbody.querySelectorAll('[data-ban]').forEach(btn => {
        btn.addEventListener('click', () => banPeer(btn.dataset.ban));
      });
    }

    const bannedTbody = $('#banned-table tbody');
    const bans = banned?.data || [];
    if (!bans.length) {
      bannedTbody.innerHTML = '<tr><td colspan="3" class="empty">No banned peers</td></tr>';
    } else {
      bannedTbody.innerHTML = bans.map(b => {
        const ip = b.ip || b.address || '';
        const until = b.banuntil ? new Date(b.banuntil * 1000).toLocaleString() : '—';
        return `<tr>
          <td class="mono">${ip || '—'}</td>
          <td>${until} — ${escHtml(b.reason || '')}</td>
          <td>${ip ? `<button class="btn btn-sm" data-unban="${escAttr(ip)}">Unban</button>` : '—'}</td>
        </tr>`;
      }).join('');
      bannedTbody.querySelectorAll('[data-unban]').forEach(btn => {
        btn.addEventListener('click', () => unbanPeer(btn.dataset.unban));
      });
    }
  } catch (e) {
    toast('Failed to load peers: ' + e.message, 'error');
  }
}

async function banPeer(ip) {
  if (!confirm(`Ban ${ip}?`)) return;
  try {
    const res = await api(`/api/peers/ban/${encodeURIComponent(ip)}`, { method: 'POST' });
    toast(res.note ? `Banned ${ip}` : `Banned ${ip}`);
    loadPeers();
  } catch (e) {
    toast('Ban failed: ' + e.message, 'error');
  }
}

async function unbanPeer(ip) {
  if (!confirm(`Unban ${ip}?`)) return;
  try {
    const res = await api(`/api/peers/unban/${encodeURIComponent(ip)}`, { method: 'POST' });
    toast(res.note || `Unbanned ${ip}`);
    loadPeers();
  } catch (e) {
    toast('Unban failed: ' + e.message, 'error');
  }
}

async function unbanAll() {
  if (!confirm('Unban all peers? This clears the in-memory ban cache immediately.')) return;
  try {
    await api('/api/peers/unban', { method: 'POST' });
    toast('All peers unbanned');
    loadPeers();
  } catch (e) {
    toast('Unban failed: ' + e.message, 'error');
  }
}

// ── Mempool ───────────────────────────────────────────────────────────────────

async function loadMempool() {
  try {
    const res = await api('/api/node/transaction/mempool');
    const entries = res?.data || [];
    const tbody = $('#mempool-table tbody');

    if (!entries.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty">Mempool is empty</td></tr>';
      return;
    }

    tbody.innerHTML = entries.map(e => {
      const tx = e.transaction || e;
      const hash = tx.hash || '—';
      const fee = tx.signedCommon?.fee?.str || tx.fee?.str || '—';
      const from = tx.signedCommon?.originAddress || '—';
      const type = tx.data?.baseAsset?.name ? `DEX (${tx.data.baseAsset.name})` : 'Transfer';
      return `<tr>
        <td class="mono" title="${escAttr(hash)}">${shortHash(hash)}</td>
        <td>${type}</td>
        <td class="mono" title="${escAttr(from)}">${shortHash(from)}</td>
        <td>${fee}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    toast('Failed to load mempool: ' + e.message, 'error');
  }
}

// ── Logs ──────────────────────────────────────────────────────────────────────

async function loadLogFiles() {
  const res = await api('/api/logs/files');
  const sel = $('#log-file-select');
  sel.innerHTML = res.files.map(f =>
    `<option value="${escAttr(f.name)}">${escHtml(f.name)} (${fmtBytes(f.size)})</option>`
  ).join('');
}

async function loadLogs() {
  await loadLogFiles();
  const source = $('#log-source').value;
  const lines = $('#log-lines').value || 100;

  try {
    let logLines;
    if (source === 'journal') {
      const res = await api(`/api/logs/journal?lines=${lines}`);
      logLines = res.lines;
    } else {
      const file = $('#log-file-select').value;
      const res = await api(`/api/logs/tail?file=${encodeURIComponent(file)}&lines=${lines}`);
      logLines = res.lines;
    }
    const viewer = $('#log-viewer');
    viewer.innerHTML = logLines.map(colorizeLog).join('\n');
    viewer.scrollTop = viewer.scrollHeight;
  } catch (e) {
    toast('Failed to load logs: ' + e.message, 'error');
  }
}

function toggleLogStream() {
  if (logStream) {
    logStream.close();
    logStream = null;
    $('#btn-stream').textContent = 'Live Stream';
    return;
  }

  const file = $('#log-file-select').value;
  logStream = new EventSource(`/api/logs/stream?file=${encodeURIComponent(file)}`);
  const viewer = $('#log-viewer');
  viewer.innerHTML = '';

  logStream.onmessage = (ev) => {
    const { line } = JSON.parse(ev.data);
    viewer.innerHTML += colorizeLog(line) + '\n';
    if (viewer.scrollHeight - viewer.scrollTop < 200) {
      viewer.scrollTop = viewer.scrollHeight;
    }
  };
  logStream.onerror = () => {
    logStream.close();
    logStream = null;
    $('#btn-stream').textContent = 'Live Stream';
    toast('Log stream disconnected', 'error');
  };
  $('#btn-stream').textContent = 'Stop Stream';
}

// ── Service ───────────────────────────────────────────────────────────────────

function collectFlagState() {
  const bool_flags = {};
  $$('#bool-flags input[type="checkbox"]').forEach(input => {
    bool_flags[input.dataset.key] = input.checked;
  });
  const value_flags = {};
  $$('#value-flags input').forEach(input => {
    if (input.value.trim()) value_flags[input.dataset.key] = input.value.trim();
  });
  return { bool_flags, value_flags };
}

function buildPreviewCommand() {
  if (!serviceFlags) return '—';
  const { bool_flags, value_flags } = collectFlagState();
  const parts = [serviceFlags.binary];

  serviceFlags.available.bool_flags.forEach(item => {
    if (bool_flags[item.key]) parts.push(item.flag);
  });
  serviceFlags.available.value_flags.forEach(item => {
    const value = value_flags[item.key];
    if (value) parts.push(`${item.flag}=${value}`);
  });

  return parts.join(' ');
}

function updateCommandPreview() {
  const preview = buildPreviewCommand();
  $('#svc-preview-command').textContent = preview;
}

function renderServiceFlags(data) {
  serviceFlags = data;
  $('#svc-current-command').textContent = data.command;

  const boolEl = $('#bool-flags');
  boolEl.innerHTML = data.available.bool_flags.map(item => {
    const checked = data.current.bool_flags[item.key] ? 'checked' : '';
    return `<label class="flag-check" title="${escAttr(item.description)}">
      <input type="checkbox" data-key="${escAttr(item.key)}" ${checked}>
      <span>${escHtml(item.label)}</span>
      <code>${escHtml(item.flag)}</code>
    </label>`;
  }).join('');

  const valueEl = $('#value-flags');
  valueEl.innerHTML = data.available.value_flags.map(item => {
    const value = data.current.value_flags[item.key] || '';
    return `<div class="value-flag-row">
      <label title="${escAttr(item.description)}">${escHtml(item.label)} <code>${escHtml(item.flag)}</code></label>
      <input type="text" data-key="${escAttr(item.key)}" value="${escAttr(value)}" placeholder="${escAttr(item.placeholder || '')}">
    </div>`;
  }).join('');

  $$('#bool-flags input, #value-flags input').forEach(input => {
    input.addEventListener('input', updateCommandPreview);
    input.addEventListener('change', updateCommandPreview);
  });
  updateCommandPreview();
}

async function loadService() {
  try {
    const [s, flags] = await Promise.all([
      api('/api/service/status'),
      api('/api/service/flags'),
    ]);
    $('#svc-name').textContent = s.service;
    $('#svc-state').textContent = `${s.active} (${s.sub})`;
    $('#svc-state').style.color = s.running ? 'var(--green)' : 'var(--red)';
    $('#svc-pid').textContent = s.pid || '—';
    $('#svc-started').textContent = s.started || '—';
    renderServiceFlags(flags);
  } catch (e) {
    toast('Failed to load service status: ' + e.message, 'error');
  }
}

async function serviceAction(action, withFlags = false) {
  if (action === 'stop' || action === 'restart') {
    const msg = withFlags
      ? 'Restart the node with the selected flags?'
      : `${action} the node service?`;
    if (!confirm(msg)) return;
  }

  try {
    const btn = $(`#btn-${action}`);
    if (btn) btn.disabled = true;

    const opts = { method: 'POST' };
    if (withFlags) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(collectFlagState());
    }

    const res = await api(`/api/service/${action}`, opts);
    toast(withFlags && res.applied_flags
      ? 'Service restarted with updated flags'
      : `Service ${action} successful`);
    setTimeout(() => { loadService(); loadDashboard(); }, 2000);
  } catch (e) {
    toast(`${action} failed: ` + e.message, 'error');
  } finally {
    const btn = $(`#btn-${action}`);
    if (btn) btn.disabled = false;
  }
}

// ── Settings ──────────────────────────────────────────────────────────────────

async function loadSettings() {
  try {
    const res = await api('/api/node/transaction/minfee');
    const fee = res?.data?.minFee;
    $('#current-minfee').textContent = fee?.str || '—';
    $('#minfee-input').value = fee?.str || '0.00000001';
  } catch (e) {
    toast('Failed to load settings: ' + e.message, 'error');
  }
}

async function updateMinfee() {
  const val = $('#minfee-input').value.trim();
  try {
    const encoded = await api(`/api/node/tools/encode16bit/from_string/${encodeURIComponent(val)}`);
    const feeE8 = encoded?.data?.feeE8;
    if (!feeE8) throw new Error('Could not encode fee');
    await api(`/api/settings/minfee?fee_e8=${feeE8}`, { method: 'POST' });
    toast(`Min fee updated to ${val}`);
    loadSettings();
    loadDashboard();
  } catch (e) {
    toast('Update failed: ' + e.message, 'error');
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  $$('.nav button').forEach(btn => {
    btn.addEventListener('click', () => navigate(btn.dataset.page));
  });

  $('#btn-start')?.addEventListener('click', () => serviceAction('start'));
  $('#btn-stop')?.addEventListener('click', () => serviceAction('stop'));
  $('#btn-restart')?.addEventListener('click', () => serviceAction('restart', true));
  $('#btn-unban')?.addEventListener('click', unbanAll);
  $('#btn-refresh-logs')?.addEventListener('click', loadLogs);
  $('#btn-stream')?.addEventListener('click', toggleLogStream);
  $('#btn-update-minfee')?.addEventListener('click', updateMinfee);
  $('#log-source')?.addEventListener('change', () => {
    const isJournal = $('#log-source').value === 'journal';
    $('#log-file-select').style.display = isJournal ? 'none' : '';
    $('#btn-stream').style.display = isJournal ? 'none' : '';
  });

  loadConfig();
  navigate('dashboard');
  refreshTimer = setInterval(() => {
    if (currentPage === 'dashboard') loadDashboard();
    else if (currentPage === 'peers') loadPeers();
    else if (currentPage === 'mempool') loadMempool();
    else if (currentPage === 'service') loadService();
  }, REFRESH_MS);
});