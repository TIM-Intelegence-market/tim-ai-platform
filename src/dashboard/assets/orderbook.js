/* TIM order book dashboard (read-only): live public WebSocket -> book, depth chart, heatmap.
 * Binance first, Coinbase as fallback. No keys, no orders; the browser talks to the exchange directly. */
(function () {
  "use strict";
  var OB = window.TimOB;
  var PAIRS = { BTC: ["BTCUSDT", "BTC-USD"], ETH: ["ETHUSDT", "ETH-USD"], SOL: ["SOLUSDT", "SOL-USD"] };
  var RANGE = 0.01;           // +-1 % around mid for depth chart and heatmap
  var HEAT_COLS = 480, HEAT_EVERY_MS = 1000, DRAW_EVERY_MS = 250, LADDER_ROWS = 14, KEEP_LEVELS = 1500;
  var $ = function (id) { return document.getElementById(id); };

  var state = { coin: "BTC", source: "auto", ws: null, gen: 0, book: new OB.Book(), sync: null, heat: null,
                src: "", status: "", fails: 0, lastMsg: 0, msgs: 0, msgRate: 0, fallback: false };
  state.sync = new OB.BinanceSync(state.book);
  var timers = [];

  function setStatus(text, kind) { var el = $("ob-status"); el.textContent = text; el.setAttribute("data-kind", kind || "wait"); }
  function fmt(x, d) { return x === null || x === undefined || !isFinite(x) ? "–" : x.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function decimals(p) { return p >= 1000 ? 2 : p >= 10 ? 3 : 4; }

  function close() {
    state.gen++;
    timers.forEach(clearTimeout); timers = [];
    if (state.ws) { try { state.ws.onclose = state.ws.onerror = state.ws.onmessage = null; state.ws.close(); } catch (e) {} state.ws = null; }
  }

  function start() {
    close();
    var gen = state.gen;
    state.book.reset([], []); state.sync.restart(); state.heat = null; state.msgs = 0;
    var useCoinbase = state.source === "coinbase" || (state.source === "auto" && state.fallback);
    if (useCoinbase) connectCoinbase(gen); else connectBinance(gen);
  }

  function failover(gen, why) {
    if (gen !== state.gen) return;
    state.fails++;
    if (state.source === "auto" && !state.fallback && state.fails >= 2) {
      state.fallback = true; state.fails = 0;
      setStatus("Binance nicht erreichbar (" + why + "), wechsle zu Coinbase", "warn");
      return start();
    }
    setStatus("Verbindung weg (" + why + "), neuer Versuch in 3 s", "warn");
    close(); var g = state.gen;
    timers.push(setTimeout(function () { if (g === state.gen) start(); }, 3000));
  }

  /* ---- Binance: diff depth + REST snapshot (official sync procedure) ---- */
  function connectBinance(gen) {
    var sym = PAIRS[state.coin][0];
    state.src = "Binance " + sym; setStatus("Verbinde mit Binance …", "wait");
    var ws = new WebSocket("wss://stream.binance.com:9443/ws/" + sym.toLowerCase() + "@depth@100ms");
    state.ws = ws;
    var snapped = false;
    function loadSnapshot() {
      fetch("https://api.binance.com/api/v3/depth?symbol=" + sym + "&limit=1000", { cache: "no-store", credentials: "omit" })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(function (snap) {
          if (gen !== state.gen) return;
          var res = state.sync.snapshot(snap);
          if (res === "resync") { state.sync.restart(); return loadSnapshot(); }
          snapped = true; state.fails = 0; setStatus("Live: " + state.src, "ok");
        })
        .catch(function (e) { failover(gen, "Snapshot " + e.message); });
    }
    ws.onopen = loadSnapshot;
    ws.onerror = function () { failover(gen, "WebSocket-Fehler"); };
    ws.onclose = function () { failover(gen, "WebSocket geschlossen"); };
    ws.onmessage = function (m) {
      if (gen !== state.gen) return;
      var ev; try { ev = JSON.parse(m.data); } catch (e) { return; }
      if (ev.e !== "depthUpdate") return;
      state.msgs++; state.lastMsg = Date.now();
      var r = state.sync.feed(ev);
      if (r === "resync") { setStatus("Lücke im Strom, lade Snapshot neu …", "warn"); state.sync.restart(); snapped = false; loadSnapshot(); }
      else if (snapped && r === "ok") state.book.trim(KEEP_LEVELS);
    };
  }

  /* ---- Coinbase Exchange: level2_batch (snapshot, then l2update) ---- */
  function connectCoinbase(gen) {
    var product = PAIRS[state.coin][1];
    state.src = "Coinbase " + product; setStatus("Verbinde mit Coinbase …", "wait");
    var ws = new WebSocket("wss://ws-feed.exchange.coinbase.com");
    state.ws = ws;
    ws.onopen = function () { ws.send(JSON.stringify({ type: "subscribe", product_ids: [product], channels: ["level2_batch"] })); };
    ws.onerror = function () { failover(gen, "WebSocket-Fehler"); };
    ws.onclose = function () { failover(gen, "WebSocket geschlossen"); };
    ws.onmessage = function (m) {
      if (gen !== state.gen) return;
      var d; try { d = JSON.parse(m.data); } catch (e) { return; }
      if (d.type === "snapshot") { state.book.reset(d.bids, d.asks); state.fails = 0; setStatus("Live: " + state.src, "ok"); }
      else if (d.type === "l2update") {
        var b = [], a = [];
        (d.changes || []).forEach(function (c) { (c[0] === "buy" ? b : a).push([c[1], c[2]]); });
        state.book.update(b, a); state.book.trim(KEEP_LEVELS); state.msgs++; state.lastMsg = Date.now();
      } else if (d.type === "error") { failover(gen, d.message || d.reason || "Coinbase-Fehler"); }
    };
  }

  /* ---- rendering ---- */
  function fit(canvas) {
    var r = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    var w = Math.max(200, Math.round(r.width)), h = Math.round(canvas.getAttribute("data-h") || 300);
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; canvas.style.height = h + "px"; }
    var ctx = canvas.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, w: w, h: h };
  }
  var C = { bid: "#35d39a", ask: "#ff6b6b", grid: "rgba(255,255,255,.08)", text: "#9aa7b4", mid: "#e6edf3" };

  function drawDepth(met) {
    var f = fit($("ob-depth")), ctx = f.ctx, w = f.w, h = f.h, padB = 20, padL = 6;
    ctx.clearRect(0, 0, w, h);
    if (!met) return;
    var cur = OB.depthCurve(state.book, met.mid, RANGE), lo = met.mid * (1 - RANGE), hi = met.mid * (1 + RANGE);
    var maxCum = Math.max(1e-9, cur.bids.length ? cur.bids[cur.bids.length - 1][1] : 0, cur.asks.length ? cur.asks[cur.asks.length - 1][1] : 0);
    var X = function (p) { return padL + (p - lo) / (hi - lo) * (w - 2 * padL); };
    var Y = function (c) { return h - padB - c / maxCum * (h - padB - 10); };
    function area(pts, color, edge) {
      if (!pts.length) return;
      ctx.beginPath(); ctx.moveTo(X(pts[0][0]), Y(0));
      var prev = Y(0);
      pts.forEach(function (pt) { ctx.lineTo(X(pt[0]), prev); ctx.lineTo(X(pt[0]), Y(pt[1])); prev = Y(pt[1]); });
      ctx.lineTo(X(edge), prev); ctx.lineTo(X(edge), Y(0)); ctx.closePath();
      ctx.fillStyle = color + "33"; ctx.fill(); ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
    }
    area(cur.bids, C.bid, lo); area(cur.asks, C.ask, hi);
    ctx.strokeStyle = C.grid; ctx.fillStyle = C.text; ctx.font = "11px system-ui,sans-serif"; ctx.lineWidth = 1;
    for (var i = 0; i <= 4; i++) {
      var p = lo + (hi - lo) * i / 4, x = X(p);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h - padB); ctx.stroke();
      ctx.textAlign = i === 0 ? "left" : i === 4 ? "right" : "center"; ctx.fillText(fmt(p, 0), x, h - 6);
    }
    ctx.strokeStyle = C.mid; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(X(met.mid), 0); ctx.lineTo(X(met.mid), h - padB); ctx.stroke(); ctx.setLineDash([]);
    ctx.textAlign = "left"; ctx.fillStyle = C.text; ctx.fillText("kum. Menge ±" + (RANGE * 100) + " % · max " + fmt(maxCum, 2), padL + 4, 12);
  }

  function color(v) { // dark blue -> teal -> yellow -> white-ish
    var stops = [[0, 10, 16, 28], [0.35, 24, 80, 140], [0.7, 240, 190, 50], [1, 255, 250, 235]], i = 1;
    while (i < stops.length - 1 && v > stops[i][0]) i++;
    var a = stops[i - 1], b = stops[i], t = Math.min(1, Math.max(0, (v - a[0]) / (b[0] - a[0])));
    return "rgb(" + Math.round(a[1] + (b[1] - a[1]) * t) + "," + Math.round(a[2] + (b[2] - a[2]) * t) + "," + Math.round(a[3] + (b[3] - a[3]) * t) + ")";
  }
  function drawHeat(met) {
    var f = fit($("ob-heat")), ctx = f.ctx, w = f.w, h = f.h, padR = 62;
    ctx.fillStyle = "#0a101c"; ctx.fillRect(0, 0, w, h);
    var heat = state.heat; if (!met || !heat || !heat.cols.length) return;
    var lo = met.mid * (1 - RANGE), hi = met.mid * (1 + RANGE), cap = heat.cap();
    var plotW = w - padR, cw = plotW / heat.max, tick = heat.tick, rowH = Math.max(1, tick / (hi - lo) * h) + 0.5;
    var Y = function (p) { return h - (p - lo) / (hi - lo) * h; };
    var x0 = plotW - heat.cols.length * cw;
    heat.cols.forEach(function (col, i) {
      col.cells.forEach(function (q, k) {
        var p = k * tick; if (p < lo - tick || p > hi) return;
        ctx.fillStyle = color(OB.intensity(q, cap)); ctx.fillRect(x0 + i * cw, Y(p + tick), cw + 0.5, rowH);
      });
    });
    ctx.strokeStyle = C.mid; ctx.lineWidth = 1.2; ctx.beginPath();
    heat.cols.forEach(function (col, i) { var x = x0 + (i + 0.5) * cw, y = Y(col.mid); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
    ctx.stroke();
    ctx.fillStyle = C.text; ctx.font = "11px system-ui,sans-serif"; ctx.textAlign = "left";
    for (var i = 0; i <= 4; i++) { var p = lo + (hi - lo) * i / 4; ctx.fillText(fmt(p, 0), plotW + 6, Y(p) + 4); }
    ctx.fillText("Spalte = " + (HEAT_EVERY_MS / 1000) + " s · hell = viel Liquidität", 6, 12);
  }

  // Built as DOM nodes: the page CSP forbids inline style attributes.
  function fillRows(box, levels, side, maxQ, d) {
    while (box.children.length > levels.length) box.removeChild(box.lastChild);
    levels.forEach(function (l, i) {
      var row = box.children[i];
      if (!row) {
        row = document.createElement("div");
        row.appendChild(document.createElement("i")); row.appendChild(document.createElement("span")); row.appendChild(document.createElement("span"));
        box.appendChild(row);
      }
      row.className = "ob-row ob-" + side;
      row.children[0].style.width = Math.min(100, l[1] / maxQ * 100).toFixed(1) + "%";
      row.children[1].textContent = fmt(l[0], d); row.children[2].textContent = fmt(l[1], 4);
    });
  }
  function drawLadder(met) {
    if (!met) return;
    var d = decimals(met.mid), tick = OB.niceTick(met.mid * 0.00005);
    var asks = OB.aggregate(state.book.sorted("ask", 600), tick, "ask").slice(0, LADDER_ROWS);
    var bids = OB.aggregate(state.book.sorted("bid", 600), tick, "bid").slice(0, LADDER_ROWS);
    var maxQ = Math.max(1e-9, Math.max.apply(null, asks.concat(bids).map(function (l) { return l[1]; })));
    fillRows($("ob-asks"), asks.slice().reverse(), "ask", maxQ, d);
    fillRows($("ob-bids"), bids, "bid", maxQ, d);
    $("ob-mid").textContent = fmt(met.mid, d);
    $("ob-tick").textContent = "Raster " + fmt(tick, tick < 1 ? 2 : 0);
  }
  function drawMetrics(met) {
    var age = state.lastMsg ? (Date.now() - state.lastMsg) / 1000 : null;
    var d = met ? decimals(met.mid) : 2;
    var imb = met ? met.imbalance : null;
    var cells = [
      ["Quelle", state.src || "–"],
      ["Bestes Gebot / Angebot", met ? fmt(met.bestBid, d) + " / " + fmt(met.bestAsk, d) : "–"],
      ["Spread", met ? fmt(met.spread, d) + " (" + fmt(met.spreadBps, 2) + " bp)" : "–"],
      ["Mikropreis", met ? fmt(met.micro, d) + " (" + (met.micro >= met.mid ? "+" : "") + fmt(met.micro - met.mid, d) + " zur Mitte)" : "–"],
      ["Ungleichgewicht (Top 10)", imb === null ? "–" : (imb >= 0 ? "+" : "") + fmt(imb * 100, 0) + " % " + (imb > 0.1 ? "Käufer" : imb < -0.1 ? "Verkäufer" : "ausgeglichen")],
      ["Updates/s", fmt(state.msgRate, 1) + (age !== null ? " · letztes vor " + fmt(age, 1) + " s" : "")]
    ];
    var box = $("ob-metrics"); box.textContent = "";
    cells.forEach(function (c) {
      var div = document.createElement("div"), k = document.createElement("span"), v = document.createElement("b");
      k.textContent = c[0]; v.textContent = c[1]; div.appendChild(k); div.appendChild(v); box.appendChild(div);
    });
  }

  function tick() {
    var met = OB.metrics(state.book, 10);
    drawMetrics(met); drawLadder(met); drawDepth(met); drawHeat(met);
  }
  function sampleHeat() {
    var met = OB.metrics(state.book, 10); if (!met) return;
    if (!state.heat) state.heat = new OB.Heat(HEAT_COLS, OB.niceTick(met.mid * RANGE * 2 / 150));
    state.heat.push(state.book, met.mid, RANGE, Date.now());
  }

  function init() {
    var coin = $("ob-coin"), src = $("ob-source");
    coin.addEventListener("change", function () { state.coin = coin.value; state.fallback = false; state.fails = 0; start(); });
    src.addEventListener("change", function () { state.source = src.value; state.fallback = false; state.fails = 0; start(); });
    window.addEventListener("resize", tick);
    var last = 0;
    setInterval(function () { state.msgRate = (state.msgs - last) / 2; last = state.msgs; }, 2000);
    setInterval(tick, DRAW_EVERY_MS);
    setInterval(sampleHeat, HEAT_EVERY_MS);
    start();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
