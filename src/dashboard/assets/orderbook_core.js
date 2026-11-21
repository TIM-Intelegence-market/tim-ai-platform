/* TIM order book core: pure logic (book, Binance sync, depth curve, heatmap, microstructure).
 * No DOM, no network; runs in the browser (window.TimOB) and in node (module.exports) for tests. */
(function (root) {
  "use strict";

  function Book() { this.bids = new Map(); this.asks = new Map(); }
  Book.prototype.reset = function (bids, asks) {
    this.bids.clear(); this.asks.clear();
    this.update(bids, asks);
  };
  // Levels are [price, qty] (strings or numbers); qty 0 removes the level.
  Book.prototype.update = function (bids, asks) {
    var self = this;
    [[bids, this.bids], [asks, this.asks]].forEach(function (pair) {
      (pair[0] || []).forEach(function (l) {
        var p = +l[0], q = +l[1];
        if (!isFinite(p) || !isFinite(q)) return;
        if (q === 0) pair[1].delete(p); else pair[1].set(p, q);
      });
    });
    // A level that crosses the other side is stale: drop it so spread never goes negative.
    var bb = this.bestBid(), ba = this.bestAsk();
    if (bb !== null && ba !== null && bb >= ba) {
      if (bids && bids.length && !(asks && asks.length)) this.asks.forEach(function (_, p) { if (p <= bb) self.asks.delete(p); });
      else this.bids.forEach(function (_, p) { if (p >= ba) self.bids.delete(p); });
    }
  };
  Book.prototype.bestBid = function () { var m = null; this.bids.forEach(function (_, p) { if (m === null || p > m) m = p; }); return m; };
  Book.prototype.bestAsk = function () { var m = null; this.asks.forEach(function (_, p) { if (m === null || p < m) m = p; }); return m; };
  // Sorted from the touch outwards: bids descending, asks ascending.
  Book.prototype.sorted = function (side, n) {
    var arr = Array.from((side === "bid" ? this.bids : this.asks).entries());
    arr.sort(side === "bid" ? function (a, b) { return b[0] - a[0]; } : function (a, b) { return a[0] - b[0]; });
    return n ? arr.slice(0, n) : arr;
  };
  // Keep memory bounded: only the closest `max` levels per side survive.
  Book.prototype.trim = function (max) {
    var self = this;
    [["bid", this.bids], ["ask", this.asks]].forEach(function (pair) {
      if (pair[1].size <= max * 2) return;
      var keep = new Set(self.sorted(pair[0], max).map(function (l) { return l[0]; }));
      pair[1].forEach(function (_, p) { if (!keep.has(p)) pair[1].delete(p); });
    });
  };

  /* Binance diff-depth sync (official procedure): buffer events, load snapshot, drop events with
   * u <= lastUpdateId, first applied event must satisfy U <= lastUpdateId+1 <= u, afterwards every
   * event must continue seamlessly (U == previous u + 1), a gap forces a resync. */
  function BinanceSync(book) { this.book = book; this.restart(); }
  BinanceSync.prototype.restart = function () { this.buffer = []; this.last = null; this.synced = false; };
  BinanceSync.prototype.snapshot = function (snap) {
    this.book.reset(snap.bids, snap.asks);
    this.last = snap.lastUpdateId;
    var pending = this.buffer; this.buffer = []; this.synced = false;
    for (var i = 0; i < pending.length; i++) if (this.feed(pending[i]) === "resync") return "resync";
    return this.synced ? "ok" : "waiting";
  };
  // Returns "buffered" | "ok" | "ignored" | "resync".
  BinanceSync.prototype.feed = function (ev) {
    if (this.last === null) { this.buffer.push(ev); return "buffered"; }
    if (ev.u <= this.last) return "ignored";
    if (!this.synced) {
      if (ev.U > this.last + 1) return "resync";
      this.synced = true;
    } else if (ev.U !== this.last + 1) {
      return "resync";
    }
    this.book.update(ev.b, ev.a);
    this.last = ev.u;
    return "ok";
  };

  // Cumulative depth within +-pct of mid. Returns {bids:[[price,cum]...], asks:[...]} touch -> outwards.
  function depthCurve(book, mid, pct) {
    var lo = mid * (1 - pct), hi = mid * (1 + pct), cum, out = { bids: [], asks: [] };
    cum = 0; book.sorted("bid").forEach(function (l) { if (l[0] >= lo) { cum += l[1]; out.bids.push([l[0], cum]); } });
    cum = 0; book.sorted("ask").forEach(function (l) { if (l[0] <= hi) { cum += l[1]; out.asks.push([l[0], cum]); } });
    return out;
  }

  // Aggregate levels into price buckets of width `tick` (bids round down, asks round up).
  function aggregate(levels, tick, side) {
    var m = new Map();
    levels.forEach(function (l) {
      var k = side === "bid" ? Math.floor(l[0] / tick) * tick : Math.ceil(l[0] / tick) * tick;
      k = Math.round(k / tick) * tick;
      m.set(k, (m.get(k) || 0) + l[1]);
    });
    return Array.from(m.entries()).sort(side === "bid" ? function (a, b) { return b[0] - a[0]; } : function (a, b) { return a[0] - b[0]; });
  }

  // Round to 1/2/5 x 10^n.
  function niceTick(x) {
    if (!(x > 0)) return 1;
    var e = Math.pow(10, Math.floor(Math.log10(x))), f = x / e;
    return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * e;
  }

  // Microstructure numbers from the current book. `n` = levels for the touch imbalance.
  function metrics(book, n) {
    var bb = book.bestBid(), ba = book.bestAsk();
    if (bb === null || ba === null) return null;
    var bidTop = book.sorted("bid", n), askTop = book.sorted("ask", n);
    var sb = bidTop.reduce(function (s, l) { return s + l[1]; }, 0);
    var sa = askTop.reduce(function (s, l) { return s + l[1]; }, 0);
    var qb = book.bids.get(bb), qa = book.asks.get(ba), mid = (bb + ba) / 2;
    return {
      bestBid: bb, bestAsk: ba, mid: mid, spread: ba - bb, spreadBps: (ba - bb) / mid * 1e4,
      // Volume-weighted mid: leans towards the thinner side of the touch.
      micro: (bb * qa + ba * qb) / (qa + qb),
      imbalance: sb + sa > 0 ? (sb - sa) / (sb + sa) : 0, // +1 = only bids, -1 = only asks
      bidDepth: sb, askDepth: sa
    };
  }

  /* Liquidity heatmap: one column per sample, each a sparse map bucket -> qty around the mid.
   * Absolute price axis; bucket width is fixed per instance so columns stay comparable. */
  function Heat(maxCols, tick) { this.max = maxCols; this.tick = tick; this.cols = []; }
  Heat.prototype.push = function (book, mid, pct, t) {
    var lo = mid * (1 - pct), hi = mid * (1 + pct), tick = this.tick, m = new Map();
    [book.bids, book.asks].forEach(function (side) {
      side.forEach(function (q, p) {
        if (p < lo || p > hi) return;
        var k = Math.floor(p / tick); // bucket index, price = k * tick
        m.set(k, (m.get(k) || 0) + q);
      });
    });
    this.cols.push({ t: t, mid: mid, cells: m });
    if (this.cols.length > this.max) this.cols.shift();
  };
  // Colour scale input: log-compressed 0..1 against a robust cap (e.g. 95th percentile of cells).
  Heat.prototype.cap = function () {
    var vals = [];
    this.cols.forEach(function (c) { c.cells.forEach(function (q) { vals.push(q); }); });
    if (!vals.length) return 1;
    vals.sort(function (a, b) { return a - b; });
    return vals[Math.min(vals.length - 1, Math.floor(vals.length * 0.97))] || 1;
  };
  function intensity(q, cap) { return q <= 0 ? 0 : Math.min(1, Math.log1p(q) / Math.log1p(cap)); }

  var api = { Book: Book, BinanceSync: BinanceSync, depthCurve: depthCurve, aggregate: aggregate, niceTick: niceTick, metrics: metrics, Heat: Heat, intensity: intensity };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.TimOB = api;
})(typeof window !== "undefined" ? window : this);
