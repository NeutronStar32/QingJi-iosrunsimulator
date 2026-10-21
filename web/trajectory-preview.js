(() => {
  const map = window.qingjiMap,
    el = (id) => document.getElementById(id);
  if (!map) return;
  const layer = L.layerGroup().addTo(map);
  let result = null,
    settings = null;
  const readSettings = () => ({
    laps: Number(el('previewLaps').value),
    jitter: Number(el('previewJitter').value),
    width: Number(el('previewWidth').value),
    lanes: Number(el('previewLanes').value),
    inside: el('previewInside').checked,
  });
  const feedback = (text) => {
    el('previewFeedback').textContent = text;
  };
  function clear() {
    layer.clearLayers();
    el('previewLegend').replaceChildren();
  }
  window.addEventListener('qingji-route-change', () => {
    clear();
    result = null;
    feedback('路线已调整，点击生成／刷新轨迹查看新预览。');
  });
  el('previewClear').onclick = () => {
    clear();
    feedback('已清除彩色轨迹；再次生成仍沿用当前起点。');
  };
  function generatePreview() {
    const state = window.trajectoryPreviewState;
    const current = state?.mode === 'simulating' ? state.target : null;
    const anchor = current || result?.start || null;
    const seed = crypto.getRandomValues(new Uint32Array(1))[0];
    const options = readSettings();
    const next = TrajectoryVariation.generate(window.routeEditor.getDraft(), {
      ...options,
      anchor,
      seed,
    });
    clear();
    result = next;
    settings = { ...options, seed, anchor: [...next.start] };
    for (const [index, lap] of result.laps.entries()) {
      L.polyline(lap.points, {
        color: lap.color,
        weight: 3,
        opacity: 0.85,
        interactive: false,
      }).addTo(layer);
      const item = document.createElement('span'),
        swatch = document.createElement('i');
      swatch.style.background = lap.color;
      item.append(swatch, `第 ${index + 1} 圈 · ${lap.distance.toFixed(1)} 米`);
      el('previewLegend').append(item);
    }
    L.circleMarker(result.start, {
      radius: 6,
      color: '#fff',
      weight: 2,
      fillColor: '#275e45',
      fillOpacity: 1,
    })
      .addTo(layer)
      .bindTooltip('本次预览起点');
    map.fitBounds(
      result.laps.flatMap((lap) => lap.points),
      { padding: [30, 30], maxZoom: 20, animate: false },
    );
    feedback(
      `已生成 ${result.laps.length} 圈，共 ${result.distance.toFixed(1)} 米。${current ? '从当前模拟位置开始' : anchor ? '沿用上次预览起点' : '从路线起点开始'}；刷新只改变后续轨迹。启用“随机变道轨迹”后，开始跑步将沿用此预览。正在进行的任务保持原轨迹。`,
    );
  }
  el('previewRefresh').onclick = () => {
    try {
      generatePreview();
    } catch (error) {
      feedback(error.message);
    }
  };
  window.trajectoryPreview = {
    snapshot: () => result,
    runConfig() {
      const current = readSettings();
      if (
        !result ||
        Object.keys(current).some((key) => current[key] !== settings[key])
      )
        generatePreview();
      return structuredClone(settings);
    },
  };
})();
