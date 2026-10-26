// TIM-Chart: interactive candles with labelled level segments (read-only, no orders).
// Data: /api/chart/live?symbol=&tf= (src/dashboard/chart_live.py). Library: TradingView
// Lightweight Charts 4.2.3 (Apache 2.0), served locally from /assets/chart/.
(() => {
  'use strict';
  const root = document.getElementById('tc-live');
  if (!root || !window.LightweightCharts) return;
  const LWC = window.LightweightCharts;
  const box = document.getElementById('tc-live-chart');
  const legend = document.getElementById('tc-live-legend');
  const status = document.getElementById('tc-live-status');
  const layers = document.getElementById('tc-live-layers');
  const STORE = 'tim-chart-layers-v1';
  const SHORT_BARS = 12;
  const STYLE = { solid: LWC.LineStyle.Solid, dotted: LWC.LineStyle.Dotted, dashed: LWC.LineStyle.Dashed };
  let symbol = root.dataset.symbol, timeframe = root.dataset.tf, timer = null, model = null, first = true, request = 0;
  let lines = [];

  // Times arrive in UTC seconds; the chart shows the viewer's current local time. One fixed
  // offset for all points: a per-point offset would fold the hour at the DST change and the
  // library rejects times that are not strictly ascending.
  const OFFSET = -new Date().getTimezoneOffset() * 60;
  const local = t => t + OFFSET;
  const fmt = v => v == null ? '–' : Number(v).toLocaleString('de-DE', { maximumFractionDigits: v < 10 ? 4 : v < 1000 ? 2 : 1 });

  const chart = LWC.createChart(box, {
    autoSize: true,
    layout: { background: { type: 'solid', color: '#0b0f16' }, textColor: '#c3cad6', fontSize: 12, attributionLogo: false },
    grid: { vertLines: { color: 'rgba(120,134,156,0.10)' }, horzLines: { color: 'rgba(120,134,156,0.10)' } },
    crosshair: { mode: LWC.CrosshairMode.Normal },
    rightPriceScale: { borderColor: 'rgba(120,134,156,0.35)', scaleMargins: { top: 0.06, bottom: 0.18 } },
    timeScale: { borderColor: 'rgba(120,134,156,0.35)', timeVisible: true, secondsVisible: false, rightOffset: 8 },
    localization: { locale: 'de-DE', priceFormatter: fmt },
  });
  const candles = chart.addCandlestickSeries({
    upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    priceLineColor: '#c3cad6',
  });
  const volume = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });

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
                  ctx.fillText(`TPO ${day.label}${day.running ? ' lfd.' : ''} · POC ${fmt(day.poc)}${anyLetters ? '' : ' · ' + day.periods + ' Perioden'}`, x0 + 2, Math.max(12, yLabel - 2));
                }
              }
            });
          },
        };
      },
    },
  };
  candles.attachPrimitive(tpo);

  function shownGroups() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || 'null');
      if (Array.isArray(saved)) return new Set(saved);
    } catch (error) { /* private window: defaults */ }
    return new Set(model ? model.default_groups : []);
  }
  function saveGroups(groups) {
    try { localStorage.setItem(STORE, JSON.stringify([...groups])); } catch (error) { /* ignore */ }
  }

  function buildLayers() {
    if (!model || layers.dataset.built) return;
    const groups = shownGroups();
    for (const [key, name] of Object.entries(model.groups)) {
      const label = document.createElement('label');
      label.className = 'tc-layer tc-layer--' + key;
      const input = document.createElement('input');
      input.type = 'checkbox'; input.value = key; input.checked = groups.has(key);
      input.addEventListener('change', () => {
        const now = new Set([...layers.querySelectorAll('input:checked')].map(node => node.value));
        saveGroups(now); applyVisibility(now);
      });
      label.append(input, document.createTextNode(' ' + name));
      layers.append(label);
    }
    layers.dataset.built = '1';
  }

  function applyVisibility(groups) {
    for (const item of lines) item.series.applyOptions({ visible: groups.has(item.group) });
    tpo.visible = groups.has('tpo');
    if (tpo.requestUpdate) tpo.requestUpdate();
  }

  function drawLines() {
    for (const item of lines) chart.removeSeries(item.series);
    lines = [];
    const groups = shownGroups();
    for (const d of model.drawings) {
      const series = chart.addLineSeries({
        color: d.color, lineWidth: d.group === 'trend' || d.group === 'week' || d.group === 'month' ? 2 : 1,
        // Finished segments (BOS/MSS, broken trend lines) get no label on the price axis: they are history, not a live level.
        lineStyle: STYLE[d.style] ?? LWC.LineStyle.Solid, lastValueVisible: !d.finished, priceLineVisible: false,
        crosshairMarkerVisible: false, title: d.finished ? '' : d.label, visible: groups.has(d.group),
        autoscaleInfoProvider: () => null,  // levels never squeeze the candles
      });
      series.setData([{ time: local(d.t1), value: d.p1 }, { time: local(d.t2), value: d.p2 }]);
      // Name at the start of the segment; short segments (a level from the last few candles) keep only the
      // label on the price axis, otherwise the texts pile up at the right edge.
      series.setMarkers([{
        time: local(d.t1), position: d.p2 >= model.last ? 'aboveBar' : 'belowBar', color: d.color, shape: 'circle', size: 0.4,
        text: d.bars >= SHORT_BARS || d.finished ? d.label + (d.clipped ? ' ←' : '') : '',
      }]);
      lines.push({ series, group: d.group, drawing: d });
    }
  }

  function setLegend(bar) {
    if (!model) return;
    const head = `${model.symbol} · ${model.timeframe}`;
    if (!bar) { legend.textContent = `${head} · Kurs ${fmt(model.last)}`; return; }
    const change = bar.open ? ((bar.close - bar.open) / bar.open * 100) : 0;
    legend.textContent = `${head} · O ${fmt(bar.open)} H ${fmt(bar.high)} L ${fmt(bar.low)} C ${fmt(bar.close)} (${change >= 0 ? '+' : ''}${change.toFixed(2).replace('.', ',')} %)`;
  }

  chart.subscribeCrosshairMove(param => {
    const bar = param && param.time ? param.seriesData.get(candles) : null;
    setLegend(bar || null);
  });

  async function load() {
    clearTimeout(timer);
    status.textContent = 'Lade…';
    try {
      const ticket = ++request;  // only the newest request may draw (a slow 1h answer must not overwrite 4h)
      const response = await fetch(`/api/chart/live?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(timeframe)}`, { cache: 'no-store' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const next = await response.json();
      if (ticket !== request) return;
      const keep = first ? null : chart.timeScale().getVisibleLogicalRange();
      const sameView = model && model.symbol === next.symbol && model.timeframe === next.timeframe;
      model = next;
      buildLayers();
      candles.setData(model.candles.map(c => ({ time: local(c.time), open: c.open, high: c.high, low: c.low, close: c.close })));
      volume.setData(model.candles.map(c => ({ time: local(c.time), value: c.volume, color: c.close >= c.open ? 'rgba(38,166,154,0.35)' : 'rgba(239,83,80,0.35)' })));
      drawLines();
      tpo.visible = shownGroups().has('tpo');
      if (first || !sameView) {
        const count = model.candles.length;
        chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, count - 160), to: count + 8 });
        first = false;
      } else if (keep) {
        chart.timeScale().setVisibleLogicalRange(keep);
      }
      setLegend(null);
      const notes = (model.notes || []).join(' · ');
      status.textContent = `${model.candles.length} Kerzen · Level: ${model.level_source || '–'} · ${new Date().toLocaleTimeString('de-DE')}` + (notes ? ' · ' + notes : '');
    } catch (error) {
      status.textContent = `Laden fehlgeschlagen (${error.message}). Neuer Versuch in 30 s.`;
    } finally {
      timer = setTimeout(load, 30000);
    }
  }

  root.addEventListener('click', event => {
    const tab = event.target.closest && event.target.closest('a[data-tf]');
    if (tab) {
      event.preventDefault();
      timeframe = tab.dataset.tf;
      root.dataset.tf = timeframe;
      root.querySelectorAll('a[data-tf]').forEach(node => {
        const active = node.dataset.tf === timeframe;
        node.classList.toggle('tc-tab--active', active);
        if (active) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current');
      });
      const url = new URL(location.href);
      url.searchParams.set('tf', timeframe);
      history.replaceState(null, '', url);
      load();
      return;
    }
    const action = event.target.closest && event.target.closest('[data-action]');
    if (!action) return;
    if (action.dataset.action === 'now') chart.timeScale().scrollToRealTime();
    if (action.dataset.action === 'fit') chart.timeScale().fitContent();
    if (action.dataset.action === 'reset') { try { localStorage.removeItem(STORE); } catch (error) { /* ignore */ }
      const groups = new Set(model ? model.default_groups : []);
      layers.querySelectorAll('input').forEach(node => { node.checked = groups.has(node.value); });
      applyVisibility(groups); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); else clearTimeout(timer); });
  load();
})();
