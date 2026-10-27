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
  // The public view (src/dashboard/public_en.py) sets data-lang='en'; the Control Center stays German.
  const EN = root.dataset.lang === 'en';
  const LOCALE = EN ? 'en-US' : 'de-DE';
  const T = EN
    ? { slNow: 'SL now', running: ' running', periods: ' periods', price: 'Price', loading: 'Loading…', candles: 'candles', asOf: 'as of',
        failed: m => `Loading failed (${m}). Retrying in 30 s.` }
    : { slNow: 'SL jetzt', running: ' lfd.', periods: ' Perioden', price: 'Kurs', loading: 'Lade…', candles: 'Kerzen', asOf: 'Stand',
        failed: m => `Laden fehlgeschlagen (${m}). Neuer Versuch in 30 s.` };
  const fmt = v => v == null ? '–' : Number(v).toLocaleString(LOCALE, { maximumFractionDigits: v < 10 ? 4 : v < 1000 ? 2 : 1 });

  const chart = LWC.createChart(box, {
    autoSize: true,
    layout: { background: { type: 'solid', color: '#0b0f16' }, textColor: '#c3cad6', fontSize: 12, attributionLogo: false },
    grid: { vertLines: { color: 'rgba(120,134,156,0.10)' }, horzLines: { color: 'rgba(120,134,156,0.10)' } },
    crosshair: { mode: LWC.CrosshairMode.Normal },
    rightPriceScale: { borderColor: 'rgba(120,134,156,0.35)', scaleMargins: { top: 0.06, bottom: 0.18 } },
    timeScale: { borderColor: 'rgba(120,134,156,0.35)', timeVisible: true, secondsVisible: false, rightOffset: 8 },
    localization: { locale: LOCALE, priceFormatter: fmt },
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

  // Footprint: bid x ask per price step inside each bar when the bars are wide enough;
  // imbalances (diagonal 4:1) with a filled background, delta under the bar.
  const fp = {
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
            if (!fp.visible || !fp.chart || !model || !model.footprint || !model.footprint.bars.length) return;
            target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
              const scale = fp.chart.timeScale();
              const step = model.footprint.step;
              const range = scale.getVisibleLogicalRange();
              if (!range) return;
              const barWidth = mediaSize.width / Math.max(1, range.to - range.from);
              if (barWidth < 26) return;  // too narrow for numbers: zoom in
              const short = v => v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
              ctx.font = `${barWidth >= 60 ? 10 : 9}px ui-monospace, Menlo, monospace`;
              ctx.textBaseline = 'middle';
              for (const bar of model.footprint.bars) {
                const x = scale.timeToCoordinate(local(bar.time));
                if (x === null || x < -barWidth || x > mediaSize.width + barWidth) continue;
                const half = Math.min(barWidth / 2 - 1, 44);
                const marks = new Set(bar.imbalances.map(i => i[0] + ':' + i[1]));
                for (const [price, bid, ask] of bar.levels) {
                  const yTop = fp.series.priceToCoordinate(price + step);
                  const yBottom = fp.series.priceToCoordinate(price);
                  if (yTop === null || yBottom === null) continue;
                  const height = yBottom - yTop;
                  if (height < 8) continue;
                  const y = (yTop + yBottom) / 2;
                  const bidMark = marks.has(price + ':bid'), askMark = marks.has(price + ':ask');
                  ctx.fillStyle = 'rgba(11,15,22,0.72)';  // dark cell so the numbers stay readable over the candle body
                  ctx.fillRect(x - half, yTop + 1, 2 * half, height - 2);
                  if (bidMark) { ctx.fillStyle = 'rgba(239,83,80,0.45)'; ctx.fillRect(x - half, yTop + 1, half - 1, height - 2); }
                  if (askMark) { ctx.fillStyle = 'rgba(38,166,154,0.45)'; ctx.fillRect(x + 1, yTop + 1, half - 1, height - 2); }
                  if (price === bar.poc) { ctx.fillStyle = 'rgba(245,197,66,0.25)'; ctx.fillRect(x - half, yTop + 1, 2 * half, height - 2); }
                  ctx.textAlign = 'right';
                  ctx.fillStyle = bidMark ? '#ffd7d9' : 'rgba(255,150,150,0.95)';
                  ctx.fillText(short(bid), x - 2, y, half - 3);
                  ctx.textAlign = 'left';
                  ctx.fillStyle = askMark ? '#d2fff3' : 'rgba(140,230,200,0.95)';
                  ctx.fillText(short(ask), x + 2, y, half - 3);
                }
                const low = Math.min(...bar.levels.map(l => l[0]));
                const yDelta = fp.series.priceToCoordinate(low);
                if (yDelta !== null) {
                  ctx.textAlign = 'center';
                  ctx.fillStyle = bar.delta >= 0 ? 'rgba(38,166,154,1)' : 'rgba(239,83,80,1)';
                  ctx.fillText(`Δ ${bar.delta >= 0 ? '+' : '-'}${short(Math.abs(bar.delta))}`, x, yDelta + 9, 2 * half);
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

  // Layers added after a visitor saved a choice (e.g. TIM's plans) start visible: only keys the
  // visitor has seen before can be hidden by a saved choice.
  const KNOWN = 'tim-chart-layers-known-v1';
  function shownGroups() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || 'null');
      if (Array.isArray(saved)) {
        const known = new Set(JSON.parse(localStorage.getItem(KNOWN) || '[]'));
        const groups = new Set(saved);
        for (const key of (model ? model.default_groups : [])) if (!known.has(key) && known.size) groups.add(key);
        if (!known.size) for (const key of (model ? model.default_groups : [])) if (key.startsWith('plans_')) groups.add(key);
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
      const legs = closed
        ? [[plan.entry, long ? 'rgba(53,211,154,0.7)' : 'rgba(255,101,119,0.7)', 1, 'solid', '']]
        : [[plan.entry, '#70a7ff', 2, waiting ? 'dashed' : 'solid', `${plan.label} ${long ? 'L' : 'S'}`],
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
    marks.sort((a, b) => a.time - b.time);
    candles.setMarkers(marks);
  }

  function applyVisibility(groups) {
    planMarkers(groups);
    for (const item of lines) item.series.applyOptions({ visible: groups.has(item.group) });
    tpo.visible = groups.has('tpo');
    vp.visible = groups.has('vp');
    fp.visible = groups.has('fp');
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
      const points = [{ time: local(d.t1), value: d.p1 }, { time: local(d.t2), value: d.p2 }];
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
    status.textContent = T.loading;
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
      { const groups = shownGroups(); tpo.visible = groups.has('tpo'); vp.visible = groups.has('vp'); fp.visible = groups.has('fp'); }
      if (first || !sameView) {
        const count = model.candles.length;
        chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, count - 160), to: count + 8 });
        first = false;
      } else if (keep) {
        chart.timeScale().setVisibleLogicalRange(keep);
      }
      setLegend(null);
      const notes = (model.notes || []).concat(model.footprint && model.footprint.note ? [model.footprint.note] : []).join(' · ');
      const trades = model.trades_updated_at ? ` · Trades: ${model.trade_source} (${T.asOf} ${new Date(model.trades_updated_at).toLocaleTimeString(LOCALE)})` : '';
      status.textContent = `${model.candles.length} ${T.candles} · Level: ${model.level_source || '–'}${trades} · ${new Date().toLocaleTimeString(LOCALE)}` + (notes ? ' · ' + notes : '');
    } catch (error) {
      status.textContent = T.failed(error.message);
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
    if (action.dataset.action === 'plans') {
      // Only TIM's current paper plans (SHORT, MID, LONG) on the candles: levels and the 30m test versions off.
      const groups = new Set(Object.keys(model ? model.groups : {}).filter(key => key.startsWith('plans_') && key !== 'plans_old'));
      layers.querySelectorAll('input').forEach(node => { node.checked = groups.has(node.value); });
      saveGroups(groups); applyVisibility(groups);
    }
    if (action.dataset.action === 'none') {
      // Every tick off: only the candles stay.
      const groups = new Set();
      layers.querySelectorAll('input').forEach(node => { node.checked = false; });
      saveGroups(groups); applyVisibility(groups);
    }
    if (action.dataset.action === 'reset') { try { localStorage.removeItem(STORE); } catch (error) { /* ignore */ }
      const groups = new Set(model ? model.default_groups : []);
      layers.querySelectorAll('input').forEach(node => { node.checked = groups.has(node.value); });
      applyVisibility(groups); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); else clearTimeout(timer); });
  load();
})();
