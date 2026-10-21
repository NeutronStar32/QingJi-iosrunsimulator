(() => {
  const map = window.qingjiMap,
    el = (id) => document.getElementById(id);
  if (!map) return;
  const layer = L.layerGroup().addTo(map);
  let editing = false,
    points = [],
    closed = false,
    selected = -1,
    id = null,
    saved = [],
    undo = [],
    redo = [];
  let mode = 'straight',
    track = null;
  const G = window.RouteGeometry;
  const geometry = () =>
    mode === 'track' && track
      ? G.track(track)
      : mode === 'smooth'
        ? G.smooth(points, closed)
        : points.map((p) => [...p]);
  const draftKey = 'qingji-route-draft-v3';
  const snapshot = () => ({
    points: points.map((p) => [...p]),
    closed,
    name: el('routeName').value,
    id,
    mode,
    track: track ? JSON.parse(JSON.stringify(track)) : null,
  });
  const exportRoute = () => ({
    ...snapshot(),
    points: geometry(),
    editor:
      mode === 'smooth'
        ? { mode, control_points: points.map((p) => [...p]) }
        : mode === 'track'
          ? { mode, track: JSON.parse(JSON.stringify(track)) }
          : undefined,
  });
  function persist() {
    try {
      localStorage.setItem(draftKey, JSON.stringify(snapshot()));
    } catch {
      message('草稿暂存失败，请使用“保存路线”。', true);
    }
  }
  function history() {
    undo.push(snapshot());
    if (undo.length > 100) undo.shift();
    redo = [];
  }
  function restore(s) {
    mode = s.editor?.mode || s.mode || 'straight';
    track = s.editor?.track || s.track || null;
    if (
      !['straight', 'smooth', 'track'].includes(mode) ||
      (mode === 'track' && !track)
    )
      mode = 'straight';
    points = (s.editor?.control_points || s.points).map((p) => [...p]);
    closed = s.closed;
    id = s.id || null;
    el('routeName').value = s.name || '';
    selected = -1;
    draw();
  }
  function message(text, error = false) {
    el('routeFeedback').textContent = text;
    el('routeFeedback').className = error ? 'hint error' : 'hint';
  }
  function length() {
    const p = geometry();
    let meters = 0;
    for (let i = 1; i < p.length; i++) meters += map.distance(p[i - 1], p[i]);
    if (closed && p.length > 2) meters += map.distance(p.at(-1), p[0]);
    return meters;
  }
  function draw() {
    window.dispatchEvent(new Event('qingji-route-change'));
    layer.clearLayers();
    el('routeShape').value = mode;
    el('trackSettings').hidden = mode !== 'track';
    el('routePointPanel').hidden = !editing || mode === 'track';
    if (track) {
      el('trackLength').value = track.length.toFixed(1);
      el('trackWidth').value = track.width.toFixed(1);
      el('trackAngle').value = track.angle.toFixed(1);
    }
    const preview = geometry();
    if (editing) {
      if (preview.length > 1) {
        const line = L.polyline(closed ? [...preview, preview[0]] : preview, {
          color: '#b4773e',
          weight: 4,
          bubblingMouseEvents: false,
        }).addTo(layer);
        line.on('click', (e) => {
          if (mode === 'track') return;
          const p = e.latlng.wrap();
          const click = map.latLngToLayerPoint(p);
          let best = 0,
            minimum = Infinity;
          const count = closed ? points.length : points.length - 1;
          for (let i = 0; i < count; i++) {
            const a = map.latLngToLayerPoint(points[i]),
              b = map.latLngToLayerPoint(points[(i + 1) % points.length]);
            const dx = b.x - a.x,
              dy = b.y - a.y,
              t = Math.max(
                0,
                Math.min(
                  1,
                  ((click.x - a.x) * dx + (click.y - a.y) * dy) /
                    (dx * dx + dy * dy || 1),
                ),
              );
            const d =
              (click.x - a.x - t * dx) ** 2 + (click.y - a.y - t * dy) ** 2;
            if (d < minimum) {
              minimum = d;
              best = i;
            }
          }
          if (points.length >= 2000)
            return message('最多支持 2000 个路线点。', true);
          history();
          points.splice(best + 1, 0, [
            Number(p.lat.toFixed(6)),
            Number(p.lng.toFixed(6)),
          ]);
          selected = best + 1;
          draw();
        });
      }
      if (mode === 'track' && track) {
        G.handles(track).forEach((p, index) => {
          const label = ['移动', '长／旋转', '宽'][index];
          const handle = L.marker(p, {
            draggable: true,
            bubblingMouseEvents: false,
            title: label,
            icon: L.divIcon({
              className: 'track-handle',
              html: `<span>${label}</span>`,
              iconSize: [72, 30],
              iconAnchor: [20, 15],
            }),
          }).addTo(layer);
          handle.on('dragstart', history);
          handle.on('dragend', () => {
            const q = handle.getLatLng().wrap();
            if (index === 0) track.center = [q.lat, q.lng];
            else {
              const [east, north] = G.frame(track.center).xy([q.lat, q.lng]);
              if (index === 1) {
                track.length = Math.max(
                  20,
                  track.width + 5,
                  Math.min(1000, 2 * Math.hypot(east, north)),
                );
                track.angle = (Math.atan2(east, north) * 180) / Math.PI;
              } else {
                const a = (track.angle * Math.PI) / 180;
                track.width = Math.max(
                  10,
                  Math.min(
                    500,
                    track.length - 5,
                    2 * Math.abs(east * Math.cos(a) - north * Math.sin(a)),
                  ),
                );
              }
            }
            draw();
          });
        });
      } else
        points.forEach((p, index) => {
          const marker = L.marker(p, {
            draggable: true,
            autoPan: true,
            bubblingMouseEvents: false,
            title: `路线点 ${index + 1}，可拖动`,
            alt: `路线点 ${index + 1}`,
            icon: L.divIcon({
              className:
                'route-marker' + (index === selected ? ' selected' : ''),
              html: `<span>${index + 1}</span>`,
              iconSize: [26, 26],
              iconAnchor: [13, 13],
            }),
          }).addTo(layer);
          marker.on('click', () => {
            selected = index;
            draw();
          });
          marker.on('dragstart', () => history());
          marker.on('dragend', () => {
            const p = marker.getLatLng().wrap();
            points[index] = [
              Number(p.lat.toFixed(6)),
              Number(p.lng.toFixed(6)),
            ];
            selected = index;
            draw();
          });
        });
    }
    const meters = length();
    el('routeStats').textContent =
      `${mode === 'track' ? '操场模板' : points.length + ' 个关键点' + (mode === 'smooth' ? ' · 平滑曲线' : '')} · ${meters >= 1000 ? (meters / 1000).toFixed(2) + ' 公里' : meters.toFixed(0) + ' 米'} · ${closed ? '已闭环（含首尾连接段）' : '未闭环'}`;
    el('routeClose').textContent = closed ? '取消闭环' : '首尾闭环';
    el('routeUndo').disabled = !undo.length;
    el('routeRedo').disabled = !redo.length;
    el('routePoints').replaceChildren(
      ...points.map((p, index) => {
        const row = document.createElement('li');
        row.className = index === selected ? 'selected' : '';
        const choose = document.createElement('button');
        choose.type = 'button';
        choose.textContent = `${index + 1}. ${p.map((n) => n.toFixed(6)).join(', ')}`;
        choose.onclick = () => {
          selected = index;
          draw();
          map.stop();
          map.panTo(p, { animate: false });
        };
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.textContent = '删除';
        remove.setAttribute('aria-label', `删除路线点 ${index + 1}`);
        remove.onclick = () => removePoint(index);
        row.append(choose, remove);
        return row;
      }),
    );
    persist();
  }
  function removePoint(index) {
    if (index < 0 || index >= points.length)
      return message('请先点击一个编号点。', true);
    history();
    points.splice(index, 1);
    if (points.length < 3) closed = false;
    selected = Math.min(index, points.length - 1);
    draw();
  }
  function setMode(value) {
    editing = value;
    el('routePanel').hidden = !value;
    el('routePointPanel').hidden = !value;
    el('routeMode').classList.toggle('active', value);
    el('singleMode').classList.toggle('active', !value);
    el('editorHelp').textContent = value
      ? '路线编辑只修改规划，不会向手机发送位置。'
      : '单点选位，点击“设置虚拟定位”后生效。';
    draw();
  }
  window.routeEditor = {
    isEditing: () => editing,
    addPoint(lat, lng) {
      if (mode === 'track')
        return message('请拖动模板手柄调整跑道；自由选点请切换路线方式。');
      if (points.length >= 2000)
        return message('最多支持 2000 个路线点。', true);
      history();
      points.push([Number(lat.toFixed(6)), Number(lng.toFixed(6))]);
      selected = points.length - 1;
      draw();
    },
    getDraft: () => exportRoute(),
  };
  el('singleMode').onclick = () => setMode(false);
  el('routeMode').onclick = () => setMode(true);
  el('routeUndo').onclick = () => {
    if (!undo.length) return;
    redo.push(snapshot());
    restore(undo.pop());
  };
  el('routeRedo').onclick = () => {
    if (!redo.length) return;
    undo.push(snapshot());
    restore(redo.pop());
  };
  el('routeClose').onclick = () => {
    if (mode === 'track') return message('操场模板始终闭环，无需连接首尾。');
    if (!closed && new Set(points.map((p) => p.join(','))).size < 3)
      return message('闭环至少需要 3 个不同位置。', true);
    history();
    closed = !closed;
    draw();
    message(closed ? '已闭环，请检查预览中的首尾连接段。' : '已取消首尾连接。');
  };
  el('routeDeletePoint').onclick = () =>
    mode === 'track'
      ? message('模板使用三个手柄调整，无需逐点删除。')
      : removePoint(selected);
  el('routeFit').onclick = () => {
    if (geometry().length) {
      map.stop();
      map.fitBounds(geometry(), {
        padding: [35, 35],
        maxZoom: 18,
        animate: false,
      });
    }
  };
  el('routeNew').onclick = () => {
    history();
    points = [];
    closed = false;
    mode = 'straight';
    track = null;
    id = null;
    selected = -1;
    el('routeName').value = '';
    draw();
    message('已新建空路线，上一份草稿可撤销找回。');
  };
  function makeTrack() {
    history();
    const c = map.getCenter().wrap();
    mode = 'track';
    track = { center: [c.lat, c.lng], length: 160, width: 80, angle: 0 };
    points = [];
    closed = true;
    id = null;
    selected = -1;
    if (!el('routeName').value) el('routeName').value = '操场跑道';
    draw();
    map.fitBounds(geometry(), {
      padding: [50, 50],
      maxZoom: 19,
      animate: false,
    });
    message('已生成跑道，拖动三个手柄，或输入尺寸与角度调整。');
  }
  el('routeTrackCreate').onclick = makeTrack;
  el('routeShape').onchange = () => {
    const next = el('routeShape').value;
    if (next === 'track') {
      makeTrack();
      return;
    }
    history();
    if (mode === 'track') {
      const p = geometry();
      points = Array.from(
        { length: 8 },
        (_, i) => p[Math.floor((i * p.length) / 8)],
      );
    }
    mode = next;
    track = null;
    draw();
    message(
      next === 'smooth'
        ? '已改用平滑曲线。曲线可能切入弯道内侧，请检查预览，必要时补充关键点。'
        : '已改用直线连接。',
    );
  };
  for (const key of ['Length', 'Width', 'Angle'])
    el('track' + key).onchange = () => {
      if (mode !== 'track') return;
      const length = Number(el('trackLength').value),
        width = Number(el('trackWidth').value),
        angle = Number(el('trackAngle').value);
      if (
        !Number.isFinite(length) ||
        !Number.isFinite(width) ||
        !Number.isFinite(angle) ||
        length < 20 ||
        length > 1000 ||
        width < 10 ||
        width > 500 ||
        width >= length ||
        Math.abs(angle) > 360
      ) {
        message(
          '长度 20～1000 米、宽度 10～500 米且小于长度、角度 -360～360 度。',
          true,
        );
        return;
      }
      history();
      track = { ...track, length, width, angle };
      draw();
    };
  el('routeName').addEventListener('input', persist);
  function renderSaved(records, select) {
    saved = records;
    el('savedRoutes').replaceChildren(
      new Option('选择已保存路线', ''),
      ...records.map((r) => new Option(r.name, r.id)),
    );
    if (select) el('savedRoutes').value = select;
  }
  async function request(path, data) {
    const response = await fetch('/api/' + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Local-Token': token },
      body: JSON.stringify(data),
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || '保存操作失败');
    return result;
  }
  el('routeSave').onclick = async () => {
    if (el('routeSave').disabled) return;
    el('routeSave').disabled = true;
    try {
      const result = await request('route-save', exportRoute());
      id = result.route.id;
      persist();
      renderSaved(result.routes, id);
      message(`已保存“${result.route.name}”，下次启动可加载。`);
    } catch (error) {
      message(error.message, true);
    } finally {
      el('routeSave').disabled = false;
    }
  };
  el('routeLoad').onclick = () => {
    const r = saved.find((r) => r.id === el('savedRoutes').value);
    if (!r) return message('请选择一条已保存路线。', true);
    history();
    restore(r);
    setMode(true);
    map.stop();
    map.fitBounds(geometry(), {
      padding: [35, 35],
      maxZoom: 18,
      animate: false,
    });
    message(`已加载“${r.name}”，未修改手机定位。`);
  };
  el('routeDelete').onclick = async () => {
    const chosen = el('savedRoutes').value;
    if (!chosen) return message('请选择要删除的已保存路线。', true);
    try {
      const result = await request('route-delete', { id: chosen });
      if (id === chosen) {
        id = null;
        persist();
      }
      renderSaved(result.routes);
      message('已删除保存记录，当前编辑草稿保留，可重新保存。');
    } catch (error) {
      message(error.message, true);
    }
  };
  try {
    const draft = JSON.parse(localStorage.getItem(draftKey));
    if (
      draft &&
      Array.isArray(draft.points) &&
      draft.points.length <= 2000 &&
      draft.points.every(
        (p) =>
          Array.isArray(p) &&
          p.length === 2 &&
          p.every(Number.isFinite) &&
          Math.abs(p[0]) <= 90 &&
          Math.abs(p[1]) <= 180,
      )
    )
      restore({ ...draft, closed: Boolean(draft.closed) });
  } catch {}
  fetch('/api/routes')
    .then((r) => {
      if (!r.ok) throw Error('路线服务尚未就绪，请重启新版程序。');
      return r.json();
    })
    .then((r) => renderSaved(r.routes, id))
    .catch((e) => message(e.message, true));
  draw();
})();
