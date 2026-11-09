// TIM-Chart: interactive candles with labelled level segments (read-only, no orders).
// Data: /api/chart/live?symbol=&tf= (src/dashboard/chart_live.py). Library: TradingView
// Lightweight Charts 4.2.3 (Apache 2.0), served locally from /assets/chart/.
(() => {
  'use strict';
  const host = document.getElementById('tc-live');
  if (!host || !window.LightweightCharts) return;
  const LWC = window.LightweightCharts;
  // Version of this script as the page loaded it (?v= in the script tag). The API answer names the version
  // the server runs now; a tab left open across an update reloads itself once, otherwise it keeps drawing
  // with the old code for hours (Uzi 30.10.2026: no position boxes after the merge).
  const SCRIPT_VERSION = (() => {
    try { return new URL(document.currentScript.src).searchParams.get('v') || ''; } catch (error) { return ''; }
  })();
  function reloadOnNewVersion(version) {
    if (!version || !SCRIPT_VERSION || version === SCRIPT_VERSION) return false;
    try {
      if (sessionStorage.getItem('tim-chart-reloaded') === version) return false;  // never a reload loop
      sessionStorage.setItem('tim-chart-reloaded', version);
    } catch (error) { return false; }
    location.reload();
    return true;
  }
  // Two charts side by side (Uzi 09.11.2026): the page holds two panes, each one is a full chart of its own
  // (coin, timeframe, market, layout). PANE is '' for the first and '-2' for the second; it is the suffix of
  // the element ids and of the browser memory, so the two never overwrite each other. The first pane keeps
  // coin and timeframe in the address, the second one in localStorage.
  const SPLIT_STORE = 'tim-chart-split-v1';
  const PANE2_STORE = 'tim-chart-pane2-v1';
  let secondPane = null;
  function setSplit(on) {
    const pane = document.getElementById('tc-pane-2');
    const wrap = document.getElementById('tc-split');
    if (!pane || !wrap) return;
    pane.hidden = !on;
    wrap.classList.toggle('tc-split--on', on);
    host.querySelectorAll("#tc-pane [data-action='split']").forEach(node => {
      node.setAttribute('aria-pressed', on ? 'true' : 'false');
      node.textContent = (on ? '✓ ' : '') + node.textContent.replace(/^✓ /, '');  // a tick, like Spot/Perp
    });
    try { localStorage.setItem(SPLIT_STORE, on ? '1' : '0'); } catch (error) { /* ignore */ }
    if (on) { if (secondPane) secondPane.resume(); else secondPane = start('-2'); } else if (secondPane) secondPane.pause();
  }
  function start(PANE) {
  const root = document.getElementById('tc-pane' + PANE);
  if (!root) return null;
  const box = document.getElementById('tc-live-chart' + PANE);
  const legend = document.getElementById('tc-live-legend' + PANE);
  const status = document.getElementById('tc-live-status' + PANE);
  const layers = document.getElementById('tc-live-layers' + PANE);
  const STORE = 'tim-chart-layers-v1' + PANE;
  const SHORT_BARS = 12;
  const STYLE = { solid: LWC.LineStyle.Solid, dotted: LWC.LineStyle.Dotted, dashed: LWC.LineStyle.Dashed };
  let symbol = (PANE ? root : host).dataset.symbol, timeframe = (PANE ? root : host).dataset.tf;
  let timer = null, model = null, first = true, request = 0, running = true;
  function markTabs() {
    root.querySelectorAll('a[data-tf]').forEach(node => {
      const on = node.dataset.tf === timeframe;
      node.classList.toggle('tc-tab--active', on);
      if (on) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current');
    });
    if (!PANE) return;
    root.querySelectorAll('a[data-symbol]').forEach(node => {
      const on = node.dataset.symbol === symbol;
      node.classList.toggle('tc-tab--active', on);
      if (on) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current');
    });
  }
  function rememberPane() {
    if (!PANE) return;
    try { localStorage.setItem(PANE2_STORE, JSON.stringify({ symbol, tf: timeframe })); } catch (error) { /* ignore */ }
  }
  if (PANE) {  // the second pane remembers its own coin and timeframe; only values the page offers count
    try {
      const saved = JSON.parse(localStorage.getItem(PANE2_STORE) || 'null') || {};
      if (root.querySelector(`a[data-symbol='${CSS.escape(String(saved.symbol))}']`)) symbol = saved.symbol;
      if (root.querySelector(`a[data-tf='${CSS.escape(String(saved.tf))}']`)) timeframe = saved.tf;
    } catch (error) { /* ignore */ }
    markTabs();
  }
  // Spot or perp trades behind volume profile, footprint, delta and bubbles (Beirat 29.10.2026, F5).
  const MARKET_STORE = 'tim-chart-market-v1' + PANE;
  let market = (() => { try { return localStorage.getItem(MARKET_STORE) || 'spot'; } catch (error) { return 'spot'; } })();
  let lines = [];

  // The public view (src/dashboard/public_en.py) sets data-lang='en'; the Control Center stays German.
  const EN = host.dataset.lang === 'en';
  const LOCALE = EN ? 'en-US' : 'de-DE';
  // Times stay in UTC seconds on the axis (strictly ascending, also across the DST change); only the
  // labels show the viewer's local time, per point, so candles before and after the change both
  // carry the clock time Discord and TradingView show (a fixed offset put earlier candles one hour off).
  const local = t => t;
  const ZONE = { hour12: false };
  const TIME_FMT = new Intl.DateTimeFormat(LOCALE, { ...ZONE, hour: '2-digit', minute: '2-digit' });
  const DAY_FMT = new Intl.DateTimeFormat(LOCALE, { ...ZONE, day: '2-digit', month: '2-digit' });
  const MONTH_FMT = new Intl.DateTimeFormat(LOCALE, { ...ZONE, month: 'short', year: '2-digit' });
  const YEAR_FMT = new Intl.DateTimeFormat(LOCALE, { ...ZONE, year: 'numeric' });
  const FULL_FMT = new Intl.DateTimeFormat(LOCALE, { ...ZONE, weekday: 'short', day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
  const asDate = t => new Date(Number(t) * 1000);
  const tickLabel = (t, type) => {
    const d = asDate(t);
    if (type === 0) return YEAR_FMT.format(d);
    if (type === 1) return MONTH_FMT.format(d);
    if (type === 2) return DAY_FMT.format(d);
    return TIME_FMT.format(d);
  };
  const T = EN
    ? { slNow: 'SL now', running: ' running', periods: ' periods', price: 'Price', loading: 'Loading…', candles: 'candles', asOf: 'as of', next: 'Next release',
        failed: m => `Loading failed (${m}). Retrying in 30 s.` }
    : { slNow: 'SL jetzt', running: ' lfd.', periods: ' Perioden', price: 'Kurs', loading: 'Lade…', candles: 'Kerzen', asOf: 'Stand', next: 'Nächster Termin',
        failed: m => `Laden fehlgeschlagen (${m}). Neuer Versuch in 30 s.` };
  const P = EN
    ? { cvdSpot: 'CVD spot', cvdPerp: 'CVD perp', delta: 'Delta volume', oi: 'OI Binance (BTC)', oiBybit: 'OI Bybit (BTC)', oiZ: 'OI Z 7.5d', funding: 'Funding % / 8h', premium: 'Coinbase premium %', domBtc: 'BTC.D %', domUsdt: 'USDT.D %',
        health: (ok, n, gaps) => `Perp check: ${ok}/${n} h equal to Binance, ${gaps} gaps` }
    : { cvdSpot: 'CVD Spot', cvdPerp: 'CVD Perp', delta: 'Delta Volume', oi: 'OI Binance (BTC)', oiBybit: 'OI Bybit (BTC)', oiZ: 'OI Z 7,5 T', funding: 'Funding % / 8 h', premium: 'Coinbase-Premium %', domBtc: 'BTC.D %', domUsdt: 'USDT.D %',
        health: (ok, n, gaps) => `Perp-Prüfung: ${ok}/${n} h gleich mit Binance, ${gaps} Lücken` };
  const fmt = v => v == null ? '–' : Number(v).toLocaleString(LOCALE, { maximumFractionDigits: v < 10 ? 4 : v < 1000 ? 2 : 1 });

  const chart = LWC.createChart(box, {
    autoSize: true,
    layout: { background: { type: 'solid', color: '#0b0f16' }, textColor: '#c3cad6', fontSize: 12, attributionLogo: false },
    grid: { vertLines: { color: 'rgba(120,134,156,0.10)' }, horzLines: { color: 'rgba(120,134,156,0.10)' } },
    crosshair: { mode: LWC.CrosshairMode.Normal },
    rightPriceScale: { borderColor: 'rgba(120,134,156,0.35)', scaleMargins: { top: 0.06, bottom: 0.18 } },
    timeScale: { borderColor: 'rgba(120,134,156,0.35)', timeVisible: true, secondsVisible: false, rightOffset: 8, tickMarkFormatter: tickLabel },
    localization: { locale: LOCALE, priceFormatter: fmt, timeFormatter: t => FULL_FMT.format(asDate(t)) },
    // Phone: a vertical swipe over the chart scrolls the page. Otherwise it moved the chart up or down and
    // switched the automatic price scale off (Uzi 06.11.2026: price axis 68k-86k around 75k-81k candles).
    handleScroll: { vertTouchDrag: false },
  });
  const autoPrice = () => chart.priceScale('right').applyOptions({ autoScale: true });
  const candles = chart.addCandlestickSeries({
    upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    priceLineColor: '#c3cad6',
  });
  const volume = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });

  // Lower bands under the candles: CVD spot vs. perp (each on its own scale, perp volume is 8-12x spot)
  // and open interest with its 7.5-day Z-score. Lightweight Charts 4 has no panes, so each band is a
  // price scale with its own margins; the candles move up while a band is on.
  const band = { lastValueVisible: true, priceLineVisible: false, crosshairMarkerVisible: false };
  const cvdSpot = chart.addLineSeries({ ...band, priceScaleId: 'cvd_spot', color: '#5ec8d8', lineWidth: 2, title: P.cvdSpot, visible: false });
  const cvdPerp = chart.addLineSeries({ ...band, priceScaleId: 'cvd_perp', color: '#ffb020', lineWidth: 2, title: P.cvdPerp, visible: false });
  // Delta per candle of the chosen market (difference of the CVD line), with a line at ± the size 90 % of the
  // candles stay below: the candles that stick out are the ones worth a look (Uzi 09.11.2026).
  let deltaMarks = [], deltaEdge = 0;
  const deltaBars = chart.addHistogramSeries({
    ...band, priceScaleId: 'delta', title: P.delta, visible: false, priceFormat: { type: 'volume' },
    autoscaleInfoProvider: original => {  // the band always holds both threshold lines, also while only small candles are in view
      const info = original();
      if (info && info.priceRange && deltaEdge > 0) {
        info.priceRange.minValue = Math.min(info.priceRange.minValue, -deltaEdge * 1.15);
        info.priceRange.maxValue = Math.max(info.priceRange.maxValue, deltaEdge * 1.15);
      }
      return info;
    },
  });
  const oiZ = chart.addHistogramSeries({ ...band, priceScaleId: 'oi_z', title: P.oiZ, visible: false, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
  const oiLine = chart.addLineSeries({ ...band, priceScaleId: 'oi', color: '#c3cad6', lineWidth: 1, title: P.oi, visible: false,
                                       priceFormat: { type: 'volume' } });
  // Second venue (issue #162): Bybit linear open interest on the same scale, so the two lines compare in BTC.
  const oiBybit = chart.addLineSeries({ ...band, priceScaleId: 'oi', color: '#f7a35c', lineWidth: 1, title: P.oiBybit, visible: false,
                                        priceFormat: { type: 'volume' } });
  // Funding (scaled to 8 h so symbols compare) and Coinbase premium (Coinbase USD vs. Binance USDT in USD), both start hidden.
  const fundingBars = chart.addHistogramSeries({ ...band, priceScaleId: 'funding', title: P.funding, visible: false,
                                                 priceFormat: { type: 'price', precision: 4, minMove: 0.0001 } });
  const premiumLine = chart.addBaselineSeries({ ...band, priceScaleId: 'premium', title: P.premium, visible: false, baseValue: { type: 'price', price: 0 },
                                               topLineColor: '#26a69a', topFillColor1: 'rgba(38,166,154,0.28)', topFillColor2: 'rgba(38,166,154,0.04)',
                                               bottomLineColor: '#ef5350', bottomFillColor1: 'rgba(239,83,80,0.04)', bottomFillColor2: 'rgba(239,83,80,0.28)',
                                               lineWidth: 1, priceFormat: { type: 'price', precision: 3, minMove: 0.001 } });
  // BTC and USDT dominance (daily, market-wide), each on its own scale in one band; starts hidden.
  const domBtc = chart.addLineSeries({ ...band, priceScaleId: 'dom_btc', color: '#f7931a', lineWidth: 2, title: P.domBtc, visible: false,
                                       priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
  const domUsdt = chart.addLineSeries({ ...band, priceScaleId: 'dom_usdt', color: '#26a17b', lineWidth: 2, title: P.domUsdt, visible: false,
                                        priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
  // Upcoming CPI/FOMC dates after the last candle: empty (whitespace) candles to the right keep the time
  // axis evenly spaced, an invisible line carries the markers at the last price.
  const ahead = chart.addLineSeries({ lineVisible: false, lastValueVisible: false, priceLineVisible: false,
                                      crosshairMarkerVisible: false, autoscaleInfoProvider: () => null });
  const BAND = 0.15;
  const BAND_SCALES = { cvd: ['cvd_spot', 'cvd_perp'], delta: ['delta'], oi: ['oi', 'oi_z'], funding: ['funding'], premium: ['premium'], dominance: ['dom_btc', 'dom_usdt'] };
  const bandHasData = key => {
    if (key === 'delta') return deltaSource().length > 1;
    const part = model && model[key];
    if (!part) return false;
    return key === 'cvd' ? part.spot.length || part.perp.length : part.points.length;
  };
  const deltaSource = () => {  // the chosen market's CVD line; the other one if it has no trades yet
    const cvd = model && model.cvd;
    if (!cvd) return [];
    const first = market === 'perp' ? cvd.perp : cvd.spot, second = market === 'perp' ? cvd.spot : cvd.perp;
    return first.length > 1 ? first : second;
  };
  function layoutBands(groups) {
    const shown = ['delta', 'cvd', 'oi', 'funding', 'premium', 'dominance'].filter(key => groups.has(key) && bandHasData(key));
    chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.06, bottom: 0.18 + BAND * shown.length } });
    shown.forEach((key, index) => {
      const top = 0.82 - BAND * (shown.length - index) + 0.01;
      const margins = { top, bottom: 1 - top - BAND + 0.02 };
      for (const id of BAND_SCALES[key]) chart.priceScale(id).applyOptions({ scaleMargins: margins, visible: false });
    });
    deltaBars.applyOptions({ visible: shown.includes('delta') });
    cvdSpot.applyOptions({ visible: shown.includes('cvd') });
    cvdPerp.applyOptions({ visible: shown.includes('cvd') });
    oiLine.applyOptions({ visible: shown.includes('oi') });
    oiBybit.applyOptions({ visible: shown.includes('oi') && oiBybit.data().length > 0 });
    oiZ.applyOptions({ visible: shown.includes('oi') });
    fundingBars.applyOptions({ visible: shown.includes('funding') });
    premiumLine.applyOptions({ visible: shown.includes('premium') });
    domBtc.applyOptions({ visible: shown.includes('dominance') });
    domUsdt.applyOptions({ visible: shown.includes('dominance') });
  }
  function drawBands() {
    const cvd = (model && model.cvd) || { spot: [], perp: [] };
    cvdSpot.setData(cvd.spot.map(([t, v]) => ({ time: local(t), value: v })));
    cvdPerp.setData(cvd.perp.map(([t, v]) => ({ time: local(t), value: v })));
    const source = deltaSource(), deltas = [];
    for (let i = 1; i < source.length; i += 1) deltas.push([source[i][0], source[i][1] - source[i - 1][1]]);
    deltaBars.setData(deltas.map(([t, v]) => ({ time: local(t), value: v, color: v >= 0 ? 'rgba(91,124,250,0.9)' : 'rgba(244,122,106,0.9)' })));
    for (const mark of deltaMarks) deltaBars.removePriceLine(mark);
    deltaMarks = [];
    const sizes = deltas.map(([, v]) => Math.abs(v)).sort((a, b) => a - b);
    const edge = sizes.length >= 20 ? sizes[Math.floor(sizes.length * 0.9)] : 0;
    deltaEdge = edge;
    if (edge > 0) {
      for (const price of [edge, -edge]) {
        deltaMarks.push(deltaBars.createPriceLine({ price, color: '#e8ecf3', lineWidth: 1, lineStyle: LWC.LineStyle.Solid, axisLabelVisible: false, title: '' }));
      }
    }
    // Open interest is hourly: each candle takes the last hour that began at or before it.
    const oi = model && model.oi;
    const at = (points, t) => { let found = null; for (const p of points) { if (p[0] <= t) found = p; else break; } return found; };
    const oiPoints = [], zPoints = [], bybitPoints = [];
    const bybit = oi && oi.venues ? oi.venues.find(v => v.venue === 'bybit') : null;
    if (oi && model.candles.length) {
      for (const c of model.candles) {
        const p = at(oi.points, c.time); if (p) oiPoints.push({ time: local(c.time), value: p[1] });
        if (bybit) { const b = at(bybit.points, c.time); if (b) bybitPoints.push({ time: local(c.time), value: b[1] }); }
        const z = at(oi.z, c.time);
        if (z) zPoints.push({ time: local(c.time), value: z[1], color: z[1] >= 2 ? 'rgba(255,107,61,0.85)' : z[1] <= -2 ? 'rgba(63,182,255,0.85)' : 'rgba(132,145,163,0.45)' });
      }
    }
    oiLine.setData(oiPoints);
    oiBybit.setData(bybitPoints);
    oiZ.setData(zPoints);
    // Funding per settlement and the hourly premium: each candle takes the last value that began at or before it.
    const fundingPoints = [], premiumPoints = [];
    const fund = model && model.funding, prem = model && model.premium;
    if (model && model.candles.length) {
      for (const c of model.candles) {
        const f = fund && at(fund.points, c.time);
        if (f) {
          const v = f[2];
          const color = v >= fund.high_8h ? 'rgba(255,107,61,0.85)' : v < 0 ? 'rgba(63,182,255,0.85)' : 'rgba(132,145,163,0.45)';
          fundingPoints.push({ time: local(c.time), value: v, color });
        }
        const p = prem && at(prem.points, c.time);
        if (p) premiumPoints.push({ time: local(c.time), value: p[1] });
      }
    }
    fundingBars.setData(fundingPoints);
    premiumLine.setData(premiumPoints);
    // Dominance per day (placed at the next 00:00 UTC): each candle takes the last complete day.
    const dom = model && model.dominance, btcD = [], usdtD = [];
    if (dom && model.candles.length) {
      for (const c of model.candles) {
        const d = at(dom.points, c.time);
        if (d) { btcD.push({ time: local(c.time), value: d[1] }); usdtD.push({ time: local(c.time), value: d[2] }); }
      }
    }
    domBtc.setData(btcD);
    domUsdt.setData(usdtD);
  }
  function showMarket() {
    const m = model && model.markets;
    root.querySelectorAll('[data-market]').forEach(node => {
      const key = node.dataset.market;
      const active = m ? m.active === key : market === key;
      // A tick instead of the tab colour: the page's button style would hide the active tab's text.
      node.textContent = (active ? '✓ ' : '') + (key === 'perp' ? 'Perp' : 'Spot');
      node.setAttribute('aria-pressed', active ? 'true' : 'false');
      node.disabled = !!m && !m.available.includes(key) && !active;
    });
  }

  // TPO profiles (Market Profile per day) drawn on the chart canvas behind the candles:
  // one row per price step, width = number of 30-minute periods that traded there,
  // value area brighter, POC marked, single prints in orange, letters when there is room.
  const tpo = {
    chart: null, series: null, requestUpdate: null, visible: true,
    attached(param) { this.chart = param.chart; this.series = param.series; this.requestUpdate = param.requestUpdate; },
    detached() { this.chart = null; this.series = null; },
    updateAllViews() {},
    autoscaleInfo() { return null; },
    paneViews() { return [this.view]; },
    view: {
      zOrder() { return 'bottom'; },
      renderer() {
        return {
          draw(target) {
            if (!tpo.visible || !tpo.chart || !model || !model.tpo || !model.tpo.length) return;
            target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
              const scale = tpo.chart.timeScale();
              const count = model.candles.length;
              const firstTime = local(model.candles[0].time);
              const leftEdge = scale.logicalToCoordinate(0);
              for (const day of model.tpo) {
                const start = local(Date.parse(day.start) / 1000);
                const end = local(Date.parse(day.end) / 1000);
                let x0 = scale.timeToCoordinate(start);
                if (x0 === null) { if (start < firstTime && leftEdge !== null) x0 = leftEdge; else continue; }
                let x1 = scale.timeToCoordinate(end);
                if (x1 === null) x1 = day.running ? scale.logicalToCoordinate(count - 1) : null;
                if (x1 === null) x1 = mediaSize.width;
                if (x1 < 0 || x0 > mediaSize.width) continue;
                x0 = Math.max(0, x0);  // a day that began left of the view keeps its profile at the left edge
                const span = Math.max(20, x1 - x0);
                const maxWidth = Math.min(span * 0.6, 160);
                const unit = maxWidth / Math.max(1, day.max_count);
                let anyLetters = false;
                for (const row of day.rows) {
                  const yTop = tpo.series.priceToCoordinate(row.price + day.step);
                  const yBottom = tpo.series.priceToCoordinate(row.price);
                  if (yTop === null || yBottom === null) continue;
                  const height = Math.max(1, yBottom - yTop - 1);
                  const width = Math.max(2, row.count * unit);
                  const inValue = row.price >= day.val && row.price <= day.vah;
                  ctx.fillStyle = row.price === day.poc ? 'rgba(245,197,66,0.70)' : row.single ? 'rgba(255,159,67,0.55)'
                    : inValue ? 'rgba(94,200,216,0.38)' : 'rgba(94,200,216,0.16)';
                  ctx.fillRect(x0 + 1, yTop + 0.5, width, height);
                  if (height >= 9 && unit >= 6.5) {
                    anyLetters = true;
                    ctx.fillStyle = 'rgba(230,236,245,0.85)';
                    ctx.font = '9px ui-monospace, Menlo, monospace';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(row.letters, x0 + 2, yTop + height / 2 + 0.5, width - 2);
                  }
                }
                const yLabel = tpo.series.priceToCoordinate(day.high);
                if (yLabel !== null) {
                  ctx.fillStyle = 'rgba(94,200,216,0.95)';
                  ctx.font = '11px ui-monospace, Menlo, monospace';
                  ctx.textBaseline = 'bottom';
                  ctx.fillText(`TPO ${day.label}${day.running ? T.running : ''} · POC ${fmt(day.poc)}${anyLetters ? '' : ' · ' + day.periods + T.periods}`, x0 + 2, Math.max(12, yLabel - 2));
                }
              }
            });
          },
        };
      },
    },
  };
  candles.attachPrimitive(tpo);

  // Volume profile per day from TIM's own trades: bars from the day's right edge to the left,
  // width = volume per price step, value area brighter, POC yellow; delta per row as a thin mark.
  const vp = {
    chart: null, series: null, requestUpdate: null, visible: true,
    attached(param) { this.chart = param.chart; this.series = param.series; this.requestUpdate = param.requestUpdate; },
    detached() { this.chart = null; this.series = null; },
    updateAllViews() {},
    autoscaleInfo() { return null; },
    paneViews() { return [this.view]; },
    view: {
      zOrder() { return 'bottom'; },
      renderer() {
        return {
          draw(target) {
            if (!vp.visible || !vp.chart || !model || !model.volume_profile || !model.volume_profile.length) return;
            target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
              const scale = vp.chart.timeScale();
              const count = model.candles.length;
              for (const day of model.volume_profile) {
                const start = local(Date.parse(day.start) / 1000);
                const end = local(Date.parse(day.end) / 1000);
                let x0 = scale.timeToCoordinate(start);
                let x1 = scale.timeToCoordinate(end);
                if (x1 === null) x1 = day.running ? scale.logicalToCoordinate(count - 1) : null;
                if (x1 === null) x1 = mediaSize.width;
                if (x0 === null) x0 = 0;
                if (x1 < 0 || x0 > mediaSize.width) continue;
                x1 = Math.min(x1, mediaSize.width);
                const maxWidth = Math.min(Math.max(20, x1 - x0) * 0.35, 120);
                const unit = maxWidth / Math.max(1e-9, day.max_volume);
                for (const row of day.rows) {
                  const yTop = vp.series.priceToCoordinate(row.price + day.step);
                  const yBottom = vp.series.priceToCoordinate(row.price);
                  if (yTop === null || yBottom === null) continue;
                  const height = Math.max(1, yBottom - yTop - 1);
                  const width = Math.max(1, row.volume * unit);
                  const inValue = row.price >= day.val && row.price <= day.vah;
                  ctx.fillStyle = row.price === day.poc ? 'rgba(245,197,66,0.75)' : inValue ? 'rgba(76,141,255,0.42)' : 'rgba(76,141,255,0.18)';
                  ctx.fillRect(x1 - width - 1, yTop + 0.5, width, height);
                  ctx.fillStyle = row.delta >= 0 ? 'rgba(38,166,154,0.9)' : 'rgba(239,83,80,0.9)';
                  ctx.fillRect(x1 - 3, yTop + 0.5, 2, height);  // thin delta mark at the edge: green = more aggressive buying
                }
                // Name under the profile (the TPO name sits at the top of the next day, at the same x).
                const yLabel = vp.series.priceToCoordinate(day.rows[0].price);
                if (yLabel !== null) {
                  ctx.fillStyle = 'rgba(140,180,255,0.95)';
                  ctx.font = '11px ui-monospace, Menlo, monospace';
                  ctx.textBaseline = 'top';
                  ctx.textAlign = 'right';
                  ctx.fillText(`VP ${day.label}${day.running ? T.running : ''} · POC ${fmt(day.poc)} · Δ ${day.delta >= 0 ? '+' : ''}${fmt(day.delta)}`, x1 - 4, Math.min(mediaSize.height - 14, yLabel + 3));
                  ctx.textAlign = 'left';
                }
              }
            });
          },
        };
      },
    },
  };
  candles.attachPrimitive(vp);

  // Estimated liquidation heatmap (src/liquidation_map): one band per price row from the period the
  // positions were opened until a candle traded through it (or to the right edge while still open).
  // Colour by size against the strongest cell: teal (small), yellow, red (large). An estimate, not orders.
  function heatColor(share, open) {
    const s = Math.max(0, Math.min(1, share));
    const [r, g, b] = s < 0.5 ? [Math.round(40 + 410 * s), Math.round(170 + 50 * s), Math.round(160 - 250 * s)]
      : [255, Math.round(195 - 230 * (s - 0.5)), Math.round(35 - 30 * (s - 0.5))];
    const alpha = (open ? 0.22 : 0.10) + (open ? 0.50 : 0.25) * s;
    return `rgba(${r},${Math.max(0, g)},${Math.max(0, b)},${alpha.toFixed(3)})`;
  }
  const liq = {
    chart: null, series: null, requestUpdate: null, visible: true,
    attached(param) { this.chart = param.chart; this.series = param.series; this.requestUpdate = param.requestUpdate; },
    detached() { this.chart = null; this.series = null; },
    updateAllViews() {},
    autoscaleInfo() { return null; },
    paneViews() { return [this.view]; },
    view: {
      zOrder() { return 'bottom'; },
      renderer() {
        return {
          draw(target) {
            const heat = model && model.liquidation;
            if (!liq.visible || !liq.chart || !heat || !heat.cells || !heat.cells.length) return;
            target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
              const scale = liq.chart.timeScale();
              const firstTime = local(model.candles[0].time);
              const right = scale.logicalToCoordinate(model.candles.length - 1 + 8);
              const max = Math.max(1, heat.max_usd);
              for (const cell of heat.cells) {
                const start = local(cell.start), end = cell.end == null ? null : local(cell.end);
                let x0 = start < firstTime ? 0 : scale.timeToCoordinate(start);
                let x1 = end == null ? (right === null ? mediaSize.width : right) : scale.timeToCoordinate(end);
                if (x0 === null || x1 === null || x1 < 0 || x0 > mediaSize.width) continue;
                const yTop = liq.series.priceToCoordinate(cell.price + heat.step);
                const yBottom = liq.series.priceToCoordinate(cell.price);
                if (yTop === null || yBottom === null) continue;
                ctx.fillStyle = heatColor(cell.usd / max, cell.end == null);
                ctx.fillRect(Math.max(0, x0), yTop, Math.max(1, Math.min(mediaSize.width, x1) - Math.max(0, x0)), Math.max(1, yBottom - yTop));
              }
            });
          },
        };
      },
    },
  };
  candles.attachPrimitive(liq);

  // Fibonacci retracement of the newest swing leg (src/dashboard/chart_live.fib_retracement), drawn like
  // TradingView's Fib tool: dashed line from the swing start to its end, coloured zones between the levels
  // from the swing start to the newest candle, level and price on the left. Display only, not a signal.
  const FIB_COLORS = { '0': '#787b86', '0.236': '#f23645', '0.382': '#ff9800', '0.5': '#4caf50', '0.618': '#089981',
                       '0.786': '#00bcd4', '0.886': '#9575cd', '0.941': '#ba68c8', '1': '#787b86', '1.618': '#2962ff' };
  const fibColor = ratio => FIB_COLORS[String(ratio)] || '#c9a227';
  const alpha = (hex, a) => `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})`;
  const fib = {
    chart: null, series: null, requestUpdate: null, visible: false,
    attached(param) { this.chart = param.chart; this.series = param.series; this.requestUpdate = param.requestUpdate; },
    detached() { this.chart = null; this.series = null; },
    updateAllViews() {},
    autoscaleInfo() { return null; },
    paneViews() { return [this.view]; },
    view: {
      zOrder() { return 'bottom'; },
      renderer() {
        return {
          draw(target) {
            const leg = model && model.fib;
            if (!fib.visible || !fib.chart || !leg || !leg.levels || !leg.levels.length) return;
            target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
              const scale = fib.chart.timeScale();
              let x0 = scale.timeToCoordinate(local(leg.start));
              const xEnd = scale.timeToCoordinate(local(leg.end));
              const x1 = scale.logicalToCoordinate(model.candles.length - 1 + 3);
              if (x0 === null) x0 = local(leg.start) < local(model.candles[0].time) ? 0 : null;
              if (x0 === null || x1 === null || x1 < 0 || x0 > mediaSize.width) return;
              const left = Math.max(0, x0), right = Math.min(mediaSize.width, x1);
              const levels = [...leg.levels].sort((a, b) => a.ratio - b.ratio);
              const ys = levels.map(level => fib.series.priceToCoordinate(level.price));
              for (let i = 0; i + 1 < levels.length; i++) {  // zone between two levels in the colour of the outer one
                if (ys[i] === null || ys[i + 1] === null) continue;
                ctx.fillStyle = alpha(fibColor(levels[i + 1].ratio), 0.12);
                ctx.fillRect(left, Math.min(ys[i], ys[i + 1]), right - left, Math.abs(ys[i + 1] - ys[i]));
              }
              ctx.font = '11px ui-monospace, Menlo, monospace';
              ctx.textBaseline = 'middle';
              const inside = x0 < 130;  // no room left of the swing: labels go inside the zones
              ctx.textAlign = inside ? 'left' : 'right';
              levels.forEach((level, i) => {
                const y = ys[i];
                if (y === null) return;
                const color = fibColor(level.ratio);
                ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash([]);
                ctx.beginPath(); ctx.moveTo(left, Math.round(y) + 0.5); ctx.lineTo(right, Math.round(y) + 0.5); ctx.stroke();
                ctx.fillStyle = color;
                const text = `${level.ratio} (${fmt(level.price)})` + (level.ratio === 0 ? ` · Fib ${leg.tf}` : '');
                ctx.fillText(text, inside ? left + 4 : left - 6, inside ? y - 7 : y);
              });
              // the swing itself: from its start (level 1) to its end (level 0)
              const yA = fib.series.priceToCoordinate(leg.start_price), yB = fib.series.priceToCoordinate(leg.end_price);
              if (yA !== null && yB !== null && xEnd !== null) {
                ctx.strokeStyle = 'rgba(195,202,214,0.75)'; ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
                ctx.beginPath(); ctx.moveTo(x0, yA); ctx.lineTo(xEnd, yB); ctx.stroke();
                ctx.setLineDash([]);
              }
              ctx.textAlign = 'left';
            });
          },
        };
      },
    },
  };
  candles.attachPrimitive(fib);

  // Footprint like TradingView's: rows follow the zoom (finer price steps the closer you get).
  // Far out: a short hint. Medium zoom: one heat column per candle (colour = delta, strength = volume).
  // Close: bid × ask numbers per row next to a slim candle, POC framed, 4:1 imbalances coloured,
  // stacked imbalances (3+) as a bar at the side, unfinished auctions dotted, Δ and volume under the candle.
  const FP = { heatWidth: 8, numberWidth: 40, numberRow: 13, heatRow: 3, ratio: 4, stack: 3, merges: [1, 2, 4, 5, 10, 20, 25, 50, 100, 200] };
  const FP_TEXT = EN
    ? { zoom: 'Footprint: zoom in (or the “Footprint” button)', vol: 'V' }
    : { zoom: 'Footprint: hineinzoomen (oder Knopf „Footprint“)', vol: 'V' };
  // Rows of one bar at ``k`` times the sent step: sums per row, imbalances and stacks for that row size.
  function fpRows(bar, step, k) {
    const size = step * k;
    const cells = new Map();
    for (const [price, bid, ask] of bar.levels) {
      const index = Math.floor(price / size + 1e-9);
      const cell = cells.get(index) || { index, price: index * size, bid: 0, ask: 0 };
      cell.bid += bid; cell.ask += ask;
      cells.set(index, cell);
    }
    const rows = [...cells.values()].sort((a, b) => a.index - b.index);
    let poc = rows[0];
    for (const row of rows) {
      if (row.bid + row.ask > poc.bid + poc.ask) poc = row;
    }
    const lowest = rows[0].index, highest = rows[rows.length - 1].index;
    rows.forEach(row => {
      // Same rule as the server and orderflow_scenario.footprint (F1): diagonal, one row away; an empty row
      // in between counts as zero (Prüfung 31.10.2026: before, a gap hid the imbalance here and the server
      // compared with a row two steps away).
      const below = cells.get(row.index - 1) || { bid: 0, ask: 0 }, above = cells.get(row.index + 1) || { bid: 0, ask: 0 };
      row.askImb = row.index > lowest && row.ask > 0 && row.ask >= FP.ratio * below.bid;
      row.bidImb = row.index < highest && row.bid > 0 && row.bid >= FP.ratio * above.ask;
      row.poc = row === poc;
    });
    const stacks = [];
    for (const side of ['ask', 'bid']) {
      let run = [];
      for (const row of rows.concat([null])) {
        const marked = row && (side === 'ask' ? row.askImb : row.bidImb);
        if (marked && (!run.length || run[run.length - 1].index === row.index - 1)) { run.push(row); continue; }
        if (run.length >= FP.stack) stacks.push({ side, low: run[0].price, high: run[run.length - 1].price + size });
        run = marked ? [row] : [];
      }
    }
    return { size, rows, stacks };
  }
  // Two ways to draw the footprint. 'delta' (Uzi 09.11.2026: "die perfekte Footprint-Darstellung"):
  // a slim candle and, per price row, one bar to the right, long = much delta, blue =
  // more market buys, red = more market sells. 'cells': heat columns and bid × ask numbers as before.
  const FP_STYLE = 'tim-chart-fp-style-v1' + PANE;
  let fpStyle = (() => { try { return localStorage.getItem(FP_STYLE) === 'delta' ? 'delta' : 'cells'; } catch (error) { return 'cells'; } })();
  function setFpStyle(style) {
    fpStyle = style === 'delta' ? 'delta' : 'cells';
    try { localStorage.setItem(FP_STYLE, fpStyle); } catch (error) { /* ignore */ }
    if (fp.requestUpdate) fp.requestUpdate();
  }
  function drawDeltaBars(ctx, mediaSize, scale, step, barWidth, perStep) {
    const k = FP.merges.find(m => m * perStep >= 4) || FP.merges[FP.merges.length - 1];
    const half = Math.max(3, Math.min(barWidth * 0.46, 60));
    for (const bar of model.footprint.bars) {
      const x = scale.timeToCoordinate(local(bar.time));
      if (x === null || x < -barWidth || x > mediaSize.width + barWidth) continue;
      const { size, rows } = fpRows(bar, step, k);
      const maxDelta = Math.max(...rows.map(r => Math.abs(r.ask - r.bid)), 1e-12);
      const candle = fp.byTime.get(bar.time);
      const up = candle ? candle.close >= candle.open : bar.delta >= 0;
      const left = x - half, room = 2 * half - 5;
      const yTopAll = fp.series.priceToCoordinate(Math.max(rows[rows.length - 1].price + size, candle ? candle.high : -Infinity));
      const yBottomAll = fp.series.priceToCoordinate(Math.min(rows[0].price, candle ? candle.low : Infinity));
      if (yTopAll === null || yBottomAll === null) continue;
      ctx.fillStyle = 'rgba(11,15,22,1)';  // hides the library's wide candle behind the slim one
      ctx.fillRect(left - 1, yTopAll - 1, 2 * half + 2, yBottomAll - yTopAll + 2);
      if (candle) {
        const yH = fp.series.priceToCoordinate(candle.high), yL = fp.series.priceToCoordinate(candle.low);
        const yO = fp.series.priceToCoordinate(candle.open), yC = fp.series.priceToCoordinate(candle.close);
        if (yH !== null && yL !== null && yO !== null && yC !== null) {
          ctx.fillStyle = up ? '#5b7cfa' : '#f47a6a';
          ctx.fillRect(left + 1, yH, 1, yL - yH);
          ctx.fillRect(left, Math.min(yO, yC), 3, Math.max(1, Math.abs(yC - yO)));
        }
      }
      for (const row of rows) {
        const yTop = fp.series.priceToCoordinate(row.price + size), yBottom = fp.series.priceToCoordinate(row.price);
        if (yTop === null || yBottom === null) continue;
        const delta = row.ask - row.bid;
        const height = Math.max(1, yBottom - yTop - (yBottom - yTop > 3 ? 1 : 0));
        const share = Math.abs(delta) / maxDelta;
        ctx.fillStyle = `rgba(${delta >= 0 ? '91,124,250' : '244,122,106'},${(0.35 + 0.65 * share).toFixed(3)})`;
        ctx.fillRect(left + 5, yTop, Math.max(1, room * share), height);
        if (row.poc && barWidth >= 14) {  // most traded row: dotted line across the bar
          ctx.strokeStyle = 'rgba(195,202,214,0.7)'; ctx.lineWidth = 1; ctx.setLineDash([2, 2]);
          ctx.beginPath(); ctx.moveTo(left + 5, yTop + height / 2); ctx.lineTo(left + 5 + room, yTop + height / 2); ctx.stroke();
          ctx.setLineDash([]);
        }
      }
    }
  }
  const fp = {
    chart: null, series: null, requestUpdate: null, visible: true, byTime: new Map(),
    attached(param) { this.chart = param.chart; this.series = param.series; this.requestUpdate = param.requestUpdate; },
    detached() { this.chart = null; this.series = null; },
    updateAllViews() {},
    autoscaleInfo() { return null; },
    paneViews() { return [this.view]; },
    view: {
      zOrder() { return 'top'; },
      renderer() {
        return {
          draw(target) {
            if (!fp.visible || !fp.chart || !model || !model.footprint || !model.footprint.bars.length) return;
            target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
              const scale = fp.chart.timeScale();
              const step = model.footprint.step;
              const range = scale.getVisibleLogicalRange();
              if (!range || !step) return;
              const barWidth = mediaSize.width / Math.max(1, range.to - range.from);
              ctx.textBaseline = 'middle';
              if (barWidth < FP.heatWidth) {
                ctx.font = '11px ui-sans-serif, system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillStyle = 'rgba(195,202,214,0.75)';
                ctx.fillText(FP_TEXT.zoom, mediaSize.width / 2, 14);
                ctx.textAlign = 'left';
                return;
              }
              const y0 = fp.series.priceToCoordinate(model.last || model.footprint.bars[model.footprint.bars.length - 1].poc);
              const y1 = fp.series.priceToCoordinate((model.last || model.footprint.bars[model.footprint.bars.length - 1].poc) + step);
              if (y0 === null || y1 === null) return;
              const perStep = Math.max(1e-6, Math.abs(y0 - y1));
              if (fpStyle === 'delta') { drawDeltaBars(ctx, mediaSize, scale, step, barWidth, perStep); return; }
              const pick = need => FP.merges.find(k => k * perStep >= need) || FP.merges[FP.merges.length - 1];
              const numbers = barWidth >= FP.numberWidth;
              const k = pick(numbers ? FP.numberRow : FP.heatRow);
              const half = numbers ? Math.min(barWidth / 2 - 2, 70) : Math.max(2, Math.min(barWidth * 0.42, 30));
              const short = v => v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v >= 1 ? v.toFixed(2) : v > 0 ? v.toFixed(3).replace(/^0/, '') : '0';
              for (const bar of model.footprint.bars) {
                const x = scale.timeToCoordinate(local(bar.time));
                if (x === null || x < -barWidth || x > mediaSize.width + barWidth) continue;
                const { size, rows, stacks } = fpRows(bar, step, k);
                const maxVolume = Math.max(...rows.map(r => r.bid + r.ask), 1e-12);
                const maxDelta = Math.max(...rows.map(r => Math.abs(r.ask - r.bid)), 1e-12);
                const candle = fp.byTime.get(bar.time);
                const left = numbers ? x - half + 6 : x - half;  // numbers: a slim candle sits in the first 5 px
                const width = x + half - left;
                const mid = left + width / 2;
                const fontSize = Math.max(8, Math.min(11, Math.floor(k * perStep) - 3));
                ctx.font = `${fontSize}px ui-monospace, Menlo, monospace`;
                let bottomY = -Infinity, topY = Infinity;
                if (numbers) {  // one dark backdrop over the whole bar, so the candle body never shows through empty rows
                  const yAllTop = fp.series.priceToCoordinate(rows[rows.length - 1].price + size), yAllBottom = fp.series.priceToCoordinate(rows[0].price);
                  if (yAllTop !== null && yAllBottom !== null) { ctx.fillStyle = 'rgba(11,15,22,0.96)'; ctx.fillRect(left - 1, yAllTop, width + 2, yAllBottom - yAllTop); }
                }
                for (const row of rows) {
                  const yTop = fp.series.priceToCoordinate(row.price + size);
                  const yBottom = fp.series.priceToCoordinate(row.price);
                  if (yTop === null || yBottom === null) continue;
                  const height = Math.max(1, yBottom - yTop);
                  bottomY = Math.max(bottomY, yBottom); topY = Math.min(topY, yTop);
                  const delta = row.ask - row.bid;
                  const shade = delta >= 0 ? '38,166,154' : '239,83,80';
                  if (numbers) {
                    ctx.fillStyle = 'rgba(11,15,22,0.94)';
                    ctx.fillRect(left, yTop, width, height - 1);
                    ctx.fillStyle = `rgba(${shade},${(0.10 + 0.45 * Math.abs(delta) / maxDelta).toFixed(3)})`;
                    ctx.fillRect(left, yTop, width, height - 1);
                    ctx.fillStyle = 'rgba(120,134,156,0.35)';
                    ctx.fillRect(mid, yTop, 1, height - 1);
                    ctx.textAlign = 'right';
                    ctx.font = `${row.bidImb ? 'bold ' : ''}${fontSize}px ui-monospace, Menlo, monospace`;
                    ctx.fillStyle = row.bidImb ? '#ff6b6b' : 'rgba(235,190,190,0.95)';
                    ctx.fillText(short(row.bid), mid - 3, yTop + height / 2, width / 2 - 4);
                    ctx.textAlign = 'left';
                    ctx.font = `${row.askImb ? 'bold ' : ''}${fontSize}px ui-monospace, Menlo, monospace`;
                    ctx.fillStyle = row.askImb ? '#3ee6c4' : 'rgba(185,235,220,0.95)';
                    ctx.fillText(short(row.ask), mid + 4, yTop + height / 2, width / 2 - 4);
                  } else {
                    ctx.fillStyle = `rgba(${shade},${(0.18 + 0.72 * (row.bid + row.ask) / maxVolume).toFixed(3)})`;
                    ctx.fillRect(left, yTop, width, Math.max(1, height - (height > 4 ? 1 : 0)));
                  }
                  if (row.poc) {
                    ctx.strokeStyle = '#f5c542'; ctx.lineWidth = 1;
                    ctx.strokeRect(left + 0.5, yTop + 0.5, width - 1, Math.max(1, height - 2));
                  }
                }
                if (topY === Infinity) continue;
                for (const s of stacks) {  // stacked imbalances: bar at the side the aggressor pushed from
                  const yHigh = fp.series.priceToCoordinate(s.high), yLow = fp.series.priceToCoordinate(s.low);
                  if (yHigh === null || yLow === null) continue;
                  ctx.fillStyle = s.side === 'ask' ? '#3ee6c4' : '#ff6b6b';
                  ctx.fillRect(s.side === 'ask' ? x + half + 1 : left - 3, yHigh, 2, yLow - yHigh);
                }
                ctx.strokeStyle = '#ffa726'; ctx.lineWidth = 1; ctx.setLineDash([2, 2]);
                if (bar.unfinished_high) { ctx.beginPath(); ctx.moveTo(left, topY - 1.5); ctx.lineTo(left + width, topY - 1.5); ctx.stroke(); }
                if (bar.unfinished_low) { ctx.beginPath(); ctx.moveTo(left, bottomY + 1.5); ctx.lineTo(left + width, bottomY + 1.5); ctx.stroke(); }
                ctx.setLineDash([]);
                if (numbers && candle) {  // slim candle left of the cells
                  const yH = fp.series.priceToCoordinate(candle.high), yL = fp.series.priceToCoordinate(candle.low);
                  const yO = fp.series.priceToCoordinate(candle.open), yC = fp.series.priceToCoordinate(candle.close);
                  if (yH !== null && yL !== null && yO !== null && yC !== null) {
                    ctx.fillStyle = candle.close >= candle.open ? '#26a69a' : '#ef5350';
                    ctx.fillRect(x - half + 1.5, yH, 1, yL - yH);
                    ctx.fillRect(x - half, Math.min(yO, yC), 4, Math.max(1, Math.abs(yC - yO)));
                  }
                }
                if (barWidth >= 26) {  // Δ and volume under the candle
                  ctx.font = `${barWidth >= 60 ? 10 : 9}px ui-monospace, Menlo, monospace`;
                  ctx.textAlign = 'center';
                  ctx.fillStyle = bar.delta >= 0 ? 'rgba(38,166,154,1)' : 'rgba(239,83,80,1)';
                  ctx.fillText(`Δ ${bar.delta >= 0 ? '+' : '-'}${short(Math.abs(bar.delta))}`, x, bottomY + 9, 2 * half + 4);
                  if (numbers) {
                    ctx.fillStyle = 'rgba(195,202,214,0.85)';
                    ctx.fillText(`${FP_TEXT.vol} ${short(bar.total)}`, x, bottomY + 20, 2 * half + 4);
                  }
                }
              }
              ctx.textAlign = 'left';
            });
          },
        };
      },
    },
  };
  candles.attachPrimitive(fp);

  // Volume bubbles: large market orders from TIM's trades (one taker order = aggTrades of the same
  // millisecond and side). Circle at the order's time inside its candle and its average price; area
  // follows the order size against the largest in view; green = aggressive buyer, red = aggressive seller.
  // Absorbed (Uzi 09.11.2026: the bubbles were too large and did not show absorption): the candle closed
  // against the order (a big buy, close below its price; a big sell, close above). Those get a white ring,
  // the others stay faint. Only finished candles are judged; it is a reading of the candle, not a proof.
  const BUBBLE = { minR: 2, maxR: 11, labelR: 9, pxPer: 14, minCount: 20 };
  const absorbed = item => {
    const candle = fp.byTime.get(item.bar);
    if (!candle || !model || candle.time === model.candles[model.candles.length - 1].time) return false;
    return item.side > 0 ? candle.close < item.price : candle.close > item.price;
  };
  const bubbles = {
    chart: null, series: null, requestUpdate: null, visible: true,
    attached(param) { this.chart = param.chart; this.series = param.series; this.requestUpdate = param.requestUpdate; },
    detached() { this.chart = null; this.series = null; },
    updateAllViews() {},
    autoscaleInfo() { return null; },
    paneViews() { return [this.view]; },
    view: {
      zOrder() { return 'top'; },
      renderer() {
        return {
          draw(target) {
            const data = model && model.bubbles;
            if (!bubbles.visible || !bubbles.chart || !data || !data.items || !data.items.length || model.candles.length < 2) return;
            target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
              const scale = bubbles.chart.timeScale();
              const range = scale.getVisibleLogicalRange();
              if (!range) return;
              const barWidth = mediaSize.width / Math.max(1, range.to - range.from);
              const n = model.candles.length;
              const seconds = Math.max(1, model.candles[n - 1].time - model.candles[n - 2].time);
              // Only the largest orders in view (about one per 14 px of width), sized against the largest of them:
              // zoomed out the big ones stand out, zoomed in the smaller ones appear.
              const placed = [];
              for (const item of data.items) {
                const center = scale.timeToCoordinate(local(item.bar));
                const y = bubbles.series.priceToCoordinate(item.price);
                if (center === null || y === null) continue;
                const x = center + ((item.time - item.bar) / seconds - 0.5) * barWidth;
                if (x < -BUBBLE.maxR || x > mediaSize.width + BUBBLE.maxR) continue;
                placed.push({ item, x, y });
              }
              placed.sort((a, b) => b.item.usd - a.item.usd);  // biggest first, small ones drawn on top stay visible
              const order = placed.slice(0, Math.max(BUBBLE.minCount, Math.round(mediaSize.width / BUBBLE.pxPer)));
              if (!order.length) return;
              const max = Math.max(1, order[0].item.usd);
              ctx.textAlign = 'center';
              ctx.textBaseline = 'middle';
              ctx.font = '10px ui-sans-serif, system-ui, sans-serif';
              for (const { item, x, y } of order) {
                const r = Math.max(BUBBLE.minR, BUBBLE.maxR * Math.sqrt(item.usd / max));
                const buy = item.side > 0;
                ctx.beginPath();
                ctx.arc(x, y, r, 0, Math.PI * 2);
                const bybit = item.venue === 'bybit';  // second venue (issue #162): hollow, dashed ring
                const held = absorbed(item);
                ctx.fillStyle = bybit ? 'rgba(11,15,22,0.35)' : buy ? `rgba(38,200,140,${held ? 0.55 : 0.18})` : `rgba(239,83,80,${held ? 0.55 : 0.18})`;
                ctx.fill();
                ctx.lineWidth = 1;
                ctx.setLineDash(bybit ? [3, 2] : []);
                ctx.strokeStyle = buy ? `rgba(38,220,150,${held ? 0.95 : 0.55})` : `rgba(255,92,88,${held ? 0.95 : 0.55})`;
                ctx.stroke();
                ctx.setLineDash([]);
                if (held) {  // white ring: the market took this order and closed against it
                  ctx.beginPath(); ctx.arc(x, y, r + 2, 0, Math.PI * 2);
                  ctx.lineWidth = 1.5; ctx.strokeStyle = 'rgba(232,236,243,0.95)'; ctx.stroke();
                }
                if (r >= BUBBLE.labelR) {
                  ctx.fillStyle = '#e8edf5';
                  ctx.fillText(item.quantity >= 100 ? item.quantity.toFixed(0) : item.quantity.toFixed(1), x, y);
                }
              }
              ctx.textAlign = 'left';
            });
          },
        };
      },
    },
  };
  candles.attachPrimitive(bubbles);

  // Real liquidations (issue #162): Binance forceOrder and Bybit allLiquidation from TIM's S12 record.
  // A triangle at the event's time and price: pointing down and red when a long was liquidated (forced
  // sell), up and green for a short (forced buy); Bybit events get a hollow shape. Size by USD against
  // the largest in view, label from 500 k$. Only the largest events of the window are sent (300).
  const LIQEV = { minR: 3, maxR: 14, labelUsd: 500000, pxPer: 10, minCount: 40 };
  const liqev = {
    chart: null, series: null, requestUpdate: null, visible: true,
    attached(param) { this.chart = param.chart; this.series = param.series; this.requestUpdate = param.requestUpdate; },
    detached() { this.chart = null; this.series = null; },
    updateAllViews() {},
    autoscaleInfo() { return null; },
    paneViews() { return [this.view]; },
    view: {
      zOrder() { return 'top'; },
      renderer() {
        return {
          draw(target) {
            const data = model && model.liquidations;
            if (!liqev.visible || !liqev.chart || !data || !data.items || !data.items.length || model.candles.length < 2) return;
            target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
              const scale = liqev.chart.timeScale();
              const range = scale.getVisibleLogicalRange();
              if (!range) return;
              const barWidth = mediaSize.width / Math.max(1, range.to - range.from);
              const n = model.candles.length;
              const seconds = Math.max(1, model.candles[n - 1].time - model.candles[n - 2].time);
              const first = model.candles[0].time;
              const placed = [];
              for (const item of data.items) {
                const bar = first + Math.floor((item.time - first) / seconds) * seconds;
                const center = scale.timeToCoordinate(local(bar));
                const y = liqev.series.priceToCoordinate(item.price);
                if (center === null || y === null) continue;
                const x = center + ((item.time - bar) / seconds - 0.5) * barWidth;
                if (x < -LIQEV.maxR || x > mediaSize.width + LIQEV.maxR) continue;
                placed.push({ item, x, y });
              }
              placed.sort((a, b) => b.item.usd - a.item.usd);
              const order = placed.slice(0, Math.max(LIQEV.minCount, Math.round(mediaSize.width / LIQEV.pxPer)));
              if (!order.length) return;
              const max = Math.max(1, order[0].item.usd);
              ctx.textAlign = 'center';
              ctx.textBaseline = 'bottom';
              ctx.font = '10px ui-sans-serif, system-ui, sans-serif';
              ctx.lineWidth = 1.4;
              for (const { item, x, y } of order) {
                const r = Math.max(LIQEV.minR, LIQEV.maxR * Math.sqrt(item.usd / max));
                const long = item.side === 'long';  // long liquidated = forced sell, drawn pointing down
                const dir = long ? 1 : -1;
                ctx.beginPath();
                ctx.moveTo(x, y + dir * r);
                ctx.lineTo(x - r * 0.9, y - dir * r * 0.7);
                ctx.lineTo(x + r * 0.9, y - dir * r * 0.7);
                ctx.closePath();
                ctx.strokeStyle = long ? 'rgba(255,92,88,0.95)' : 'rgba(38,220,150,0.95)';
                ctx.fillStyle = item.venue === 'bybit' ? 'rgba(11,15,22,0.65)' : (long ? 'rgba(239,83,80,0.55)' : 'rgba(38,200,140,0.55)');
                ctx.fill();
                ctx.stroke();
                if (item.usd >= LIQEV.labelUsd) {
                  ctx.fillStyle = '#e8edf5';
                  const usd = item.usd >= 1e6 ? `${(item.usd / 1e6).toFixed(1)}M` : `${Math.round(item.usd / 1e3)}k`;
                  ctx.fillText(usd, x, y - dir * r - 2 * dir - (dir > 0 ? 0 : -12));
                }
              }
              ctx.textAlign = 'left';
              ctx.textBaseline = 'middle';
            });
          },
        };
      },
    },
  };
  candles.attachPrimitive(liqev);

  // TIM's trades as position boxes, like TradingView's long/short tool (Uzi 30.10.2026): green zone from
  // the entry to the last target, red zone from the entry to the original stop, entry line between them,
  // the other targets as thin lines inside the green zone. Labels on a running or waiting trade: target with
  // distance in %, open P&L at the current price and the reward/risk ratio, stop with distance in %.
  // Closed trades keep a faint box without text (their result sits at the exit dot). The stop TIM moved
  // stays the orange step line drawn above the box, unchanged.
  const PT = EN
    ? { target: 'Target', stop: 'Stop', open: 'Open P&L', rr: 'Reward/Risk', wait: 'Waiting for entry' }
    : { target: 'Ziel', stop: 'Stop', open: 'Offener G&V', rr: 'Chance/Risiko', wait: 'Wartet auf Einstieg' };
  const num = (v, digits) => EN ? v.toFixed(digits) : v.toFixed(digits).replace('.', ',');
  const signed = (v, digits) => (v > 0 ? '+' : v < 0 ? '−' : '') + num(Math.abs(v), digits);
  function positionGeometry(plan) {
    const targets = plan.targets || [];
    if (!targets.length || plan.entry == null || plan.stop == null) return null;
    const long = plan.direction === 'LONG';
    const target = long ? Math.max(...targets) : Math.min(...targets);
    const risk = Math.abs(plan.entry - plan.stop);
    const reward = Math.abs(target - plan.entry);
    return { long, target, rr: risk > 0 ? reward / risk : null,
             targetPct: (target - plan.entry) / plan.entry * 100, stopPct: (plan.stop - plan.entry) / plan.entry * 100 };
  }
  function openResult(plan, price) {
    const long = plan.direction === 'LONG';
    const move = long ? price - plan.entry : plan.entry - price;
    const risk = Math.abs(plan.entry - plan.stop);
    return { pct: move / plan.entry * 100, r: risk > 0 ? move / risk : null };
  }
  // One label box; `placed` holds the boxes already drawn this frame, a label that would cover one moves
  // down (or up at the bottom edge) until it is free, so two trades close together stay readable.
  function label(ctx, text, x, y, fill, size, placed) {
    ctx.font = '11px ui-sans-serif, system-ui, sans-serif';
    const lines = String(text).split('\n');
    const width = Math.max(...lines.map(line => ctx.measureText(line).width)) + 10;
    const height = 15 * lines.length + 3;
    const left = Math.max(2, Math.min(x, size.width - width - 2));
    const hits = top => placed.some(b => left < b.x + b.w && b.x < left + width && top < b.y + b.h && b.y < top + height);
    for (let step = 0, start = y; step < 8 && hits(y); step++) {
      const blocker = placed.find(b => left < b.x + b.w && b.x < left + width && y < b.y + b.h && b.y < y + height);
      y = start > size.height / 2 ? blocker.y - height - 2 : blocker.y + blocker.h + 2;
    }
    placed.push({ x: left, y, w: width, h: height });
    ctx.fillStyle = fill;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(left, y, width, height, 3); else ctx.rect(left, y, width, height);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.textBaseline = 'top';
    lines.forEach((line, i) => ctx.fillText(line, left + 5, y + 3 + 15 * i));
    return height;
  }
  const positions = {
    chart: null, series: null, requestUpdate: null, groups: new Set(),
    attached(param) { this.chart = param.chart; this.series = param.series; this.requestUpdate = param.requestUpdate; },
    detached() { this.chart = null; this.series = null; },
    updateAllViews() {},
    autoscaleInfo() { return null; },
    paneViews() { return [this.boxView, this.labelView]; },
    // Box corners in pixels for every plan in view (null: hidden or outside).
    place(plan, mediaSize) {
      if (!this.groups.has(plan.group)) return null;
      const g = positionGeometry(plan);
      if (!g) return null;
      const scale = this.chart.timeScale();
      let x1 = scale.timeToCoordinate(local(plan.t1));
      let x2 = scale.timeToCoordinate(local(plan.t2));
      if (x1 === null || x2 === null) return null;
      if (plan.status !== 'CLOSED') {
        // A trade that still runs or waits reaches a few bars into the free space on the right, as on TradingView.
        const range = scale.getVisibleLogicalRange();
        const bar = range ? mediaSize.width / Math.max(1, range.to - range.from) : 6;
        x2 += 6 * bar;
      }
      x2 = Math.max(x2, x1 + 4);
      if (x2 < 0 || x1 > mediaSize.width) return null;
      const y = price => this.series.priceToCoordinate(price);
      const yEntry = y(plan.entry), yTarget = y(g.target), yStop = y(plan.stop);
      if (yEntry === null || yTarget === null || yStop === null) return null;
      return { g, x1, x2, yEntry, yTarget, yStop, y };
    },
    boxView: {
      zOrder() { return 'bottom'; },
      renderer() {
        return {
          draw(target) {
            if (!positions.chart || !model || !model.plans || !model.plans.length) return;
            target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
              for (const plan of model.plans) {
                const p = positions.place(plan, mediaSize);
                if (!p) continue;
                const closed = plan.status === 'CLOSED';
                const waiting = plan.status === 'OPEN';
                const alpha = closed ? 0.10 : waiting ? 0.12 : 0.22;
                const width = p.x2 - p.x1;
                ctx.fillStyle = `rgba(38,166,154,${alpha})`;
                ctx.fillRect(p.x1, Math.min(p.yEntry, p.yTarget), width, Math.abs(p.yTarget - p.yEntry));
                ctx.fillStyle = `rgba(239,83,80,${alpha})`;
                ctx.fillRect(p.x1, Math.min(p.yEntry, p.yStop), width, Math.abs(p.yStop - p.yEntry));
                ctx.lineWidth = 1;
                ctx.setLineDash(waiting ? [4, 3] : []);
                ctx.strokeStyle = `rgba(38,166,154,${closed ? 0.35 : 0.8})`;
                ctx.strokeRect(p.x1 + 0.5, Math.min(p.yEntry, p.yTarget) + 0.5, width - 1, Math.abs(p.yTarget - p.yEntry));
                ctx.strokeStyle = `rgba(239,83,80,${closed ? 0.35 : 0.8})`;
                ctx.strokeRect(p.x1 + 0.5, Math.min(p.yEntry, p.yStop) + 0.5, width - 1, Math.abs(p.yStop - p.yEntry));
                // Targets before the last one: thin dotted lines inside the green zone.
                ctx.setLineDash([2, 3]);
                ctx.strokeStyle = `rgba(53,211,154,${closed ? 0.35 : 0.75})`;
                for (const value of plan.targets || []) {
                  if (value === p.g.target) continue;
                  const yt = p.y(value);
                  if (yt === null) continue;
                  ctx.beginPath(); ctx.moveTo(p.x1, Math.round(yt) + 0.5); ctx.lineTo(p.x2, Math.round(yt) + 0.5); ctx.stroke();
                }
                // Entry line: grey across the box (the blue line series with the axis label lies on top while it runs).
                ctx.setLineDash(waiting ? [4, 3] : []);
                ctx.strokeStyle = closed ? 'rgba(195,202,214,0.45)' : 'rgba(195,202,214,0.9)';
                ctx.lineWidth = closed ? 1 : 1.5;
                ctx.beginPath(); ctx.moveTo(p.x1, Math.round(p.yEntry) + 0.5); ctx.lineTo(p.x2, Math.round(p.yEntry) + 0.5); ctx.stroke();
                ctx.setLineDash([]);
              }
            });
          },
        };
      },
    },
    labelView: {
      zOrder() { return 'top'; },
      renderer() {
        return {
          draw(target) {
            if (!positions.chart || !model || !model.plans || !model.plans.length) return;
            target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
              const placed = [];
              // Newest trade first: its labels get the free spots.
              for (const plan of [...model.plans].reverse()) {
                if (plan.status === 'CLOSED') continue;
                const p = positions.place(plan, mediaSize);
                if (!p || p.x2 - Math.max(0, p.x1) < 40) continue;
                const g = p.g;
                const x = Math.max(0, p.x1);
                const name = `${plan.label} · ${g.long ? 'Long' : 'Short'}`;
                const top = Math.min(p.yTarget, p.yStop), bottom = Math.max(p.yTarget, p.yStop);
                const targetText = `${name} · ${PT.target}: ${fmt(g.target)} (${signed(g.targetPct, 2)} %)`;
                const stopText = `${PT.stop}: ${fmt(plan.stop)} (${signed(g.stopPct, 2)} %)`;
                const green = 'rgba(16,128,110,0.95)', red = 'rgba(190,52,58,0.95)';
                const [aboveText, aboveFill, belowText, belowFill] = g.long
                  ? [targetText, green, stopText, red] : [stopText, red, targetText, green];
                label(ctx, aboveText, x, Math.max(2, top - 20), aboveFill, mediaSize, placed);
                label(ctx, belowText, x, Math.min(mediaSize.height - 20, bottom + 3), belowFill, mediaSize, placed);
                const rr = g.rr == null ? '–' : num(g.rr, 2);
                let middle;
                if (plan.status === 'OPEN') middle = `${PT.wait} · ${PT.rr}: ${rr}`;
                else {
                  const res = openResult(plan, model.last);
                  middle = `${PT.open}: ${signed(res.pct, 2)} %${res.r == null ? '' : ` (${signed(res.r, 2)} R)`}\n${PT.rr}: ${rr}`;
                }
                // Below the entry line on a long, above it on a short: inside the red zone, as on TradingView.
                const h = middle.includes('\n') ? 33 : 18;
                const yMid = g.long ? p.yEntry + 4 : p.yEntry - h - 4;
                const res = plan.status === 'FILLED' ? openResult(plan, model.last) : null;
                label(ctx, middle, x + 4, yMid, res && res.pct < 0 ? 'rgba(150,40,48,0.95)' : res ? 'rgba(16,128,110,0.95)' : 'rgba(70,80,98,0.95)', mediaSize, placed);
              }
            });
          },
        };
      },
    },
  };
  candles.attachPrimitive(positions);

  // Layers added after a visitor saved a choice (e.g. TIM's plans, footprint) start visible: only keys the
  // visitor has seen before can be hidden by a saved choice. Saves from before this list existed knew
  // neither the plans nor volume profile and footprint.
  const KNOWN = 'tim-chart-layers-known-v1' + PANE;
  const LEGACY_NEW = ['vp', 'fp'];
  function shownGroups() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || 'null');
      if (Array.isArray(saved)) {
        const known = new Set(JSON.parse(localStorage.getItem(KNOWN) || '[]'));
        const groups = new Set(saved);
        for (const key of (model ? model.default_groups : [])) if (!known.has(key) && known.size) groups.add(key);
        // VWAP became a default layer together with its bands (Beirat 29.10.2026): switch the line on with them once.
        if (known.size && !known.has('vwap_bands') && groups.has('vwap_bands')) groups.add('vwap');
        if (!known.size) for (const key of (model ? model.default_groups : [])) if (key.startsWith('plans_') || LEGACY_NEW.includes(key)) groups.add(key);
        return groups;
      }
    } catch (error) { /* private window: defaults */ }
    return new Set(model ? model.default_groups : []);
  }
  function saveGroups(groups) {
    try {
      localStorage.setItem(STORE, JSON.stringify([...groups]));
      if (model) localStorage.setItem(KNOWN, JSON.stringify(Object.keys(model.groups)));
    } catch (error) { /* ignore */ }
  }

  // Layouts (Uzi 09.11.2026: indicators only sorted in named layouts, like a workspace). A layout names the
  // layers and, if it wants, coin, timeframe and spot/perp. TIM's layouts ship with the page; own layouts
  // live in this browser only (localStorage), like the ticks before.
  const LAYOUT_STORE = 'tim-chart-layouts-v1';
  const LAYOUT_ACTIVE = 'tim-chart-layout-active-v1' + PANE;
  const layoutBox = document.getElementById('tc-live-layouts' + PANE);
  const L = EN
    ? { label: 'Layout', tim: 'TIM layouts (each with levels and structure)', own: 'My layouts', changed: 'changed, not saved', save: 'Save as…', rename: 'Rename', remove: 'Delete',
        ask: 'Name of the layout:', taken: 'This name belongs to a TIM layout.', confirm: name => `Delete layout "${name}"?`,
        fpDelta: 'Footprint: delta bars', fpCells: 'Footprint: bid × ask', other: 'Other', footprint: 'Footprint', tpo: 'TPO', vp: 'Volume profile',
        standard: 'TIM standard', pro: 'Orderflow Pro (BTC 15m perp)', orderflow: 'Orderflow', profile: 'Profiles (VP, TPO)', levels: 'Levels',
        vwap: 'VWAP', structure: 'Structure', positioning: 'Positioning', macro: 'Macro', trades: "TIM's trades" }
    : { label: 'Layout', tim: 'TIM-Layouts (immer mit Level und Struktur)', own: 'Eigene Layouts', changed: 'geändert, nicht gespeichert', save: 'Speichern unter…', rename: 'Umbenennen', remove: 'Löschen',
        ask: 'Name des Layouts:', taken: 'Dieser Name gehört zu einem TIM-Layout.', confirm: name => `Layout "${name}" löschen?`,
        fpDelta: 'Footprint: Delta-Balken', fpCells: 'Footprint: Bid × Ask', other: 'Sonstiges', footprint: 'Footprint', tpo: 'TPO', vp: 'Volume Profile',
        standard: 'TIM Standard', pro: 'Orderflow Pro (BTC 15m Perp)', orderflow: 'Orderflow', profile: 'Profile (VP, TPO)', levels: 'Level',
        vwap: 'VWAP', structure: 'Struktur', positioning: 'Positionierung', macro: 'Makro', trades: 'TIMs Trades' };
  // Every layer belongs to exactly one category (Uzi 09.11.2026: each layout a category); a category is a
  // layout of its own, and the ticks under "edit layout" are sorted the same way.
  const CATEGORIES = [
    { name: L.orderflow, groups: ['fp', 'bubbles', 'delta', 'cvd'] },
    { name: L.profile, groups: ['vp', 'tpo', 'naked', 'running'] },
    { name: L.levels, groups: ['day', 'week', 'month', 'quarter', 'year', 'session', 'ib'] },
    { name: L.vwap, groups: ['vwap', 'vwap_bands'] },
    { name: L.structure, groups: ['structure', 'trend', 'fib'] },
    { name: L.positioning, groups: ['oi', 'funding', 'premium', 'liq', 'liqev', 'gamma'] },
    { name: L.macro, groups: ['dominance', 'macro'] },
    { name: L.trades, groups: ['plans_short', 'plans_mid', 'plans_long', 'plans_old'] },
  ];
  // The layouts are working views (Uzi 09.11.2026: one click for everything orderflow, TPO, footprint or
  // volume profile needs, and the levels and the structure in every one of them): BASE joins each layout.
  // groups: null = the server's default layers.
  const BASE = ['day', 'week', 'month', 'naked', 'structure', 'trend'];
  const TIM_LAYOUTS = [
    { id: 'tim:orderflow', name: L.orderflow, market: 'perp', groups: ['fp', 'bubbles', 'cvd', 'oi', 'liqev', 'vwap'] },
    { id: 'tim:footprint', name: L.footprint, market: 'perp', fp: 'delta', groups: ['fp', 'bubbles', 'delta', 'oi'] },
    { id: 'tim:tpo', name: L.tpo, groups: ['tpo', 'running', 'session', 'ib'] },
    { id: 'tim:vp', name: L.vp, groups: ['vp', 'running', 'vwap', 'vwap_bands'] },
    { id: 'tim:positioning', name: L.positioning, groups: ['oi', 'funding', 'premium', 'liq', 'liqev', 'gamma'] },
    { id: 'tim:macro', name: L.macro, groups: ['dominance', 'macro', 'quarter', 'year'] },
    { id: 'tim:trades', name: L.trades, groups: ['plans_short', 'plans_mid', 'plans_long'] },
    { id: 'tim:pro', name: L.pro, symbol: 'BTCUSDT', tf: '15m', market: 'perp', groups: ['fp', 'bubbles', 'vp', 'cvd', 'oi'] },
    { id: 'tim:standard', name: L.standard, groups: null },
  ];
  function ownLayouts() {
    try {
      const saved = JSON.parse(localStorage.getItem(LAYOUT_STORE) || '[]');
      return Array.isArray(saved) ? saved.filter(item => item && typeof item.name === 'string' && Array.isArray(item.groups)) : [];
    } catch (error) { return []; }
  }
  function storeOwn(list) { try { localStorage.setItem(LAYOUT_STORE, JSON.stringify(list)); } catch (error) { /* ignore */ } }
  // Nothing stored yet: a first visit shows the standard layout, a visitor with ticks from before the layouts has "changed".
  function activeLayout() {
    try {
      const id = localStorage.getItem(LAYOUT_ACTIVE);
      if (id === null) return localStorage.getItem(STORE) === null ? 'tim:standard' : '';
      return id === '-' ? '' : id;
    } catch (error) { return 'tim:standard'; }
  }
  function setActiveLayout(id) { try { localStorage.setItem(LAYOUT_ACTIVE, id || '-'); } catch (error) { /* ignore */ } }
  function findLayout(id) {
    if (id.startsWith('own:')) { const own = ownLayouts().find(item => item.name === id.slice(4)); return own ? { ...own, id } : null; }
    return TIM_LAYOUTS.find(item => item.id === id) || null;
  }
  function buildLayouts() {
    if (!layoutBox) return;
    const active = activeLayout();
    layoutBox.textContent = '';
    const caption = document.createElement('label');
    caption.textContent = L.label + ' ';
    const select = document.createElement('select');
    select.id = 'tc-live-layout' + PANE;
    const add = (parent, value, text) => {
      const option = document.createElement('option');
      option.value = value; option.textContent = text; option.selected = value === active;
      parent.append(option);
    };
    if (!findLayout(active)) add(select, '', '– ' + L.changed + ' –');
    const tim = document.createElement('optgroup'); tim.label = L.tim;
    for (const item of TIM_LAYOUTS) add(tim, item.id, item.name);
    select.append(tim);
    const own = ownLayouts();
    if (own.length) {
      const mine = document.createElement('optgroup'); mine.label = L.own;
      for (const item of own) add(mine, 'own:' + item.name, item.name);
      select.append(mine);
    }
    select.addEventListener('change', () => { if (select.value) applyLayout(select.value); });
    caption.append(select);
    layoutBox.append(caption);
    const button = (text, handler, enabled = true) => {
      const node = document.createElement('button');
      node.type = 'button'; node.className = 'tc-tab'; node.textContent = text; node.disabled = !enabled;
      node.addEventListener('click', handler);
      layoutBox.append(node);
    };
    button(fpStyle === 'delta' ? L.fpDelta : L.fpCells, () => { setFpStyle(fpStyle === 'delta' ? 'cells' : 'delta'); layoutChanged(); buildLayouts(); });
    button(L.save, saveLayoutAs);
    button(L.rename, renameLayout, active.startsWith('own:'));
    button(L.remove, removeLayout, active.startsWith('own:'));
  }
  // A changed tick leaves the named layout: the menu then says so until the view is saved under a name.
  function layoutChanged() { if (activeLayout()) { setActiveLayout(''); buildLayouts(); } }
  function applyLayout(id) {
    const layout = findLayout(id);
    if (!layout || !model) return;
    const all = new Set(Object.keys(model.groups));
    const wanted = layout.id.startsWith('own:') ? layout.groups : layout.groups ? BASE.concat(layout.groups) : model.default_groups;
    const groups = new Set(wanted.filter(key => all.has(key)));
    saveGroups(groups);
    setActiveLayout(id);
    if (layout.fp || !layout.id.startsWith('own:')) setFpStyle(layout.fp || 'cells');
    const nextMarket = layout.market && layout.market !== market ? layout.market : null;
    if (nextMarket) { market = nextMarket; try { localStorage.setItem(MARKET_STORE, market); } catch (error) { /* ignore */ } }
    let reload = !!nextMarket;
    if (layout.symbol && layout.symbol !== symbol) {
      if (!PANE) {  // first pane: another coin is another page (the coin tabs are links)
        const url = new URL(location.href);
        url.searchParams.set('symbol', layout.symbol);
        url.searchParams.set('tf', layout.tf || timeframe);
        location.href = url.toString();
        return;
      }
      symbol = layout.symbol; markTabs(); rememberPane(); reload = true;  // second pane: the coin changes in place
    }
    layers.querySelectorAll('input').forEach(node => { node.checked = groups.has(node.value); });
    applyVisibility(groups);
    buildLayouts();
    const tab = layout.tf && layout.tf !== timeframe ? root.querySelector(`a[data-tf='${layout.tf}']`) : null;
    if (tab) tab.click(); else if (reload) { showMarket(); load(); }
  }
  function askName(preset) {
    const name = (window.prompt(L.ask, preset || '') || '').trim().slice(0, 40);
    if (!name) return '';
    if (TIM_LAYOUTS.some(item => item.name === name)) { window.alert(L.taken); return ''; }
    return name;
  }
  function saveLayoutAs() {
    const active = activeLayout();
    const name = askName(active.startsWith('own:') ? active.slice(4) : '');
    if (!name) return;
    const layout = { name, symbol, tf: timeframe, market, fp: fpStyle, groups: [...shownGroups()] };
    storeOwn(ownLayouts().filter(item => item.name !== name).concat([layout]));
    setActiveLayout('own:' + name);
    buildLayouts();
  }
  function renameLayout() {
    const old = activeLayout().slice(4);
    const name = askName(old);
    if (!name || name === old) return;
    storeOwn(ownLayouts().filter(item => item.name !== name).map(item => (item.name === old ? { ...item, name } : item)));
    setActiveLayout('own:' + name);
    buildLayouts();
  }
  function removeLayout() {
    const name = activeLayout().slice(4);
    if (!window.confirm(L.confirm(name))) return;
    storeOwn(ownLayouts().filter(item => item.name !== name));
    setActiveLayout('');
    buildLayouts();
  }

  function buildLayers() {
    if (!model || layers.dataset.built) return;
    const groups = shownGroups();
    const tick = (parent, key) => {
      const label = document.createElement('label');
      label.className = 'tc-layer tc-layer--' + key;
      const input = document.createElement('input');
      input.type = 'checkbox'; input.value = key; input.checked = groups.has(key);
      input.addEventListener('change', () => {
        const now = new Set([...layers.querySelectorAll('input:checked')].map(node => node.value));
        saveGroups(now); applyVisibility(now); layoutChanged();
      });
      label.append(input, document.createTextNode(' ' + model.groups[key]));
      parent.append(label);
    };
    // One row per category; a layer no category names yet (new on the server) lands under "other".
    const sorted = new Set(CATEGORIES.flatMap(item => item.groups));
    const rest = Object.keys(model.groups).filter(key => !sorted.has(key));
    for (const item of CATEGORIES.concat(rest.length ? [{ name: L.other, groups: rest }] : [])) {
      const keys = item.groups.filter(key => key in model.groups);
      if (!keys.length) continue;
      const row = document.createElement('div'); row.className = 'tc-layercat';
      const title = document.createElement('span'); title.className = 'tc-layercat__name'; title.textContent = item.name;
      row.append(title);
      for (const key of keys) tick(row, key);
      layers.append(row);
    }
    layers.dataset.built = '1';
    buildLayouts();
  }

  // TIM's paper plans. A running or waiting plan shows entry (blue, dashed while waiting), stop (red)
  // and targets (green). A closed trade keeps only a short entry line from fill to exit: its stop and
  // targets are history and made the candles unreadable (Uzi 27.10.2026). Arrows mark the fill, a dot the exit.
  function drawPlans(groups) {
    for (const plan of model.plans || []) {
      const long = plan.direction === 'LONG';
      const waiting = plan.status === 'OPEN';
      const closed = plan.status === 'CLOSED';
      // A running trade whose stop TIM already moved: the SL is drawn as steps up to where it stands now.
      const steps = plan.stop_steps || [];
      const trailing = !closed && steps.length > 1;
      if (trailing) {
        const points = steps.map(([time, value]) => ({ time: local(time), value }));
        if (plan.t2 > steps[steps.length - 1][0]) points.push({ time: local(plan.t2), value: steps[steps.length - 1][1] });
        const series = chart.addLineSeries({
          color: '#ffb020', lineWidth: 2, lineStyle: LWC.LineStyle.Solid, lineType: LWC.LineType.WithSteps,
          lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
          title: T.slNow, visible: groups.has(plan.group), autoscaleInfoProvider: () => null,
        });
        series.setData(points);
        lines.push({ series, group: plan.group, plan });
      }
      // Box (zones, targets, labels): the positions primitive. A plan without targets keeps the old lines.
      // A boxed running or waiting plan keeps only its blue entry line on top of the box.
      const boxed = positionGeometry(plan) !== null;
      const entryLeg = [plan.entry, '#70a7ff', 2, waiting ? 'dashed' : 'solid', `${plan.label} ${long ? 'L' : 'S'}`];
      const legs = closed
        ? (boxed ? [] : [[plan.entry, long ? 'rgba(53,211,154,0.7)' : 'rgba(255,101,119,0.7)', 1, 'solid', '']])
        : boxed ? [entryLeg]
        : [entryLeg,
           ...(trailing ? [] : [[plan.stop, '#ff6577', 1, 'dashed', 'SL']]),
           ...plan.targets.map((value, index) => [value, '#35d39a', 1, 'dotted', `TP${index + 1}`])];
      for (const [value, color, width, style, title] of legs) {
        const series = chart.addLineSeries({
          color, lineWidth: width, lineStyle: STYLE[style], lastValueVisible: false, priceLineVisible: false,
          crosshairMarkerVisible: false, title, visible: groups.has(plan.group),
          autoscaleInfoProvider: () => null,
        });
        series.setData([{ time: local(plan.t1), value }, { time: local(plan.t2), value }]);
        lines.push({ series, group: plan.group, plan });
      }
    }
  }

  function planMarkers(groups) {
    const marks = [];
    for (const plan of (model && model.plans) || []) {
      if (!groups.has(plan.group)) continue;
      const long = plan.direction === 'LONG';
      // Closed trades: the arrow alone, the result sits at the exit dot (no stacked names).
      if (plan.fill_t != null) {
        marks.push({ time: local(plan.fill_t), position: long ? 'belowBar' : 'aboveBar', color: long ? '#35d39a' : '#ff6577',
                     shape: long ? 'arrowUp' : 'arrowDown', size: 0.8, text: plan.status === 'CLOSED' ? '' : `${plan.label} ${long ? 'L' : 'S'}` });
      }
      if (plan.close_t != null && plan.net_r != null) {
        const r = Number(plan.net_r);
        marks.push({ time: local(plan.close_t), position: long ? 'aboveBar' : 'belowBar', color: r > 0 ? '#35d39a' : r < 0 ? '#ff6577' : '#8491a3',
                     shape: 'circle', text: `${r >= 0 ? '+' : ''}${EN ? r.toFixed(2) : r.toFixed(2).replace('.', ',')} R` });
      }
    }
    // US-CPI and FOMC release dates (display only): a small square above the candle the release fell in.
    if (groups.has('macro')) {
      for (const ev of (model && model.macro) || []) {
        marks.push({ time: local(ev.time), position: 'aboveBar', color: ev.upcoming ? '#8491a3' : '#f0b429', shape: 'square', size: 0.6,
                     text: macroText(ev) });
      }
    }
    marks.sort((a, b) => a.time - b.time);
    candles.setMarkers(marks);
    drawAhead(groups);
  }

  const macroText = ev => (ev.kind === 'CPI' ? 'CPI' : 'FOMC');
  function drawAhead(groups) {
    const events = groups.has('macro') && model ? model.macro_ahead || [] : [];
    const step = model && model.interval_seconds;
    const last = model && model.candles.length ? model.candles[model.candles.length - 1] : null;
    // Adding or removing the empty candles moves Lightweight Charts' right edge: keep the view where it was,
    // otherwise ticking a layer (or "Untick all") jumps the chart days back.
    const view = chart.timeScale().getVisibleLogicalRange();
    const keepView = () => { if (view) chart.timeScale().setVisibleLogicalRange(view); };
    if (!events.length || !step || !last) { ahead.setMarkers([]); ahead.setData([]); keepView(); return; }
    const at = new Set(events.map(ev => ev.time));
    const points = [];
    for (let t = last.time + step; t <= events[events.length - 1].time; t += step) {
      points.push(at.has(t) ? { time: local(t), value: last.close } : { time: local(t) });
    }
    ahead.setData(points);
    keepView();
    ahead.setMarkers(events.map(ev => ({ time: local(ev.time), position: 'aboveBar', color: '#8491a3', shape: 'square', size: 0.6,
                                         text: macroText(ev) })));
  }
  // Right edge of the default view: the newest candle, or the next release date if it lies close enough
  // (within a third of the view) that the candles stay readable. Farther dates are named in the status line.
  function viewRange(width) {
    const count = model.candles.length;
    let to = count + 8;
    const ev = shownGroups().has('macro') && (model.macro_ahead || [])[0];
    const step = model.interval_seconds, last = count ? model.candles[count - 1] : null;
    if (ev && step && last) {
      const edge = count - 1 + Math.round((ev.time - last.time) / step) + 4;
      if (edge > to && edge - to <= width / 3) to = edge;
    }
    return { from: Math.max(0, to - width), to };
  }
  function nextRelease() {
    const ev = model && shownGroups().has('macro') && (model.macro_ahead || [])[0];
    return ev ? `${T.next}: ${macroText(ev)} ${FULL_FMT.format(new Date(Date.parse(ev.at)))}` : '';
  }

  function applyVisibility(groups) {
    planMarkers(groups);
    for (const item of lines) item.series.applyOptions({ visible: groups.has(item.group) });
    tpo.visible = groups.has('tpo');
    vp.visible = groups.has('vp');
    fp.visible = groups.has('fp');
    liq.visible = groups.has('liq');
    liqev.visible = groups.has('liqev');
    fib.visible = groups.has('fib');
    bubbles.visible = groups.has('bubbles');
    layoutBands(groups);
    positions.groups = groups;
    if (positions.requestUpdate) positions.requestUpdate();
    if (tpo.requestUpdate) tpo.requestUpdate();
  }

  function drawLines() {
    for (const item of lines) chart.removeSeries(item.series);
    lines = [];
    const groups = shownGroups();
    for (const d of model.drawings) {
      const series = chart.addLineSeries({
        color: d.color, lineWidth: ['trend', 'week', 'month', 'quarter', 'year', 'vwap'].includes(d.group) ? 2 : 1,
        // Finished segments (BOS/MSS, broken trend lines) get no label on the price axis: they are history, not a live level.
        lineStyle: STYLE[d.style] ?? LWC.LineStyle.Solid, lastValueVisible: !d.finished, priceLineVisible: false,
        crosshairMarkerVisible: false, title: d.finished ? '' : d.label, visible: groups.has(d.group),
        autoscaleInfoProvider: () => null,  // levels never squeeze the candles
      });
      // A running line (VWAP) brings its own points; levels and segments have two.
      const points = d.curve ? d.curve.map(([t, v]) => ({ time: local(t), value: v }))
        : [{ time: local(d.t1), value: d.p1 }, { time: local(d.t2), value: d.p2 }];
      const mid = d.tm != null && d.tm > d.t1 && d.tm < d.t2;
      if (mid) points.splice(1, 0, { time: local(d.tm), value: d.p1 });  // BOS/MSS: horizontal, label in the middle
      series.setData(points);
      // Name at the start of the segment (BOS/MSS: in the middle, above a break up, below a break down);
      // short segments (a level from the last few candles) keep only the label on the price axis,
      // otherwise the texts pile up at the right edge.
      const structure = d.group === 'structure';
      series.setMarkers([{
        time: local(mid ? d.tm : d.t1),
        position: structure ? (d.direction === 'UP' ? 'aboveBar' : 'belowBar') : (d.p2 >= model.last ? 'aboveBar' : 'belowBar'),
        color: d.color, shape: structure ? (d.direction === 'UP' ? 'arrowUp' : 'arrowDown') : 'circle', size: structure ? 0.6 : 0.4,
        text: d.bars >= SHORT_BARS || d.finished ? d.label + (d.clipped ? ' ←' : '') : '',
      }]);
      lines.push({ series, group: d.group, drawing: d });
    }
    positions.groups = groups;
    drawPlans(groups);
    planMarkers(groups);
  }

  function setLegend(bar) {
    if (!model) return;
    const head = `${model.symbol} · ${model.timeframe}`;
    if (!bar) { legend.textContent = `${head} · ${T.price} ${fmt(model.last)}`; return; }
    const change = bar.open ? ((bar.close - bar.open) / bar.open * 100) : 0;
    legend.textContent = `${head} · O ${fmt(bar.open)} H ${fmt(bar.high)} L ${fmt(bar.low)} C ${fmt(bar.close)} (${change >= 0 ? '+' : ''}${(EN ? change.toFixed(2) : change.toFixed(2).replace('.', ','))} %)`;
  }

  chart.subscribeCrosshairMove(param => {
    const bar = param && param.time ? param.seriesData.get(candles) : null;
    setLegend(bar || null);
  });

  async function load() {
    clearTimeout(timer);
    if (!running) return;
    status.textContent = T.loading;
    try {
      const ticket = ++request;  // only the newest request may draw (a slow 1h answer must not overwrite 4h)
      const response = await fetch(`/api/chart/live?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(timeframe)}&market=${encodeURIComponent(market)}`, { cache: 'no-store' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const next = await response.json();
      if (ticket !== request) return;
      if (reloadOnNewVersion(next.app_version)) return;
      const keep = first ? null : chart.timeScale().getVisibleLogicalRange();
      const sameView = model && model.symbol === next.symbol && model.timeframe === next.timeframe;
      model = next;
      fp.byTime = new Map(model.candles.map(c => [c.time, c]));
      buildLayers();
      candles.setData(model.candles.map(c => ({ time: local(c.time), open: c.open, high: c.high, low: c.low, close: c.close })));
      volume.setData(model.candles.map(c => ({ time: local(c.time), value: c.volume, color: c.close >= c.open ? 'rgba(38,166,154,0.35)' : 'rgba(239,83,80,0.35)' })));
      drawLines();
      drawBands();
      showMarket();
      { const groups = shownGroups(); layoutBands(groups); tpo.visible = groups.has('tpo'); vp.visible = groups.has('vp'); fp.visible = groups.has('fp'); liq.visible = groups.has('liq'); liqev.visible = groups.has('liqev'); fib.visible = groups.has('fib'); bubbles.visible = groups.has('bubbles'); }
      if (first || !sameView) {
        chart.timeScale().setVisibleLogicalRange(viewRange(168));
        first = false;
      } else if (keep) {
        chart.timeScale().setVisibleLogicalRange(keep);
      }
      setLegend(null);
      const notes = (model.notes || []).concat(model.footprint && model.footprint.note ? [model.footprint.note] : []).join(' · ');
      const trades = model.trades_updated_at ? ` · Trades: ${model.trade_source} (${T.asOf} ${new Date(model.trades_updated_at).toLocaleTimeString(LOCALE)})` : '';
      const h = model.perp_health;
      const health = h && h.checks ? ' · ' + P.health(h.checks_ok, h.checks, h.gaps) : '';
      const bandNotes = [model.cvd && model.cvd.note].filter(Boolean);
      const allNotes = [nextRelease(), notes, ...bandNotes].filter(Boolean).join(' · ');
      status.textContent = `${model.candles.length} ${T.candles} · Level: ${model.level_source || '–'}${trades}${health} · ${new Date().toLocaleTimeString(LOCALE)}` + (allNotes ? ' · ' + allNotes : '');
    } catch (error) {
      status.textContent = T.failed(error.message);
    } finally {
      if (running) timer = setTimeout(load, 30000);
    }
  }

  root.addEventListener('click', event => {
    const tab = event.target.closest && event.target.closest('a[data-tf]');
    if (tab) {
      event.preventDefault();
      timeframe = tab.dataset.tf;
      markTabs();
      if (PANE) rememberPane();
      else {
        host.dataset.tf = timeframe;
        const url = new URL(location.href);
        url.searchParams.set('tf', timeframe);
        history.replaceState(null, '', url);
      }
      load();
      return;
    }
    const coin = PANE && event.target.closest && event.target.closest('a[data-symbol]');
    if (coin) {  // second pane: the coin changes in place, the page (and the first chart) stays
      event.preventDefault();
      if (coin.dataset.symbol !== symbol) { symbol = coin.dataset.symbol; markTabs(); rememberPane(); load(); }
      return;
    }
    const action = event.target.closest && event.target.closest('[data-action]');
    if (!action) return;
    if (action.dataset.action === 'split') { setSplit(PANE ? false : !secondPane || !secondPane.shown()); return; }
    if (action.dataset.action === 'market' && action.dataset.market && action.dataset.market !== market) {
      market = action.dataset.market;
      try { localStorage.setItem(MARKET_STORE, market); } catch (error) { /* ignore */ }
      showMarket();
      load();
      return;
    }
    if (action.dataset.action === 'now' && model) {  // the newest candle at the right edge (or a release date close behind it)
      autoPrice();  // and the price axis back to the candles in view
      const range = chart.timeScale().getVisibleLogicalRange();
      chart.timeScale().setVisibleLogicalRange(viewRange(range ? range.to - range.from : 168));
    }
    if (action.dataset.action === 'fit') { autoPrice(); chart.timeScale().fitContent(); }
    if (action.dataset.action === 'plans') {
      // Only TIM's current paper plans (SHORT, MID, LONG) on the candles: levels and the 30m test versions off.
      const groups = new Set(Object.keys(model ? model.groups : {}).filter(key => key.startsWith('plans_') && key !== 'plans_old'));
      layers.querySelectorAll('input').forEach(node => { node.checked = groups.has(node.value); });
      saveGroups(groups); applyVisibility(groups); layoutChanged();
    }
    if (action.dataset.action === 'none') {
      // Every tick off: only the candles stay.
      const groups = new Set();
      layers.querySelectorAll('input').forEach(node => { node.checked = false; });
      saveGroups(groups); applyVisibility(groups); layoutChanged();
    }
    if (action.dataset.action === 'footprint' && model) {  // the last candles, about 70 px each: room for bid × ask numbers
      const count = model.candles.length;
      const shown = Math.max(3, Math.floor((box.clientWidth - 80) / 70));  // 80 px: price axis
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, count - shown), to: count + 1 });
      if (!fp.visible) {
        const groups = shownGroups(); groups.add('fp'); saveGroups(groups); applyVisibility(groups); layoutChanged();
        const input = layers.querySelector("input[value='fp']"); if (input) input.checked = true;
      }
    }
    if (action.dataset.action === 'reset') { try { localStorage.removeItem(STORE); } catch (error) { /* ignore */ }
      try { localStorage.removeItem(KNOWN); } catch (error) { /* ignore */ }
      const groups = new Set(model ? model.default_groups : []);
      layers.querySelectorAll('input').forEach(node => { node.checked = groups.has(node.value); });
      applyVisibility(groups); setActiveLayout('tim:standard'); buildLayouts(); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); else clearTimeout(timer); });
  load();
  return {
    shown: () => running,
    pause() { running = false; request += 1; clearTimeout(timer); },
    resume() { running = true; load(); },
  };
  }
  start('');
  let split = false;
  try { split = localStorage.getItem(SPLIT_STORE) === '1'; } catch (error) { /* ignore */ }
  if (split) setSplit(true);
})();
