import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import '../web/route-geometry.js';
import '../web/trajectory-variation.js';
const G = globalThis.RouteGeometry,
  V = globalThis.TrajectoryVariation;
const track = { center: [30, 120], length: 160, width: 80, angle: 17 };
const route = {
  points: G.track(track),
  closed: true,
  editor: { mode: 'track' },
};
const f = G.frame(track.center);
const distance = (a, b) => {
  a = f.xy(a);
  b = f.xy(b);
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
};
const a = V.generate(route, { seed: 23, laps: 4 });
assert.deepEqual(a, V.generate(route, { seed: 23, laps: 4 }));
assert.deepEqual(a.start, route.points[0]);
assert.equal(a.laps.length, 4);
for (let i = 0; i < a.laps.length; i++) {
  const lap = a.laps[i];
  assert(lap.points.every((p) => p.every(Number.isFinite)));
  for (let j = 1; j < lap.points.length; j++)
    assert(distance(lap.points[j - 1], lap.points[j]) < 2);
  if (i) assert(distance(a.laps[i - 1].points.at(-1), lap.points[0]) < 1e-6);
}
assert.notDeepEqual(a.laps[0].points, a.laps[1].points);
const anchor = a.laps[1].points[70];
const refreshed = V.generate(route, { seed: 72, anchor });
assert.deepEqual(refreshed.start, anchor);
assert.deepEqual(refreshed.laps[0].points[0], anchor);
assert(distance(refreshed.laps[0].points[1], anchor) < 2);
assert.notDeepEqual(
  refreshed.laps[0].points,
  V.generate(route, { seed: 73, anchor }).laps[0].points,
);
const zero = V.generate(route, { seed: 2, width: 0, laps: 1 });
assert(Math.abs(zero.distance - zero.baseLength) < 0.5);
assert.throws(() => V.generate(route, { laps: 11 }));
assert.throws(() => V.generate(route, { jitter: NaN }));
assert.throws(() => V.generate({ ...route, closed: false }));
assert.throws(() => V.generate(route, { anchor: [31, 120] }));
console.log(
  'PASS: seeded variation, lap continuity, fixed refresh anchor, no jumps, validation.',
);

// Compare browser preview coordinates to the actual Python playback generator.
const config = {
  seed: 23,
  laps: 4,
  jitter: 0.7,
  width: 3,
  lanes: 1,
  inside: true,
  anchor: null,
};
const python =
  process.env.QINGJI_PYTHON || path.resolve('.venv/Scripts/python.exe');
const native = JSON.parse(
  execFileSync(
    python,
    [
      '-c',
      'import sys,json; from qingji.trajectory import generate; d=json.load(sys.stdin); print(json.dumps(generate(d["route"],d["config"])))',
    ],
    {
      input: JSON.stringify({ route, config }),
      env: { ...process.env, PYTHONPATH: path.resolve('src') },
      windowsHide: true,
      maxBuffer: 8 * 1024 * 1024,
    },
  ).toString(),
);
for (let i = 0; i < native.length; i++) {
  assert.equal(native[i].length, a.laps[i].points.length);
  for (let j = 0; j < native[i].length; j++)
    assert(
      distance(native[i][j], a.laps[i].points[j]) < 0.0001,
      `Python/JS mismatch at ${i}:${j}`,
    );
}
console.log(
  'PASS: actual playback coordinates match browser preview within 0.1 mm.',
);
