/* Selection is a draft: this module never calls a device API. */
(() => {
  const latInput = document.getElementById('latitude');
  const lngInput = document.getElementById('longitude');
  const hint = document.getElementById('selectionHint');
  const caption = document.getElementById('mapCaption');
  const tileStatus = document.getElementById('tileStatus');
  const retry = document.getElementById('retryMap');
  if (!window.L) {
    tileStatus.textContent = '地图组件加载失败，仍可使用经纬度输入。';
    return;
  }

  const map = L.map('map', {
    zoomControl: true,
    worldCopyJump: true,
    maxZoom: 19,
    minZoom: 2,
    attributionControl: true,
  }).setView([35, 105], 4);
  window.qingjiMap = map;
  L.control.scale({ imperial: false, position: 'bottomright' }).addTo(map);
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    updateWhenIdle: true,
    keepBuffer: 1,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
  });
  let marker = null,
    sentMarker = null,
    selected = null,
    sentKey = '',
    loaded = 0,
    failed = 0;
  let loadTimeout;
  function loading() {
    loaded = 0;
    failed = 0;
    tileStatus.textContent = '正在加载在线地图…';
    tileStatus.className = '';
    retry.hidden = true;
    clearTimeout(loadTimeout);
    loadTimeout = setTimeout(() => {
      tileStatus.textContent = '地图加载较慢，请检查网络或点击重新加载。';
      tileStatus.className = 'tile-error';
      retry.hidden = false;
    }, 15000);
  }
  tiles.on('loading', loading);
  tiles.on('tileload', () => {
    loaded++;
  });
  tiles.on('tileerror', () => {
    failed++;
  });
  tiles.on('load', () => {
    clearTimeout(loadTimeout);
    tileStatus.className = failed ? 'tile-error' : '';
    tileStatus.textContent = failed
      ? loaded
        ? '部分地图未加载，请检查网络后重试。'
        : '地图加载失败，请检查网络后重试。'
      : '在线地图 · WGS84';
    retry.hidden = !failed;
  });
  tiles.addTo(map);
  retry.onclick = () => {
    loading();
    tiles.redraw();
  };

  function readInputs() {
    if (!latInput.value.trim() || !lngInput.value.trim()) return null;
    const lat = Number(latInput.value),
      lng = Number(lngInput.value);
    return Number.isFinite(lat) &&
      Number.isFinite(lng) &&
      Math.abs(lat) <= 90 &&
      Math.abs(lng) <= 180
      ? [lat, lng]
      : null;
  }
  function clearDraft() {
    if (marker) map.removeLayer(marker);
    marker = null;
    selected = null;
    hint.textContent = '尚未选点 · 点击地图选择位置';
    caption.textContent = '地图浏览中 · 非手机当前位置';
  }
  function selectPoint(lat, lng, updateInputs = true) {
    selected = [Number(lat.toFixed(6)), Number(lng.toFixed(6))];
    if (updateInputs) {
      latInput.value = selected[0].toFixed(6);
      lngInput.value = selected[1].toFixed(6);
    }
    if (!marker) {
      marker = L.marker(selected, {
        draggable: true,
        autoPan: true,
        keyboard: true,
        title: '待设置目标，可拖动调整',
        alt: '待设置目标，可拖动调整',
        icon: L.divIcon({
          className: 'map-marker',
          html: '<span></span>',
          iconSize: [24, 24],
          iconAnchor: [12, 24],
        }),
      })
        .addTo(map)
        .bindTooltip('待设置目标 · 尚未发送', {
          direction: 'top',
          offset: [0, -24],
        });
      marker.on('dragend', () => {
        const p = marker.getLatLng().wrap();
        selectPoint(Math.max(-90, Math.min(90, p.lat)), p.lng);
      });
    } else marker.setLatLng(selected);
    hint.textContent = `已选目标：${selected[0].toFixed(6)}, ${selected[1].toFixed(6)} · 尚未发送`;
    caption.textContent = '待设置目标 · 点击「设置虚拟定位」后生效';
  }
  map.on('click', (event) => {
    const p = event.latlng.wrap();
    if (window.routeEditor?.isEditing()) {
      window.routeEditor.addPoint(Math.max(-90, Math.min(90, p.lat)), p.lng);
      return;
    }
    selectPoint(Math.max(-90, Math.min(90, p.lat)), p.lng);
  });
  function syncInput() {
    const p = readInputs();
    if (p) selectPoint(p[0], p[1], false);
    else clearDraft();
  }
  latInput.addEventListener('input', syncInput);
  lngInput.addEventListener('input', syncInput);
  document.getElementById('showCoordinates').onclick = () => {
    const p = readInputs();
    if (!p) {
      hint.textContent = '请先在地图选点，或完整输入有效经纬度。';
      latInput.focus();
      return;
    }
    selectPoint(p[0], p[1], false);
    map.stop();
    map.setView([Math.max(-85.051129, Math.min(85.051129, p[0])), p[1]], 16, {
      animate: false,
    });
  };
  document.getElementById('resetSelection').onclick = () => {
    latInput.value = '';
    lngInput.value = '';
    clearDraft();
    hint.textContent = '已清除待设置目标，未修改手机定位。';
  };
  document.getElementById('city').onchange = (event) => {
    if (!event.target.value) return;
    map.stop();
    map.setView(event.target.value.split(',').map(Number), 12, {
      animate: false,
    });
    caption.textContent = '城市浏览中 · 不修改选点或手机定位';
  };
  // A blue point describes the last successful command, never a GPS readback.
  window.syncSentPoint = (state) => {
    if (state.mode !== 'simulating' || !state.target) {
      if (sentMarker) map.removeLayer(sentMarker);
      sentMarker = null;
      sentKey = '';
      return;
    }
    const key = state.target.join(',');
    if (key === sentKey) return;
    sentKey = key;
    if (sentMarker) map.removeLayer(sentMarker);
    sentMarker = L.circleMarker(state.target, {
      radius: 9,
      color: '#fff',
      weight: 3,
      fillColor: '#4889b8',
      fillOpacity: 1,
    })
      .addTo(map)
      .bindTooltip('已发送位置 · 非手机回读', { direction: 'right' });
  };
  let reportedMarker = null,
    reported = null,
    reportKey = '';
  window.resetRestoredMap = () => {
    latInput.value = '';
    lngInput.value = '';
    clearDraft();
    if (sentMarker) map.removeLayer(sentMarker);
    sentMarker = null;
    sentKey = '';
    window.syncReportedPoint(null);
    caption.textContent = '已清除旧位置 · 等待手机重新上报后自动居中';
  };
  function centerReport() {
    if (!reported) {
      document.getElementById('phoneDetails').open = true;
      return;
    }
    map.stop();
    map.setView(
      [
        Math.max(-85.051129, Math.min(85.051129, reported.latitude)),
        reported.longitude,
      ],
      16,
      { animate: false },
    );
    caption.textContent = '手机上报位置 · 非持续实时跟踪';
  }
  document.getElementById('phoneCenter').onclick = centerReport;
  window.syncReportedPoint = (report) => {
    if (!report) {
      if (reportedMarker) map.removeLayer(reportedMarker);
      reportedMarker = null;
      reported = null;
      reportKey = '';
      return;
    }
    reported = report;
    const key = `${report.received_at}:${report.latitude}:${report.longitude}`;
    if (reportKey === key) return;
    reportKey = key;
    if (reportedMarker) map.removeLayer(reportedMarker);
    reportedMarker = L.circleMarker([report.latitude, report.longitude], {
      radius: 10,
      color: '#fff',
      weight: 3,
      fillColor: '#8a63ac',
      fillOpacity: 1,
      className: 'phone-reported-marker',
    })
      .addTo(map)
      .bindTooltip('手机上报位置 · 需运行快捷指令更新', { direction: 'right' });
    centerReport();
  };
})();
