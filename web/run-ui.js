(() => {
  const el = (id) => document.getElementById(id);
  let last = null,
    line = null,
    routeKey = '';
  const states = {
    idle: '未开始',
    holding: '单点保持中',
    running: '跑步中',
    paused: '休息中',
    stopped: '已结束',
    completed: '已完成',
    error: '连接异常',
  };
  const clock = (value) => {
    const s = Math.floor(value || 0);
    return (
      (s >= 3600 ? String(Math.floor(s / 3600)).padStart(2, '0') + ':' : '') +
      String(Math.floor(s / 60) % 60).padStart(2, '0') +
      ':' +
      String(s % 60).padStart(2, '0')
    );
  };
  const pace = (value) => {
    if (!value) return '—';
    const seconds = Math.round(value);
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')} / 公里`;
  };
  function controls() {
    const active = last && ['running', 'paused'].includes(last.status);
    el('runStart').disabled = Boolean(active);
    el('runPause').disabled = !active;
    el('runStop').disabled = !active;
    el('runPause').textContent =
      last?.status === 'paused' ? '继续跑步' : '暂停休息';
    el('paceMin').disabled = Boolean(active);
    el('paceSec').disabled = Boolean(active);
    el('runInfinite').disabled = Boolean(active);
    el('runLaps').disabled = Boolean(active) || el('runInfinite').checked;
    for (const id of [
      'paceVariationEnabled',
      'paceVariation',
      'trajectoryOffsetEnabled',
      'trajectoryOffset',
    ])
      el(id).disabled = Boolean(active);
  }
  window.refreshRunControls = controls;
  window.renderRunning = (state) => {
    if (!state) {
      el('runMessage').textContent = '跑步服务需要重启新版程序后启用。';
      return;
    }
    last = state;
    el('runBadge').textContent = states[state.status] || '状态待确认';
    el('runDistance').textContent =
      state.distance_m >= 1000
        ? (state.distance_m / 1000).toFixed(2) + ' 公里'
        : state.distance_m.toFixed(1) + ' 米';
    el('runTime').textContent = clock(state.moving_seconds);
    el('runLap').textContent = state.route
      ? `${state.current_lap} / ${state.laps || '∞'} 圈 · 已完成 ${state.completed_laps} 圈`
      : '—';
    el('runPace').textContent = pace(
      state.current_pace_seconds || state.pace_seconds,
    );
    el('runPaceDetail').textContent = state.pace_seconds
      ? `基准 ${pace(state.pace_seconds)} · 本圈目标 ${pace(state.lap_pace_seconds || state.pace_seconds)} · 轨迹偏移 ${state.trajectory_offset_m || 0} 米`
      : '开始后显示基准与本圈目标配速。';
    el('runMessage').textContent = state.message;
    el('runMessage').className =
      state.status === 'error' ? 'hint error' : 'hint';
    const key = state.route ? JSON.stringify(state.route) : '';
    if (key !== routeKey) {
      routeKey = key;
      if (line) window.qingjiMap.removeLayer(line);
      line = null;
      if (state.route) {
        const p = state.route.points;
        line = L.polyline(state.route.closed ? [...p, p[0]] : p, {
          color: '#4889b8',
          weight: 7,
          opacity: 0.35,
          interactive: false,
        }).addTo(window.qingjiMap);
      }
    }
    if (!busy && !appExiting) controls();
  };
  el('runInfinite').onchange = controls;
  async function command(name, data = {}) {
    if (busy || appExiting) return;
    busy = true;
    document.querySelectorAll('button').forEach((b) => (b.disabled = true));
    el('runMessage').textContent =
      name === 'run-start'
        ? '正在连接手机并设置到路线起点，请保持解锁和 USB 连接…'
        : '正在执行跑步操作…';
    try {
      const response = await fetch('/api/' + name, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Local-Token': token },
        body: JSON.stringify(data),
      });
      const result = await response.json();
      if (result.state) render(result.state);
      if (!response.ok) throw Error(result.error || '跑步操作失败');
      el('notice').className = 'notice';
      el('notice').textContent = result.state.run.message;
    } catch (error) {
      el('runMessage').className = 'hint error';
      el('runMessage').textContent = error.message;
      el('notice').className = 'notice error';
      el('notice').textContent = error.message;
    } finally {
      busy = false;
      document.querySelectorAll('button').forEach((b) => (b.disabled = false));
      controls();
    }
  }
  el('runStart').onclick = () => {
    const minutes = Number(el('paceMin').value),
      seconds = Number(el('paceSec').value),
      laps = el('runInfinite').checked ? 0 : Number(el('runLaps').value);
    if (
      !el('paceMin').value ||
      !el('paceSec').value ||
      !Number.isInteger(minutes) ||
      !Number.isInteger(seconds) ||
      minutes < 1 ||
      minutes > 30 ||
      seconds < 0 ||
      seconds > 59 ||
      minutes * 60 + seconds > 1800 ||
      !Number.isInteger(laps) ||
      laps < 0
    ) {
      el('runMessage').textContent = '请输入有效配速（1:00～30:00）和圈数。';
      return;
    }
    const variation = el('paceVariationEnabled').checked
      ? Number(el('paceVariation').value)
      : 0;
    const offset = el('trajectoryOffsetEnabled').checked
      ? Number(el('trajectoryOffset').value)
      : 0;
    if (
      !Number.isFinite(variation) ||
      variation < 0 ||
      variation > 120 ||
      !Number.isFinite(offset) ||
      offset < 0 ||
      offset > 3
    ) {
      el('runMessage').textContent =
        '配速浮动范围为 0～120 秒／公里，轨迹偏移范围为 0～3 米。';
      return;
    }
    command('run-start', {
      route: window.routeEditor?.getDraft(),
      pace_seconds: minutes * 60 + seconds,
      laps,
      calibration_enabled: window.calibrationRequested(),
      pace_variation_seconds: variation,
      trajectory_offset_m: offset,
    });
  };
  el('runPause').onclick = () =>
    command(last?.status === 'paused' ? 'run-resume' : 'run-pause');
  el('runStop').onclick = () => command('run-stop');
  el('runFit').onclick = () => {
    if (last?.route) {
      window.qingjiMap.stop();
      window.qingjiMap.fitBounds(last.route.points, {
        padding: [40, 40],
        maxZoom: 18,
        animate: false,
      });
    } else el('runMessage').textContent = '开始跑步后可查看本次固定路线。';
  };
  controls();
})();
