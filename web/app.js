const token = '__TOKEN__';
let busy = false;
let lastMode = null;
let appExiting = false;
const $ = (id) => document.getElementById(id);
try {
  const saved = localStorage.getItem('qingji-calibration-enabled');
  if (saved !== null) $('calibrationEnabled').checked = saved === 'true';
} catch {}
$('calibrationEnabled').onchange = () => {
  try {
    localStorage.setItem(
      'qingji-calibration-enabled',
      String($('calibrationEnabled').checked),
    );
  } catch {}
};
window.calibrationRequested = () => $('calibrationEnabled').checked;
function render(s) {
  window.trajectoryPreviewState = s;
  const calibration = s.run?.calibration;
  $('calibrationStatus').textContent =
    s.run?.connected && calibration
      ? `${calibration.message} 来源：${calibration.file || 'data/calibration.json'}`
      : s.calibration_config?.message ||
        '尚未设置定位；开关在下次设置定位或开始跑步时生效。';
  $('calibrationStatus').className = s.calibration_config?.error
    ? 'hint error'
    : 'hint';
  const modes = {
    untouched: '尚未修改',
    simulating: '模拟中',
    cleared: '已清除模拟',
    unknown: '状态待确认',
  };
  $('mode').textContent = modes[s.mode] || '状态待确认';
  const target = s.target;
  s.mode === 'simulating' && target
    ? ($('position').textContent = target
        .map((n) => Number(n).toFixed(6))
        .join(', '))
    : ($('position').textContent =
        s.mode === 'unknown'
          ? '请在手机端确认位置'
          : s.mode === 'cleared'
            ? '已请求恢复真实定位'
            : '使用手机原有定位');
  $('positionNote').textContent =
    s.mode === 'simulating'
      ? s.run?.holding
        ? '持续保持当前位置中，恢复真实定位后停止。'
        : '正在持续更新模拟定位；这里显示地图目标坐标，并非手机回读坐标。'
      : s.mode === 'untouched'
        ? '本程序尚未发送定位修改指令。此处未读取或显示手机的真实坐标。'
        : '请打开手机地图确认实际位置。';
  $('deviceName').textContent = s.device ? s.device.name : '等待连接 iPhone';
  $('deviceInfo').textContent = s.device
    ? `${s.device.model} · iOS ${s.device.version}`
    : '使用数据线连接，解锁后信任此电脑';
  $('logs').textContent = s.logs.length ? s.logs.join('\n') : '暂无操作记录';
  if (window.syncSentPoint) window.syncSentPoint(s);
  if (window.renderPhone) window.renderPhone(s.phone, s);
  if (window.renderRunning) window.renderRunning(s.run);
}
async function action(name, data = {}) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach((b) => (b.disabled = true));
  $('notice').className = 'notice busy';
  $('notice').textContent =
    name === 'prepare'
      ? '正在准备设备，首次可能需要下载组件，请保持连接并等待…'
      : '正在与手机通信，请保持连接…';
  try {
    const res = await fetch('/api/' + name, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Local-Token': token },
      body: JSON.stringify(data),
    });
    const result = await res.json();
    if (res.ok && name === 'clear' && window.markLocationRestored)
      window.markLocationRestored();
    if (result.state) {
      render(result.state);
      lastMode = result.state.mode;
    }
    if (!res.ok) throw Error(result.error || '操作失败');
    $('notice').className = 'notice';
    $('notice').textContent =
      name === 'detect'
        ? '设备检测完成，未修改定位。'
        : name === 'prepare'
          ? '设备准备完成，可以输入经纬度测试。'
          : name === 'phone-start'
            ? '已开启 10 分钟接收窗口，请运行手机快捷指令。'
            : name === 'phone-stop'
              ? '已关闭手机位置接收，未修改手机定位。'
              : name === 'clear'
                ? '已发送恢复定位指令，旧标记已撤下。请确认手机地图已恢复，再运行一次快捷指令；收到新坐标后网页会自动居中。'
                : result.state.message;
  } catch (e) {
    $('notice').className = 'notice error';
    $('notice').textContent = e.message;
  } finally {
    busy = false;
    document.querySelectorAll('button').forEach((b) => (b.disabled = false));
    if (window.refreshRunControls) window.refreshRunControls();
  }
}
$('detect').onclick = () => action('detect');
$('prepare').onclick = () => action('prepare');
$('clear').onclick = () => action('clear');
$('locationForm').onsubmit = (e) => {
  e.preventDefault();
  action('set', {
    latitude: $('latitude').value,
    longitude: $('longitude').value,
    calibration_enabled: window.calibrationRequested(),
  });
};
async function refresh() {
  if (busy || appExiting) return;
  try {
    const res = await fetch('/api/status');
    if (!res.ok) throw Error();
    const s = await res.json();
    render(s);
    $('connection').textContent = '本机服务已连接';
    if (lastMode !== s.mode) {
      $('notice').className = s.mode === 'unknown' ? 'notice error' : 'notice';
      $('notice').textContent = s.message;
      lastMode = s.mode;
    }
  } catch (e) {
    $('connection').textContent = '本机服务已断开';
    $('notice').className = 'notice error';
    $('notice').textContent =
      '程序连接已断开，手机位置状态未确认。请重新启动程序，必要时恢复真实定位。';
    lastMode = null;
  }
}
refresh();
setInterval(refresh, 1000);
