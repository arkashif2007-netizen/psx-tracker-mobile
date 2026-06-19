/* ============================================================
   PSX Tracker — Frontend Application Logic
   ============================================================ */

const API_BASE = 'http://localhost:5000/api';

let refreshTimer = null;

/* ---------- Utilities ---------- */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function formatPKR(amount) {
  if (amount === null || amount === undefined || isNaN(amount)) return 'PKR 0';
  return 'PKR ' + Number(amount).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function roundTo(value, decimals = 2) {
  const factor = Math.pow(10, decimals);
  return Math.round((value + Number.EPSILON) * factor) / factor;
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
}

function setSafeHTML(id, html) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = html;
}

/* ---------- Toast ---------- */
function showToast(message, type = 'info') {
  const container = $('#toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

/* ---------- Tabs ---------- */
function switchTab(tabName) {
  $$('.tab').forEach((btn) => {
    const active = btn.getAttribute('data-tab') === tabName;
    btn.classList.toggle('active', active);
  });
  $$('.tab-panel').forEach((panel) => {
    const active = panel.id === `tab-${tabName}`;
    panel.classList.toggle('active', active);
  });

  if (tabName === 'transactions') loadTransactions();
  if (tabName === 'reports') loadReports();
  if (tabName === 'audit') loadAudit();
}

/* ---------- Section Buttons ---------- */
function navigateTo(targetId) {
  const panelMap = {
    transactions: 'transactions',
    'add-transaction': 'add-transaction',
    capital: 'capital',
    tax: 'tax',
    reports: 'reports',
    audit: 'audit',
  };
  const tabName = panelMap[targetId] || targetId;
  switchTab(tabName);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ---------- TradingViewView ---------- */
/* ---------- Symbol Dropdown ---------- */
async function loadSymbolDropdowns() {
  try {
    const res = await fetch(`${API_BASE}/symbols`);
    const data = await res.json();
    if (data.status !== 'ok') throw new Error(data.error || 'Failed to load symbols');

    const selects = $$('.stock-symbol-select');
    selects.forEach((select) => {
      const current = select.value;
      select.innerHTML = '<option value="">-- Select Stock --</option>';
      data.symbols.forEach((s) => {
        const opt = document.createElement('option');
        opt.value = s.symbol;
        opt.textContent = `${s.symbol} — ${s.name}`;
        opt.dataset.sector = s.sector;
        select.appendChild(opt);
      });
      if (current) select.value = current;
    });
  } catch (err) {
    console.error('Failed to load symbols:', err);
    showToast('Failed to load stock symbols', 'error');
  }
}

async function onSymbolSelect(symbol, priceInputId) {
  if (!symbol) return;
  const input = document.getElementById(priceInputId);
  if (!input) return;
  input.placeholder = 'Loading...';
  input.classList.add('loading');

  try {
    const res = await Promise.resolve(null);
    const data = await res.json();
    if (data.price !== null && data.price !== undefined) {
      input.value = data.price;
      showToast(`${symbol}: PKR ${data.price}`, 'success');
    } else {
      input.placeholder = 'Enter manually';
      showToast(`Live price unavailable for ${symbol}`, 'warning');
    }
  } catch (err) {
    input.placeholder = 'Enter manually';
    showToast('Price lookup failed', 'error');
  } finally {
    input.classList.remove('loading');
  }
}

/* ---------- Dashboard + Live Refresh ---------- */
function pnlClass(value) {
  if (value > 0) return 'profit';
  if (value < 0) return 'loss';
  return '';
}

function renderHoldingsTable(holdings, livePrices, tableId) {
  const tbody = document.querySelector('#' + tableId + ' tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  holdings.forEach((h) => {
    const live = livePrices[h.symbol] || {};
    const livePrice = (live.price !== undefined && live.price !== null) ? live.price : (h.live_price !== undefined ? parseFloat(h.live_price) : null);
    const avgCost = parseFloat(h.avg_cost || 0);
    const qty = parseFloat(h.quantity || 0);
    const totalCost = parseFloat(h.total_cost || 0);
    const unrealizedPnl = livePrice !== null ? (livePrice - avgCost) * qty : null;
    const unrealizedPct = (unrealizedPnl !== null && avgCost) ? ((livePrice - avgCost) / avgCost * 100) : null;
    const buyTax = totalCost * 0.15;
    const netUnrealized = unrealizedPnl !== null ? (unrealizedPnl - buyTax) : null;

    const tr = document.createElement('tr');
    tr.setAttribute('data-symbol', h.symbol);

    tr.innerHTML = [
      h.symbol,
      qty,
      'PKR ' + avgCost.toFixed(2),
      livePrice !== null ? 'PKR ' + livePrice.toLocaleString() : '--',
      unrealizedPnl !== null ? 'PKR ' + unrealizedPnl.toLocaleString() : '--',
      unrealizedPct !== null ? unrealizedPct.toFixed(2) + '%' : '--',
      unrealizedPnl !== null ? 'PKR ' + unrealizedPnl.toLocaleString() : '--',
      netUnrealized !== null ? 'PKR ' + netUnrealized.toLocaleString() : '--'
    ].map(v => '<td class="mono">' + v + '</td>').join('');

    tbody.appendChild(tr);
  });
  console.log('[ holdings ] rendered', tbody.rows.length, 'rows for', tableId);
}

function updateKashifUI(data) {
  setText('kashif-available', formatPKR(data.available_balance));
  setText('kashif-realized-profit', formatPKR(data.realized_profit));
  setText('kashif-tax-owed', formatPKR(data.tax_owed));
  setText('kashif-tax-paid', formatPKR(data.tax_paid));
  renderHoldingsTable(data.holdings || [], (data.live_prices || {}), 'kashif-holdings-table');

}

function updateShahvezUI(data) {
  setText('shahvez-available', formatPKR(data.available_balance));
  setText('shahvez-realized-profit', formatPKR(data.realized_profit));
  setText('shahvez-tax-owed', formatPKR(data.tax_owed));
  setText('shahvez-tax-paid', formatPKR(data.tax_paid));
  renderHoldingsTable(data.holdings || [], (data.live_prices || {}), 'shahvez-holdings-table');

}

function flashPriceChanges(livePrices) {
  Object.entries(livePrices).forEach(([symbol, data]) => {
    if (!data || data.price === null || data.price === undefined) return;
    const el = document.querySelector(`[data-symbol="${symbol}"]`);
    if (!el) return;
    const oldText = el.textContent || '';
    const oldPrice = parseFloat(oldText.replace(/[^0-9.]/g, '')) || 0;
    el.textContent = `PKR ${data.price.toLocaleString()}`;
    if (data.price > oldPrice) el.classList.add('value-updated-up');
    else if (data.price < oldPrice) el.classList.add('value-updated-down');
    setTimeout(() => {
      el.classList.remove('value-updated-up', 'value-updated-down');
    }, 700);
  });
}

async function refreshDashboard() {
  try {
    const res = await fetch(`${API_BASE}/dashboard`);
    const data = await res.json();
    if (data.status !== 'ok') throw new Error(data.error || 'Dashboard fetch failed');

    updateKashifUI(data.kashif || {});
    updateShahvezUI(data.shahvez || {});

    // Combined metrics
    const totalInvested = (data.kashif?.total_invested || 0) + (data.shahvez?.total_invested || 0);
    const totalWithdrawn = (data.kashif?.total_withdrawn || 0) + (data.shahvez?.total_withdrawn || 0);
    const portfolioValue = (data.kashif?.available_balance || 0) + (data.shahvez?.available_balance || 0)
      + (data.kashif?.holdings || []).reduce((sum, h) => sum + (parseFloat(h.total_cost || 0)), 0)
      + (data.shahvez?.holdings || []).reduce((sum, h) => sum + (parseFloat(h.total_cost || 0)), 0);
    const netRealized = (data.kashif?.realized_profit || 0) - (data.kashif?.tax_owed || 0)
      + (data.shahvez?.realized_profit || 0) - (data.shahvez?.tax_owed || 0);

    setText('total-invested', formatPKR(totalInvested));
    setText('total-withdrawn', formatPKR(totalWithdrawn));
    setText('portfolio-value', formatPKR(portfolioValue));
    setText('net-realized', formatPKR(netRealized));
    setText('lastUpdated', new Date().toLocaleTimeString());

    // PnL + Tax Overview bar
    {
      const k = data.kashif || {};
      const s = data.shahvez || {};
      const combinedCost = parseFloat(k.total_cost || 0) + parseFloat(s.total_cost || 0);
      const combinedMarket = parseFloat(k.market_value || 0) + parseFloat(s.market_value || 0);
      const combinedUnrealized = roundTo(combinedMarket - combinedCost, 2);
      const combinedBuyTax = roundTo(combinedCost * 0.15, 2);
      const combinedNetUnrealized = roundTo(combinedUnrealized - combinedBuyTax, 2);
      const combinedOwed = roundTo((parseFloat(k.tax_owed || 0) + parseFloat(s.tax_owed || 0)), 2);
      const combinedPaid = roundTo((parseFloat(k.tax_paid || 0) + parseFloat(s.tax_paid || 0)), 2);
      const combinedPayable = Math.max(0, combinedOwed - combinedPaid);

      setText('unrealized-pnl', formatPKR(combinedUnrealized));
      setText('unrealized-pnl-sub', `${combinedCost ? ((combinedUnrealized / combinedCost) * 100).toFixed(2) : '0.00'}% on cost`);
      setText('net-unrealized-pnl', formatPKR(combinedNetUnrealized));
      setText('net-unrealized-pnl-sub', `Buy tax: ${formatPKR(combinedBuyTax)}`);
      setText('tax-payable', formatPKR(combinedPayable));
      setText('tax-payable-sub', `Owed: ${formatPKR(combinedOwed)} / Paid: ${formatPKR(combinedPaid)}`);

      const cards = ['pnl-card-unrealized', 'pnl-card-net', 'pnl-card-tax'];
      cards.forEach((id, idx) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.remove('win', 'loss');
        const value = [combinedUnrealized, combinedNetUnrealized, combinedPayable][idx];
        if (value > 0) el.classList.add('win');
        else if (value < 0) el.classList.add('loss');
      });
    }

    const holdingsSymbols = [
      ...(data.kashif?.holdings || []),
      ...(data.shahvez?.holdings || []),
    ].map(h => h.symbol);
    updateTVTickerTape(holdingsSymbols);
    flashPriceChanges(data.live_prices || {});
    refreshAllocationCharts(data);
  } catch (err) {
    console.error('Dashboard refresh failed:', err);
    showToast('Dashboard refresh failed — retrying...', 'warning');
  }
}

function startAutoRefresh() {
  refreshDashboard();
  refreshTimer = setInterval(refreshDashboard, PRICE_REFRESH_INTERVAL);
}

/* ---------- Transactions Tab ---------- */
async function loadTransactions() {
  const kashifRes = await fetch(`${API_BASE}/transactions/kashif`);
  const kashifData = await kashifRes.json();
  const shahvezRes = await fetch(`${API_BASE}/transactions/shahvez`);
  const shahvezData = await shahvezRes.json();

  const rows = [
    ...(kashifData.transactions || []).map(t => ({ ...t, individual: 'Kashif' })),
    ...(shahvezData.transactions || []).map(t => ({ ...t, individual: 'Shahvez' })),
  ].sort((a, b) => new Date(b.date) - new Date(a.date));

  const tbody = document.querySelector('#transactions-table tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  rows.forEach((r) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${r.date}</td>
      <td>${r.individual}</td>
      <td>${r.type.toUpperCase()}</td>
      <td class="mono">${r.symbol}</td>
      <td>${r.quantity}</td>
      <td class="mono">${parseFloat(r.price).toFixed(2)}</td>
      <td class="mono">${parseFloat(r.total_value).toFixed(2)}</td>
      <td>${r.notes || ''}</td>
    `;
    tbody.appendChild(tr);
  });
}

/* ---------- Capital Form ---------- */
function bindCapitalForm() {
  const form = $('#form-capital');
  if (!form) return;
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      individual: $('#cap-individual').value,
      type: $('#cap-type').value,
      amount: parseFloat($('#cap-amount').value),
      date: $('#cap-date').value,
      note: $('#cap-note').value,
    };
    if (!payload.individual || !payload.type || isNaN(payload.amount) || !payload.date) {
      showToast('Please fill all required fields', 'error');
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/capital`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.status !== 'ok') throw new Error(data.error);
      showToast('Capital entry recorded', 'success');
      form.reset();
      refreshDashboard();
    } catch (err) {
      showToast(err.message || 'Capital entry failed', 'error');
    }
  });
}

