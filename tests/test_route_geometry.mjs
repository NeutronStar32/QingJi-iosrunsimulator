import assert from 'node:assert/strict';
import '../web/route-geometry.js';
const G = globalThis.RouteGeometry;
const controls = [
  [30.0007, 120.00045],
  [30.0007, 119.99945],
  [29.9993, 119.99945],
  [29.9993, 120.00045],
];
const f = G.frame(controls[0]);
const dist = (a, b) => {
  const p = f.xy(a),
    q = f.xy(b);
  return Math.hypot(p[0] - q[0], p[1] - q[1]);
};
for (const closed of [false, true]) {
  const curve = G.smooth(controls, closed);
  assert(curve.length > controls.length && curve.length <= 2000);
  assert.deepEqual(curve[0], controls[0]);
  if (!closed) assert.deepEqual(curve.at(-1), controls.at(-1));
  for (const control of controls)
    assert(curve.some((p) => dist(p, control) < 1e-5));
  assert(curve.every((p) => p.every(Number.isFinite)));
  for (let i = 1; i < curve.length; i++)
    assert(dist(curve[i - 1], curve[i]) < 4);
  if (closed) assert(dist(curve.at(-1), curve[0]) < 4);
}
const shape = { center: [30, 120], length: 160, width: 80, angle: 0 };
const track = G.track(shape);
let length = 0;
for (let i = 0; i < track.length; i++)
  length += dist(track[i], track[(i + 1) % track.length]);
assert(Math.abs(length - (2 * (160 - 80) + Math.PI * 80)) < 0.1);
const h = G.handles(shape);
assert(Math.abs(dist(h[0], h[1]) - 80) < 0.01);
assert(Math.abs(dist(h[0], h[2]) - 40) < 0.01);
const rotated = G.track({ ...shape, angle: 90 });
assert.equal(track.length, rotated.length);
const large = G.smooth(
  Array.from({ length: 1000 }, (_, i) => [
    31 + i * 0.00001,
    121 + Math.sin(i) * 0.0001,
  ]),
  true,
);
assert(large.length <= 2000);
console.log(
  'PASS: smooth curves, closed seams, track dimensions, rotation and sample limits',
);
