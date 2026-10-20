(() => {
  let qrKey = '',
    lastAddress = null,
    lastPhone = null;
  const restoreKey = 'qingji-restored-' + token;
  let restoredAt = 0,
    previousMode = null;
  try {
    restoredAt = Number(localStorage.getItem(restoreKey)) || 0;
  } catch {}
  const el = (id) => document.getElementById(id);
  window.markLocationRestored = () => {
    restoredAt = Date.now() / 1000;
    try {
      localStorage.setItem(restoreKey, String(restoredAt));
    } catch {}
    if (window.resetRestoredMap) window.resetRestoredMap();
  };
  window.addEventListener('storage', (event) => {
    if (event.key === restoreKey) {
      restoredAt = Number(event.newValue) || 0;
      if (window.resetRestoredMap) window.resetRestoredMap();
    }
  });
  window.renderPhone = (phone, state = {}) => {
    if (!phone) {
      el('phoneStatus').textContent = '请重新启动新版程序以启用手机回传。';
      return;
    }
    // Also discard a simulated snapshot when opening an already-restored session.
    const staleSimulated =
      state.mode === 'cleared' &&
      ['simulating', 'unknown'].includes(phone.report?.mode_at_receive);
    if (
      state.mode === 'cleared' &&
      (previousMode === 'simulating' ||
        previousMode === 'unknown' ||
        staleSimulated) &&
      !restoredAt
    )
      window.markLocationRestored();
    previousMode = state.mode || previousMode;
    lastPhone = phone;
    const options =
      phone.network_options ||
      (phone.addresses || []).map((address) => ({ address, label: address }));
    const choices = options.map((o) => o.address);
    const current = el('phoneAddress').value;
    if (
      Array.from(el('phoneAddress').options)
        .map((o) => o.value)
        .join(',') !== choices.join(',')
    ) {
      el('phoneAddress').replaceChildren(
        ...options.map((o) => new Option(o.label, o.address)),
      );
      if (choices.includes(current)) el('phoneAddress').value = current;
      else if (choices.includes(phone.address))
        el('phoneAddress').value = phone.address;
      else if (options.some((o) => o.preferred))
        el('phoneAddress').value = options.find((o) => o.preferred).address;
    }
    if (phone.active && phone.address !== lastAddress)
      el('phoneAddress').value = phone.address;
    lastAddress = phone.address;
    el('phoneStatus').textContent = phone.network_changed
      ? '电脑网络已变化，旧二维码已不可用。请选择当前 Wi-Fi 地址，重新开启接收并扫码。'
      : !choices.length
        ? '未发现可用局域网地址，请连接 Wi-Fi／有线网络。'
        : phone.active
          ? `接收地址 ${phone.address} · 剩余 ${Math.ceil(phone.remaining_seconds / 60)} 分钟`
          : '接收未开启或已过期，点击“开启／延长接收”。';
    el('phonePairing').hidden = !phone.active;
    if (phone.active) {
      el('phoneEndpoint').value = phone.endpoint;
      el('phoneGuide').href = phone.guide_url;
      if (qrKey !== phone.endpoint) {
        el('phoneQr').src = '/api/phone-qr';
        el('phoneEndpointQr').src = '/api/phone-qr?kind=endpoint';
        qrKey = phone.endpoint;
      }
    } else {
      qrKey = '';
      el('phoneQr').removeAttribute('src');
      el('phoneEndpointQr').removeAttribute('src');
    }
    const r =
      phone.report && phone.report.received_at > restoredAt && !staleSimulated
        ? phone.report
        : null;
    if (r) {
      const date = new Date(r.received_at * 1000).toLocaleString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        hour12: false,
      });
      const age = Math.floor((Date.now() / 1000 - r.received_at) / 60);
      el('phoneReport').textContent =
        `手机上报：${r.latitude.toFixed(6)}, ${r.longitude.toFixed(6)} · 收到于 ${date}${age >= 2 ? ` · 已过 ${age} 分钟，请重新运行快捷指令更新` : ''}${['simulating', 'unknown'].includes(r.mode_at_receive) ? ' · 上报时处于模拟或未确认状态，可能为模拟位置' : ''}`;
    } else
      el('phoneReport').textContent = restoredAt
        ? '旧位置已撤下，等待手机重新上报。请确认手机地图已恢复，再运行一次“轻迹当前位置”；收到新坐标后自动居中。'
        : '尚未收到手机位置。请开启接收，并运行手机上的“轻迹当前位置”快捷指令。';
    if (window.syncReportedPoint) window.syncReportedPoint(r);
  };
  el('phoneSetup').onclick = () => {
    el('phoneDetails').open = true;
    el('phoneDetails').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };
  el('phoneStart').onclick = async () => {
    const address = el('phoneAddress').value;
    if (lastPhone?.address && lastPhone.address !== address)
      await action('phone-stop');
    await action('phone-start', { address });
  };
  el('phoneStop').onclick = () => action('phone-stop');
  el('phoneCopy').onclick = async () => {
    try {
      await navigator.clipboard.writeText(el('phoneEndpoint').value);
      el('phoneCopy').textContent = '已复制';
    } catch {
      el('phoneEndpoint').focus();
      el('phoneEndpoint').select();
      el('phoneCopy').textContent = '请复制已选中地址';
    }
  };
})();