/* ---------- Transaction Form ---------- */
function bindTransactionForm() {
  const form = $('#form-transaction');
  if (!form) return;
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      individual: $('#tx-individual').value,
      type: $('#tx-type').value,
      symbol: $('#tx-symbol').value,
      stock_name: $('#tx-stock-name').value,
      quantity: parseFloat($('#tx-quantity').value),
      price: parseFloat($('#tx-price').value),
      fees: parseFloat($('#tx-fees').value || 0),
      brokerage: parseFloat($('#tx-brokerage').value || 0),
      date: $('#tx-date').value,
      notes: $('#tx-notes').value,
    };
    if (!payload.individual || !payload.type || !payload.symbol || !payload.quantity || !payload.price || !payload.date) {
      showToast('Please fill all required fields', 'error');
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/transactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.status !== 'ok') throw new Error(data.error);
      showToast('Transaction recorded', 'success');
      form.reset();
      refreshDashboard();
    } catch (err) {
      showToast(err.message || 'Transaction failed', 'error');
    }
  });
}

/* ---------- Tax Payment Form ---------- */
function bindTaxForm() {
  const form = $('#form-tax');
  if (!form) return;
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      individual: $('#tax-individual').value,
      amount: parseFloat($('#tax-amount').value),
      period: $('#tax-period').value,
      date: $('#tax-date').value,
      note: $('#tax-note').value,
    };
    if (!payload.individual || isNaN(payload.amount) || !payload.date) {
      showToast('Please fill all required fields', 'error');
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/tax-payment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.status !== 'ok') throw new Error(data.error);
      showToast('Tax payment recorded', 'success');
      form.reset();
      refreshDashboard();
    } catch (err) {
      showToast(err.message || 'Tax payment failed', 'error');
    }
  });
}

