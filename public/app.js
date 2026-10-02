/* 基金保管市場看板｜純前端（不需建置、不連外部服務） */
(function () {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (x, d = 0) => Number(x).toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (x) => `${num(x, 1)}%`;
  // 規模：資料單位為「億元」
  const amt = (yi) => (yi >= 10000 ? `${num(yi / 10000, 2)} 兆` : `${num(yi)} 億`);
  // 保管費：資料單位為「元」
  const fee = (y) => (y >= 1e8 ? `${num(y / 1e8, 2)} 億` : `${num(y / 1e4)} 萬`);
  const rankTxt = (r, tied) => `${tied ? '並列' : ''}第 ${r}`;

  const state = { data: null, key: 'n', showAll: false, cmp: new Set(), year: null, sort: { col: 'est', dir: -1 } };

  async function getJSON(url) {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`${url} ${r.status}`);
    return r.json();
  }

  async function init() {
    try {
      const idx = await getJSON('data/index.json');
      const q = new URLSearchParams(location.search).get('month');
      const months = idx.months || [];
      let month = (q && months.includes(q)) ? q : (idx.pinned && months.includes(idx.pinned) ? idx.pinned : idx.latest);
      const data = await getJSON(`data/${month}.json`);
      state.data = data;
      render(idx);
    } catch (e) {
      document.querySelector('main').innerHTML = `<section class="wrap hero"><h2>資料暫時無法載入</h2><p class="lead">${esc(e.message)}</p></section>`;
    }
  }

  function render(idx) {
    const d = state.data, m = d.meta, HL = m.highlight;
    const mon = Number(m.month.slice(4));
    state.HL = HL; state.mon = mon;
    state.B = Object.fromEntries(d.banks.map((b) => [b.bank, b]));
    document.title = `基金保管市場看板｜資料年月 ${m.month_label}`;
    $('#top-month').textContent = `資料年月 ${m.month_label}`;
    $('#hero-bank').textContent = HL;

    const od = (m.sources || []).filter((s) => s.last_modified_tw).map((s) => s.last_modified_tw).sort();
    $('#meta-row').innerHTML = [
      `資料年月 ${m.month_label}`,
      `規模基準日 ${m.aum_date}`,
      od.length ? `公會檔案更新 ${od[od.length - 1].slice(0, 10)}` : null,
      `本頁資料產生 ${m.generated_at.slice(0, 10)}`,
      '只用公開資料',
    ].filter(Boolean).map((t) => `<span class="chip">${esc(t)}</span>`).join('');
    if (idx.latest && idx.latest > m.month) {
      const n = $('#pin-notice');
      n.hidden = false;
      n.textContent = `公會已有 ${idx.latest.slice(0, 4)}/${idx.latest.slice(4)} 的資料；本頁目前固定顯示 ${m.month_label}，以便對照簡報。`;
    }

    renderKPIs();
    // 預設比較：檔數前 3 名中、非重點行的前兩家（2026/08 為第一、彰化）
    d.banks.filter((b) => b.bank !== HL).sort((a, b) => a.n_rank - b.n_rank).slice(1, 3).forEach((b) => state.cmp.add(b.bank));
    renderRankSeg();
    renderBars();
    renderCmp();
    state.year = d.years[d.years.length - 1].year;
    renderYears();
    renderTop();
    renderTypes();
    initFilters();
    renderFooter();
  }

  /* ── KPI ── */
  function renderKPIs() {
    const d = state.data, t = d.totals, s = state.B[state.HL];
    if (!s) { $('#kpis').innerHTML = ''; return; }
    const maxC = Math.max(...d.banks.map((b) => b.clients));
    const topC = d.banks.filter((b) => b.clients === maxC).map((b) => b.bank);
    const cards = [
      { label: '檔數市占', v: pct(s.n_share), r: rankTxt(s.n_rank), sub: `${num(s.n)} 檔／全市場 ${num(t.funds)} 檔` },
      { label: '規模市占', v: pct(s.aum_share), r: rankTxt(s.aum_rank), sub: `${amt(s.aum)}／全市場 ${amt(t.aum)}` },
      { label: `${state.mon} 月保管費市占`, v: pct(s.fee_share), r: rankTxt(s.fee_rank), sub: `${fee(s.fee)}／全市場 ${fee(t.fee)}` },
      { label: '投信客戶', v: `${s.clients} 家`, r: rankTxt(s.clients_rank), sub: `最多：${topC.join('、')}，各 ${maxC} 家` },
    ];
    $('#kpis').innerHTML = cards.map((c, i) => `
      <div class="stat${i === 0 ? ' is-accent' : ''}">
        <span class="stat-label">${esc(state.HL)}｜${esc(c.label)}</span>
        <div class="stat-value"><strong>${esc(c.v)}</strong><span class="stat-rank">${esc(c.r)}</span></div>
        <span class="stat-sub">${esc(c.sub)}</span>
      </div>`).join('');
    const avgS = s.aum / s.n, avgM = t.aum / t.funds;
    let cap = `同一檔基金的不同級別只算 1 檔。${state.HL}平均每檔 ${num(avgS)} 億，全市場平均每檔 ${num(avgM)} 億`;
    if (s.n_rank < s.aum_rank) cap += `——所以「檔數」排名比「規模」排名前面：保管的基金多、但平均每檔較小。`;
    else cap += '。';
    $('#kpi-caption').textContent = cap;
  }

  /* ── ranking ── */
  const RK = {
    n: { label: '依檔數：各保管行仍存續的基金檔數與市占', val: (b) => b.n, share: 'n_share', rank: 'n_rank', fmt: (b) => `${num(b.n)} 檔` },
    aum: { label: '', val: (b) => b.aum, share: 'aum_share', rank: 'aum_rank', fmt: (b) => amt(b.aum) },
    fee: { label: '', val: (b) => b.fee, share: 'fee_share', rank: 'fee_rank', fmt: (b) => fee(b.fee) },
  };

  function renderRankSeg() {
    const m = state.data.meta;
    RK.aum.label = `依規模：各保管行保管的基金規模（${m.aum_date}）與市占`;
    RK.fee.label = `依保管費：各保管行 ${state.mon} 月保管費收入與市占`;
    $('#rank-seg').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      state.key = b.dataset.k;
      $('#rank-seg').querySelectorAll('button').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
      renderBars();
    });
    $('#bars-toggle').addEventListener('click', () => { state.showAll = !state.showAll; renderBars(); });
  }

  function renderBars() {
    const k = RK[state.key], d = state.data;
    const list = [...d.banks].sort((a, b) => a[k.rank] - b[k.rank] || k.val(b) - k.val(a));
    const max = Math.max(...list.map(k.val));
    const shown = state.showAll ? list : list.slice(0, 10);
    $('#rank-label').textContent = `${k.label}${state.showAll ? '' : '（前 10 名）'}`;
    $('#bars').innerHTML = shown.map((b) => {
      const cls = b.bank === state.HL ? ' is-hl' : (state.cmp.has(b.bank) ? ' is-cmp' : '');
      return `<li class="bar-row${cls}">
        <span class="bar-rank">${b[k.rank]}</span>
        <span class="bar-name" title="${esc(b.bank)}">${esc(b.bank)}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${(k.val(b) / max * 100).toFixed(1)}%"></span></span>
        <span class="bar-val">${pct(b[k.share])}<small>${esc(k.fmt(b))}</small></span>
      </li>`;
    }).join('');
    $('#bars-toggle').textContent = state.showAll ? '只看前 10 名' : `顯示全部 ${list.length} 家`;
  }

  function renderCmp() {
    const d = state.data, HL = state.HL;
    const opts = [...d.banks].filter((b) => b.bank !== HL).sort((a, b) => a.n_rank - b.n_rank).slice(0, 10);
    $('#cmp-chips').innerHTML = `<button class="chip is-hl" aria-pressed="true" disabled>${esc(HL)}</button>` +
      opts.map((b) => `<button class="chip" type="button" data-bank="${esc(b.bank)}" aria-pressed="${state.cmp.has(b.bank)}">${esc(b.bank)}</button>`).join('');
    $('#cmp-chips').onclick = (e) => {
      const btn = e.target.closest('button[data-bank]'); if (!btn) return;
      const bk = btn.dataset.bank;
      if (state.cmp.has(bk)) state.cmp.delete(bk);
      else { if (state.cmp.size >= 3) state.cmp.delete([...state.cmp][0]); state.cmp.add(bk); }
      renderCmp(); renderBars();
    };
    const rows = [state.B[HL], ...[...state.cmp].map((b) => state.B[b]).sort((a, b) => a.n_rank - b.n_rank)].filter(Boolean);
    const cell = (v, r) => `${esc(v)}<span class="rk">（${r}）</span>`;
    const t = d.totals;
    $('#cmp-table').innerHTML = `
      <thead><tr><th>保管行</th><th>檔數市占</th><th>規模市占</th><th>${state.mon} 月保管費市占</th><th>投信客戶</th></tr></thead>
      <tbody>${rows.map((b) => `<tr class="${b.bank === HL ? 'is-hl' : ''}">
        <td>${esc(b.bank)}</td>
        <td>${cell(pct(b.n_share), b.n_rank)}</td>
        <td>${cell(pct(b.aum_share), b.aum_rank)}</td>
        <td>${cell(pct(b.fee_share), b.fee_rank)}</td>
        <td>${cell(`${b.clients} 家`, b.clients_rank)}</td></tr>`).join('')}
        <tr><td>全市場</td><td>${num(t.funds)} 檔</td><td>${amt(t.aum)}</td><td>${fee(t.fee)}</td><td>${num(t.companies)} 家投信</td></tr>
      </tbody>`;
  }

  /* ── new funds ── */
  function yearLabel(y) { return y.partial ? `${y.year} 年（至 ${state.mon} 月）` : `${y.year} 年`; }

  function renderYears() {
    const d = state.data, HL = state.HL, s = state.B[HL];
    const ys = d.years.map((y) => ({ y, b: y.banks.find((b) => b.bank === HL) }));
    const last = ys[ys.length - 1];
    if (last.b) {
      $('#new-title').textContent = `${yearLabel(last.y)}新基金：${HL}檔數${rankTxt(last.b.rank, last.b.tied)}，以規模計第 ${last.b.aum_rank}`;
    }
    $('#yr-label').textContent = `${HL}｜逐年新基金檔數市占（對照存量 ${pct(s.n_share)}）`;
    const max = Math.max(...ys.map((x) => (x.b ? x.b.share : 0)), s.n_share) * 1.12;
    $('#yearbars').innerHTML = ys.map(({ y, b }, i) => {
      const share = b ? b.share : 0;
      const cls = i === ys.length - 1 ? ' is-now' : (share < s.n_share ? ' is-low' : '');
      return `<div class="yb${cls}">
        <span class="yb-val">${pct(share)}</span>
        <span class="yb-rank">${b ? rankTxt(b.rank, b.tied) : '0 檔'}</span>
        <span class="yb-col" style="height:${Math.max(4, share / max * 150).toFixed(0)}px"></span>
        <span class="yb-year">${y.year}${y.partial ? '*' : ''}</span>
        <span class="yb-sub">${b ? b.n : 0}／${y.total} 檔</span>
      </div>`;
    }).join('');
    $('#yr-note').textContent = `${last.y.partial ? `* ${last.y.year} 年只到 ${state.mon} 月。` : ''}只含目前仍存續的基金；成立日用「基金」成立日（不用級別成立日，避免老基金新增級別被誤算成新基金）。`;
    $('#year-seg').innerHTML = d.years.map((y) => `<button role="tab" data-y="${y.year}" aria-selected="${y.year === state.year}">${y.year}</button>`).join('');
    $('#year-seg').onclick = (e) => {
      const b = e.target.closest('button'); if (!b) return;
      state.year = Number(b.dataset.y);
      $('#year-seg').querySelectorAll('button').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
      renderTop();
    };
  }

  function renderTop() {
    const d = state.data, HL = state.HL;
    const y = d.years.find((x) => x.year === state.year);
    const top = y.banks.filter((b) => b.rank <= 3);
    const hl = y.banks.find((b) => b.bank === HL);
    const rows = [...top];
    if (hl && !top.includes(hl)) rows.push(hl);
    $('#top-label').textContent = `${yearLabel(y)}新基金 ${y.total} 檔｜前三名保管行`;
    $('#top-table').innerHTML = `
      <thead><tr><th>保管行</th><th>新基金</th><th>檔數市占</th><th>其中 ETF 類</th><th>其中主動式 ETF</th><th>現規模</th></tr></thead>
      <tbody>${rows.map((b) => `<tr class="${b.bank === HL ? 'is-hl' : ''}">
        <td>${esc(b.bank)}<span class="rk">${rankTxt(b.rank, b.tied)}</span></td>
        <td>${b.n} 檔</td><td>${pct(b.share)}</td><td>${b.etf}</td><td>${b.active}</td>
        <td>${num(b.aum)} 億<span class="rk">（${b.aum_rank}）</span></td></tr>`).join('')}
      </tbody>`;
    const byA = [...y.banks].sort((a, b) => a.aum_rank - b.aum_rank).slice(0, 3);
    let note = `以現規模計：${byA.map((b) => `${b.bank} ${num(b.aum)} 億`).join('、')}`;
    if (hl && !byA.includes(hl)) note += `；${HL} ${num(hl.aum)} 億（${pct(hl.aum_share)}，第 ${hl.aum_rank}）`;
    note += '。';
    const al = d.active_etf, alHL = (al.by_bank.find((b) => b.bank === HL) || { n: 0 }).n;
    note += `主動式 ETF 歷年 ${al.total} 檔，${HL} ${alHL} 檔。`;
    $('#top-note').textContent = note;
  }

  function renderTypes() {
    const d = state.data, HL = state.HL, w = d.meta.window;
    $('#type-label').textContent = `新基金依產品類型｜${w.label} 成立（共 ${d.totals.newfunds_window} 檔）`;
    const max = Math.max(...d.newfund_types.map((t) => t.n));
    $('#type-table').innerHTML = `
      <thead><tr><th>產品類型</th><th>檔數</th><th>現規模</th><th>其中${esc(HL)}</th><th>主要承接保管行</th></tr></thead>
      <tbody>${d.newfund_types.map((t) => `<tr>
        <td><span class="mini" style="width:${(t.n / max * 64).toFixed(0)}px"></span>${esc(t.group)}</td>
        <td>${t.n} 檔</td><td>${num(t.aum)} 億</td><td>${t.hl} 檔</td>
        <td>${t.top.map((b) => `${esc(b.bank)} ${b.n}`).join('、')}</td></tr>`).join('')}
      </tbody>`;
  }

  /* ── fund list ── */
  const COLS = [
    { k: 'est', t: '成立日' }, { k: 'co', t: '投信' }, { k: 'name', t: '基金名稱' }, { k: 'type', t: '產品類型' },
    { k: 'bank', t: '保管行' }, { k: 'aum', t: '現規模（億）', n: true }, { k: 'fee', t: '月保管費（萬）', n: true },
  ];
  const typeOf = (f) => (f.group === '其他' ? `其他（${f.cat}）` : f.group);

  function initFilters() {
    const d = state.data, HL = state.HL, w = d.meta.window;
    const cos = Object.entries(d.funds.reduce((a, f) => ((a[f.co] = (a[f.co] || 0) + 1), a), {})).sort((a, b) => b[1] - a[1]);
    $('#f-co').innerHTML = `<option value="">全部（${cos.length} 家）</option>` + cos.map(([c, n]) => `<option value="${esc(c)}">${esc(c)}（${n}）</option>`).join('');
    const banks = [...d.banks].sort((a, b) => a.n_rank - b.n_rank);
    $('#f-bank').innerHTML = `<option value="">全部（${banks.length} 家）</option>` + banks.map((b) => `<option value="${esc(b.bank)}">${esc(b.bank)}（${b.n}）</option>`).join('');
    const groups = ['主動式 ETF', '被動股票 ETF', '債券 ETF', '多重資產／平衡／組合', '指數基金／ETF 連結', '其他'];
    $('#f-group').innerHTML = '<option value="">全部類型</option>' + groups.map((g) => `<option>${esc(g)}</option>`).join('');
    ['#f-from', '#f-to'].forEach((s) => { $(s).max = w.end; });
    const Y = d.years[d.years.length - 1].year;
    const presets = [
      { t: `彰化 × ${Y} 年新基金`, f: { bank: '彰化', from: `${Y}-01-01` } },
      { t: '主動式 ETF 給了誰', f: { group: '主動式 ETF' } },
      { t: '復華的基金放在哪幾家', f: { co: '復華投信' } },
      { t: `${HL} × 新案期間（${w.label}）`, f: { bank: HL, from: w.start } },
      { t: '清除條件', f: {} },
    ].filter((p) => (!p.f.bank || state.B[p.f.bank]) && (!p.f.co || cos.some(([c]) => c === p.f.co)));
    $('#presets').innerHTML = presets.map((p, i) => `<button class="chip" type="button" data-i="${i}">${esc(p.t)}</button>`).join('');
    $('#presets').onclick = (e) => {
      const b = e.target.closest('button'); if (!b) return;
      const f = presets[Number(b.dataset.i)].f;
      $('#f-co').value = f.co || ''; $('#f-bank').value = f.bank || ''; $('#f-group').value = f.group || '';
      $('#f-from').value = f.from || ''; $('#f-to').value = f.to || ''; $('#f-q').value = '';
      renderList();
    };
    ['#f-co', '#f-bank', '#f-group', '#f-from', '#f-to'].forEach((s) => $(s).addEventListener('change', renderList));
    $('#f-q').addEventListener('input', renderList);
    $('#csv-btn').addEventListener('click', downloadCSV);
    renderList();
  }

  function filtered() {
    const co = $('#f-co').value, bank = $('#f-bank').value, g = $('#f-group').value;
    const from = $('#f-from').value, to = $('#f-to').value, q = $('#f-q').value.trim().toLowerCase();
    let L = state.data.funds.filter((f) => (!co || f.co === co) && (!bank || f.bank === bank) && (!g || f.group === g)
      && (!from || f.est >= from) && (!to || f.est <= to) && (!q || f.name.toLowerCase().includes(q) || f.co.toLowerCase().includes(q)));
    const { col, dir } = state.sort;
    const key = col === 'type' ? typeOf : (f) => f[col];
    L = L.slice().sort((a, b) => {
      const x = key(a), y = key(b);
      return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y), 'zh-Hant')) * dir;
    });
    return L;
  }

  function renderList() {
    const L = filtered(), HL = state.HL, all = state.data.funds.length;
    const sumA = L.reduce((a, f) => a + f.aum, 0);
    $('#list-count').innerHTML = `符合條件 <em>${num(L.length)}</em> 檔${L.length < all ? `（全部 ${num(all)} 檔）` : ''}｜現規模合計 ${amt(sumA)}`;
    const bank = $('#f-bank').value;
    const by = (k) => Object.entries(L.reduce((a, f) => ((a[f[k]] = (a[f[k]] || 0) + 1), a), {})).sort((a, b) => b[1] - a[1]);
    const parts = bank ? by('co') : by('bank');
    $('#list-breakdown').textContent = L.length ? `${bank ? '依投信' : '依保管行'}：${parts.slice(0, 8).map(([k, n]) => `${k} ${n}`).join('、')}${parts.length > 8 ? `…等 ${parts.length} 家` : ''}` : '';
    const { col, dir } = state.sort;
    const head = `<thead><tr>${COLS.map((c) => `<th data-col="${c.k}" aria-sort="${c.k === col ? (dir > 0 ? 'ascending' : 'descending') : 'none'}" scope="col">${c.t}</th>`).join('')}</tr></thead>`;
    const body = L.length ? L.map((f) => `<tr class="${f.bank === HL ? 'is-hl' : ''}">
        <td>${esc(f.est)}</td><td>${esc(f.co)}</td><td>${esc(f.name)}</td><td>${esc(typeOf(f))}</td>
        <td>${esc(f.bank)}</td><td>${num(f.aum, 1)}</td><td>${num(f.fee / 1e4, 1)}</td></tr>`).join('')
      : `<tr><td colspan="${COLS.length}" class="empty">沒有符合條件的基金，請放寬條件。</td></tr>`;
    $('#fund-table').innerHTML = `${head}<tbody>${body}</tbody>`;
    $('#fund-table thead').onclick = (e) => {
      const th = e.target.closest('th'); if (!th) return;
      const c = th.dataset.col;
      state.sort = { col: c, dir: state.sort.col === c ? -state.sort.dir : (COLS.find((x) => x.k === c).n || c === 'est' ? -1 : 1) };
      renderList();
    };
  }

  function downloadCSV() {
    const L = filtered(), m = state.data.meta;
    const head = ['資料年月', '基金統編', '成立日', '投信', '基金名稱', '類型代號', '產品類型', '保管行', '現規模(億元)', `${state.mon}月保管費(元)`];
    // 試算表會把以 =、+、-、@ 開頭的文字當成公式；匯出時保留為純文字。
    const q = (v) => {
      let s = String(v == null ? '' : v);
      if (/^[\s\u0000-\u001f]*[=+\-@]/.test(s)) s = "'" + s;
      return `"${s.replace(/"/g, '""')}"`;
    };
    const lines = [head.map(q).join(',')].concat(L.map((f) => [m.month, f.id, f.est, f.co, f.name, f.code, typeOf(f), f.bank, f.aum, f.fee].map(q).join(',')));
    const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const tag = [$('#f-co').value, $('#f-bank').value, $('#f-group').value].filter(Boolean).join('_');
    a.download = `保管市場明細_${m.month}${tag ? '_' + tag : ''}.csv`.replace(/[\\/:*?"<>|]/g, '');
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  /* ── footer ── */
  function renderFooter() {
    const d = state.data, m = d.meta, t = d.totals, q = d.quality;
    $('#sources').innerHTML = (m.sources || []).map((s) => `<li><a href="${esc(s.page)}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a>（${esc(s.dataset)}）${s.last_modified_tw ? `<br>公會檔案更新：${esc(s.last_modified_tw)}` : ''}</li>`).join('') +
      `<li>資料年月 <b>${esc(m.month_label)}</b>；公會約在次月 8～16 日公布上月資料，本頁每天檢查一次，有新月份才更新。</li>`;
    const defs = [
      `「檔」＝基金統編前 8 碼：同一基金的不同級別只算 1 檔（共 ${num(t.funds)} 檔、${num(t.classes)} 個級別）。`,
      `兩份 SITCA 報表以「基金統編」合併：${num(q.matched)}／${num(q.std_rows)} 列全數配對；不靠列的位置對齊。`,
      `規模＝${esc(m.aum_date)} 基金規模（依基金別，新台幣）；保管費＝${state.mon} 月保管費。`,
      '新基金依「基金」成立日（SITCA「標準」報表）計算，不用級別成立日；只含目前仍存續的基金。',
      `新案期間＝${esc(m.window.label)}；只看國內保管行，不含國外受託保管機構；排名並列時名次相同。`,
      '永豐投信與永豐商銀同屬永豐金控，依法原則上不能由永豐保管（證券投資信託及顧問法第 22 條）。',
    ];
    $('#defs').innerHTML = defs.map((x) => `<li>${x}</li>`).join('');
    const icon = { pass: '<span class="ok">✓</span>', warn: '<span class="warn">！</span>', fail: '<span class="bad">✗</span>' };
    $('#checks').innerHTML = d.checks.map((c) => `<li>${icon[c.status]}<span><b>${esc(c.name)}</b><br>${esc(c.detail)}</span></li>`).join('');
    $('#footer-note').textContent = `每月更新，非即時｜只使用公開資料，不含任何客戶資料｜本頁為課程示範，不構成投資或業務建議｜本頁資料產生：${m.generated_at}（台北時間）`;
  }

  init();
})();
