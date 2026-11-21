"use strict";
// Run: node tests/js/orderbook_core.test.js  (node:test, no dependencies)
const test = require("node:test");
const assert = require("node:assert/strict");
const OB = require("../../src/dashboard/assets/orderbook_core.js");

function book(bids, asks) { const b = new OB.Book(); b.reset(bids, asks); return b; }

test("update sets, replaces and deletes levels", () => {
  const b = book([["100", "1"], ["99", "2"]], [["101", "1"]]);
  b.update([["100", "0"], ["98", "3"]], [["101", "5"]]);
  assert.equal(b.bestBid(), 99); assert.equal(b.asks.get(101), 5); assert.equal(b.bids.size, 2);
});

test("a crossing update removes the stale opposite levels", () => {
  const b = book([["100", "1"]], [["101", "1"], ["102", "1"]]);
  b.update([["101.5", "2"]], []);
  assert.ok(b.bestBid() < b.bestAsk()); assert.equal(b.bestAsk(), 102);
});

test("Binance sync: drops old events, requires continuity, resyncs on gap", () => {
  const b = new OB.Book(), s = new OB.BinanceSync(b);
  assert.equal(s.feed({ U: 8, u: 9, b: [["1", "1"]], a: [] }), "buffered");
  assert.equal(s.feed({ U: 10, u: 12, b: [["100", "1"]], a: [["101", "1"]] }), "buffered");
  assert.equal(s.feed({ U: 13, u: 14, b: [["100", "2"]], a: [] }), "buffered");
  assert.equal(s.snapshot({ lastUpdateId: 11, bids: [["99", "1"]], asks: [["102", "1"]] }), "ok");
  assert.equal(b.bids.get(100), 2); assert.equal(b.bids.has(1), false); assert.equal(s.last, 14);
  assert.equal(s.feed({ U: 10, u: 11, b: [], a: [] }), "ignored");
  assert.equal(s.feed({ U: 15, u: 15, b: [["100", "0"]], a: [] }), "ok");
  assert.equal(s.feed({ U: 17, u: 18, b: [], a: [] }), "resync");
});

test("Binance sync: first event after the snapshot must bridge lastUpdateId", () => {
  const b = new OB.Book(), s = new OB.BinanceSync(b);
  s.feed({ U: 50, u: 60, b: [], a: [] });
  assert.equal(s.snapshot({ lastUpdateId: 10, bids: [["1", "1"]], asks: [["2", "1"]] }), "resync");
});

test("depth curve is cumulative and limited to the range", () => {
  const b = book([["100", "1"], ["99", "2"], ["90", "5"]], [["101", "1"], ["102", "3"], ["120", "9"]]);
  const c = OB.depthCurve(b, 100.5, 0.05);
  assert.deepEqual(c.bids, [[100, 1], [99, 3]]); assert.deepEqual(c.asks, [[101, 1], [102, 4]]);
});

test("aggregate: bids round down, asks round up, quantities add", () => {
  assert.deepEqual(OB.aggregate([[100.4, 1], [100.9, 2], [99.1, 1]], 1, "bid"), [[100, 3], [99, 1]]);
  assert.deepEqual(OB.aggregate([[101.1, 1], [101.9, 2]], 1, "ask"), [[102, 3]]);
});

test("niceTick snaps to 1/2/5", () => { assert.equal(OB.niceTick(0.7), 0.5); assert.equal(OB.niceTick(1.2), 1); assert.equal(OB.niceTick(23), 20); assert.equal(OB.niceTick(0), 1); });

test("metrics: spread, microprice leans to the thin side, imbalance sign", () => {
  const b = book([["100", "9"], ["99", "9"]], [["101", "1"], ["102", "1"]]);
  const m = OB.metrics(b, 2);
  assert.equal(m.spread, 1); assert.equal(m.mid, 100.5);
  assert.ok(m.micro > m.mid, "thin ask -> micro price towards the ask");
  assert.ok(Math.abs(m.imbalance - 0.8) < 1e-9);
  assert.equal(OB.metrics(book([], []), 2), null);
});

test("heatmap keeps at most maxCols columns and only cells in range", () => {
  const b = book([["100", "1"], ["50", "9"]], [["101", "2"]]);
  const h = new OB.Heat(2, 1);
  for (let i = 0; i < 3; i++) h.push(b, 100.5, 0.02, i);
  assert.equal(h.cols.length, 2);
  assert.equal(h.cols[0].cells.size, 2); // 50 is outside +-2 %
  assert.ok(OB.intensity(h.cap(), h.cap()) <= 1); assert.equal(OB.intensity(0, 10), 0);
});