/* ---------- Reports ---------- */
async function loadReports() {
  const kashifRes = await fetch(`${API_BASE}/dashboard`);
  const data = await kashifRes.json();
  if (data.status !== 'ok') return;

  ['kashif', 'shahvez'].forEach((who) => {
    const p = data[who] || {};
    setText(`report-${who}-available`, formatPKR(p.available_balance));
    setText(`report-${who}-invested`, formatPKR(p.total_invested));
    setText(`report-${who}-withdrawn`, formatPKR(p.total_withdrawn));
    setText(`report-${who}-gross`, formatPKR(p.realized_profit));
    setText(`report-${who}-tax-owed`, formatPKR(p.tax_owed));
    setText(`report-${who}-tax-paid`, formatPKR(p.tax_paid));
    setText(`report-${who}-net`, formatPKR(p.net_position));
  });
}

/* ---------- Audit Log ---------- */
async function loadAudit() {
  const kashifRes = await fetch(`${API_BASE}/audit-log/kashif`);
  const shahvezRes = await fetch(`${API_BASE}/audit-log/shahvez`);
  const kashifData = await kashifRes.json();
  const shahvezData = await shahvezRes.json();

  const rows = [
    ...(kashifData.logs || []).map(l => ({ ...l, individual: 'Kashif' })),
    ...(shahvezData.logs || []).map(l => ({ ...l, individual: 'Shahvez' })),
  ].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

  const tbody = document.querySelector('#audit-log-table tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  rows.forEach((r) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${new Date(r.timestamp).toLocaleString()}</td>
      <td>${r.individual}</td>
      <td>${r.action}</td>
      <td>${r.details || ''}</td>
    `;
    tbody.appendChild(tr);
  });
}

/* ---------- Init ---------- */
document.addEventListener('DOMContentLoaded', () => {
  // Tabs
  $$('.tab').forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.getAttribute('data-tab')));
  });

  // Manual stock entry: no live price fetch

  // Forms
  bindTransactionForm();
  bindCapitalForm();
  bindTaxForm();

  // Section buttons
  $$('.section-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      navigateTo(btn.getAttribute('data-target'));
    });
  });

  // Data bootstrap
  loadSymbolDropdowns();
  startAutoRefresh();
});




/* ---------- Allocation Charts ---------- */
/* ---------- Allocation Charts ---------- */
function refreshAllocationCharts(data) {
  buildAllocationChart('kashif-allocation', (data && data.kashif && data.kashif.holdings) ? data.kashif.holdings : []);
  buildAllocationChart('shahvez-allocation', (data && data.shahvez && data.shahvez.holdings) ? data.shahvez.holdings : []);
}

function buildAllocationChart(canvasId, holdings) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const items = (holdings || []).slice(0, 12);
  const labels = items.map(h => h.symbol || 'Other');
  const values = items.map(h => {
    const qty = parseFloat(h.quantity || 0);
    const price = parseFloat(h.live_price || h.avg_cost || 0);
    return roundTo(qty * price, 2);
  });
  const total = values.reduce((sum, v) => sum + v, 0) || 1;
  const background = ['#00d4ff','#a78bfa','#34d399','#fbbf24','#f87171','#60a5fa','#f472b6','#a3e635','#facc15','#22d3ee','#c084fc','#fb923c'];

  new Chart(ctx, {
    type: 'pie',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: background.slice(0, labels.length),
        borderColor: 'rgba(10,15,30,0.8)',
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { labels: { color: '#e2e8f0', font: { size: 12 } } },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.label}: PKR ${Number(ctx.raw || 0).toLocaleString()} (${((ctx.raw/total)*100).toFixed(1)}%)`
          }
        }
      },
    },
  });
}
