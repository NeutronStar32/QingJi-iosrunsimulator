// Shared by the map preview and the route payload: no second interpolation on playback.
(() => {
  const meters = 111195,
    radians = Math.PI / 180;
  function frame(origin) {
    const longitude =
      meters * Math.max(0.01, Math.abs(Math.cos(origin[0] * radians)));
    return {
      xy: (p) => [
        (((p[1] - origin[1] + 540) % 360) - 180) * longitude,
        (p[0] - origin[0]) * meters,
      ],
      geo: (p) => [
        origin[0] + p[1] / meters,
        ((origin[1] + p[0] / longitude + 540) % 360) - 180,
      ],
    };
  }
  const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
  function smooth(points, closed) {
    if (points.length < 3) return points.map((p) => [...p]);
    const f = frame(points[0]),
      p = points.map(f.xy),
      segments = closed ? p.length : p.length - 1;
    const maxSteps = Math.max(
        1,
        Math.floor((2000 - (closed ? 0 : 1)) / segments),
      ),
      out = [];
    for (let i = 0; i < segments; i++) {
      const b = p[i],
        c = p[(i + 1) % p.length];
      const a = i
        ? p[i - 1]
        : closed
          ? p.at(-1)
          : b.map((v, k) => 2 * v - c[k]);
      const d =
        i + 2 < p.length
          ? p[i + 2]
          : closed
            ? p[(i + 2) % p.length]
            : c.map((v, k) => 2 * v - b[k]);
      const t0 = 0,
        t1 = Math.max(
          0.001,
          Math.sqrt(Math.hypot(...a.map((v, k) => v - b[k]))),
        );
      const t2 =
        t1 +
        Math.max(0.001, Math.sqrt(Math.hypot(...b.map((v, k) => v - c[k]))));
      const t3 =
        t2 +
        Math.max(0.001, Math.sqrt(Math.hypot(...c.map((v, k) => v - d[k]))));
      const steps = Math.min(
        maxSteps,
        Math.max(1, Math.ceil(Math.hypot(...b.map((v, k) => v - c[k])) / 2)),
      );
      for (let j = 0; j < steps; j++) {
        const t = t1 + ((t2 - t1) * j) / steps;
        const ab = mix(a, b, (t - t0) / (t1 - t0)),
          bc = mix(b, c, (t - t1) / (t2 - t1)),
          cd = mix(c, d, (t - t2) / (t3 - t2));
        out.push(
          f.geo(
            mix(
              mix(ab, bc, (t - t0) / (t2 - t0)),
              mix(bc, cd, (t - t1) / (t3 - t1)),
              (t - t1) / (t2 - t1),
            ),
          ),
        );
      }
    }
    if (!closed) out.push([...points.at(-1)]);
    out[0] = [...points[0]];
    return out;
  }
  function track(shape) {
    const f = frame(shape.center),
      angle = shape.angle * radians,
      r = shape.width / 2,
      half = (shape.length - shape.width) / 2;
    const geo = (x, y) =>
      f.geo([
        x * Math.cos(angle) + y * Math.sin(angle),
        -x * Math.sin(angle) + y * Math.cos(angle),
      ]);
    const out = [],
      lineSteps = Math.max(1, Math.ceil((2 * half) / 2)),
      arcSteps = Math.max(24, Math.ceil((Math.PI * r) / 2));
    for (let i = 0; i < lineSteps; i++)
      out.push(geo(r, -half + (2 * half * i) / lineSteps));
    for (let i = 0; i < arcSteps; i++) {
      const t = (Math.PI * i) / arcSteps;
      out.push(geo(r * Math.cos(t), half + r * Math.sin(t)));
    }
    for (let i = 0; i < lineSteps; i++)
      out.push(geo(-r, half - (2 * half * i) / lineSteps));
    for (let i = 0; i < arcSteps; i++) {
      const t = Math.PI + (Math.PI * i) / arcSteps;
      out.push(geo(r * Math.cos(t), -half + r * Math.sin(t)));
    }
    // The route API supports at most 2000 points.
    return out.length <= 2000
      ? out
      : Array.from(
          { length: 2000 },
          (_, i) => out[Math.floor((i * out.length) / 2000)],
        );
  }
  function handles(shape) {
    const f = frame(shape.center),
      a = shape.angle * radians;
    return [
      shape.center,
      f.geo([
        (Math.sin(a) * shape.length) / 2,
        (Math.cos(a) * shape.length) / 2,
      ]),
      f.geo([
        (Math.cos(a) * shape.width) / 2,
        (-Math.sin(a) * shape.width) / 2,
      ]),
    ];
  }
  globalThis.RouteGeometry = { smooth, track, handles, frame };
})();
