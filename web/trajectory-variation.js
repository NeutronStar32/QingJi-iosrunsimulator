// Experimental geometry only. No device commands or changes to route storage.
(() => {
  const G = globalThis.RouteGeometry;
  const ease = (t) => {
    t = Math.max(0, Math.min(1, t));
    return t * t * (3 - 2 * t);
  };
  function generate(route, options = {}) {
    const {
      laps = 3,
      jitter = 0.7,
      width = 3,
      lanes = 1,
      inside = true,
      seed = 1,
      anchor = null,
    } = options;
    if (!route.closed || route.points.length < 3)
      throw Error('请先准备一条闭环路线。');
    if (
      !Number.isInteger(laps) ||
      laps < 1 ||
      laps > 10 ||
      !Number.isFinite(jitter) ||
      jitter < 0 ||
      jitter > 2 ||
      !Number.isFinite(width) ||
      width < 0 ||
      width > 6 ||
      ![0, 1, 2].includes(lanes)
    )
      throw Error('请检查圈数及偏移参数的范围。');
    if (
      anchor &&
      (!Array.isArray(anchor) ||
        anchor.length !== 2 ||
        !anchor.every(Number.isFinite))
    )
      throw Error('预览起点无效。');
    const frame = G.frame(route.points[0]);
    const p = route.points.map(frame.xy);
    let rng = seed >>> 0;
    const random = () => {
      rng = (rng + 0x6d2b79f5) >>> 0;
      let t = Math.imul(rng ^ (rng >>> 15), 1 | rng);
      t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    const segments = [],
      ends = [];
    let length = 0;
    p.forEach((a, i) => {
      const b = p[(i + 1) % p.length],
        dx = b[0] - a[0],
        dy = b[1] - a[1];
      const size = Math.hypot(dx, dy);
      if (size < 1e-6) return;
      segments.push({ a, dx, dy, size, start: length });
      length += size;
      ends.push(length);
    });
    if (length < 10 || length > 50000)
      throw Error('随机轨迹支持每圈 10 米～50 公里。');
    function at(s) {
      s = ((s % length) + length) % length;
      let lo = 0,
        hi = ends.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (s < ends[mid]) hi = mid;
        else lo = mid + 1;
      }
      const q = segments[lo],
        t = (s - q.start) / q.size;
      return [q.a[0] + q.dx * t, q.a[1] + q.dy * t];
    }
    const origin = anchor ? frame.xy(anchor) : p[0];
    let start = 0,
      closest = Infinity;
    for (const q of segments) {
      const t = Math.max(
        0,
        Math.min(
          1,
          ((origin[0] - q.a[0]) * q.dx + (origin[1] - q.a[1]) * q.dy) /
            q.size ** 2,
        ),
      );
      const d = Math.hypot(
        origin[0] - q.a[0] - q.dx * t,
        origin[1] - q.a[1] - q.dy * t,
      );
      if (d < closest) {
        closest = d;
        start = q.start + q.size * t;
      }
    }
    if (closest > 25)
      throw Error('当前位置距路线超过 25 米，请调整路线或恢复定位后再预览。');
    const total = length * laps;
    // Random control values at several spatial scales; no repeating sine waves.
    function noise(spacing) {
      const values = Array.from(
        { length: Math.ceil(total / spacing) + 2 },
        () => random() * 2 - 1,
      );
      return (s) => {
        const i = Math.floor(s / spacing),
          t = ease(s / spacing - i);
        return values[i] + (values[i + 1] - values[i]) * t;
      };
    }
    const fine = noise(3.5),
      medium = noise(11),
      drift = noise(38);
    const events = [];
    if (lanes) {
      for (
        let s = 15 + random() * 30;
        s < total;
        s += (45 + random() * 70) / lanes
      )
        events.push({
          start: s,
          ramp: 9 + random() * 10,
          hold: 10 + random() * 25,
          amount: (random() * 2 - 1) * width,
        });
    }
    const baseStart = at(start),
      correction = origin.map((v, i) => v - baseStart[i]);
    const colors = [
      '#246bb0',
      '#df7733',
      '#8e53a4',
      '#21966d',
      '#cf5277',
      '#9b822c',
      '#4a91a4',
      '#80574b',
      '#5b67bd',
      '#798d36',
    ];
    const result = [];
    let previous = null,
      distance = 0;
    const step = Math.max(0.8, total / 30000);
    for (let lap = 0; lap < laps; lap++) {
      const points = [],
        count = Math.ceil(length / step),
        before = distance;
      for (let j = 0; j <= count; j++) {
        const s = lap * length + (j * length) / count,
          q = at(start + s);
        const a = at(start + s - 3),
          b = at(start + s + 3);
        const dx = b[0] - a[0],
          dy = b[1] - a[1],
          norm = Math.hypot(dx, dy) || 1;
        let lateral =
          jitter * (0.7 * fine(s) + 0.3 * medium(s)) + width * 0.25 * drift(s);
        for (const e of events) {
          const t = s - e.start;
          if (t >= 0 && t <= 2 * e.ramp + e.hold)
            lateral +=
              e.amount *
              ease(t / e.ramp) *
              (1 - ease((t - e.ramp - e.hold) / e.ramp));
        }
        if (inside && route.editor?.mode === 'track') {
          const turn =
            (q[0] - a[0]) * (b[1] - q[1]) - (q[1] - a[1]) * (b[0] - q[0]);
          const curvature =
            turn /
            Math.max(
              1e-6,
              Math.hypot(q[0] - a[0], q[1] - a[1]) *
                Math.hypot(b[0] - q[0], b[1] - q[1]),
            );
          lateral +=
            Math.max(-1, Math.min(1, curvature * 15)) *
            width *
            0.3 *
            (0.65 + 0.35 * medium(s));
        }
        lateral = width ? width * Math.tanh(lateral / width) * ease(s / 15) : 0;
        const fade = 1 - ease(s / 25);
        const xy = [
          q[0] - (dy / norm) * lateral + correction[0] * fade,
          q[1] + (dx / norm) * lateral + correction[1] * fade,
        ];
        if (previous)
          distance += Math.hypot(xy[0] - previous[0], xy[1] - previous[1]);
        previous = xy;
        points.push(frame.geo(xy));
      }
      result.push({ points, color: colors[lap], distance: distance - before });
    }
    // Preserve exact coordinates rather than a projection round-trip.
    result[0].points[0] = [...(anchor || route.points[0])];
    return {
      laps: result,
      start: result[0].points[0],
      baseLength: length,
      distance,
      seed,
    };
  }
  globalThis.TrajectoryVariation = { generate };
})();
