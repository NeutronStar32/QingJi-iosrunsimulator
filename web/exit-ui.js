(() => {
  const button = document.getElementById('exitApp');
  const status = document.getElementById('exitStatus');
  let exiting = false;
  async function exit(force = false) {
    if (exiting || busy) return;
    exiting = true;
    button.disabled = true;
    status.className = 'exit-status pending';
    status.textContent = '正在退出…';
    button.textContent = '退出中…';
    const notice = document.getElementById('notice');
    notice.className = 'notice busy';
    notice.textContent = '正在退出；若正在模拟定位，会先尝试恢复手机定位…';
    try {
      const response = await fetch('/api/shutdown', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Local-Token': token },
        body: JSON.stringify({ force }),
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.error || '退出失败');
      appExiting = true;
      status.className = 'exit-status success';
      status.textContent = '✓ 程序已退出';
      button.textContent = '已退出';
      document
        .querySelectorAll('button,input,select')
        .forEach((e) => (e.disabled = true));
      notice.className = 'notice';
      notice.textContent =
        '程序已退出，后台服务与手机回传已关闭。现在可以关闭这个浏览器标签页。';
      document.getElementById('connection').textContent = '程序已退出';
    } catch (error) {
      status.className = 'exit-status error';
      status.textContent = '退出失败，请重试或查看详情';
      button.textContent = '重试退出';
      notice.className = 'notice error';
      notice.textContent = `未退出：${error.message}\n可重新连接手机后重试。若需要直接关闭，请点击下方“仍然退出”，手机定位恢复状态将无法确认。`;
      if (!document.getElementById('forceExit')) {
        const forceButton = document.createElement('button');
        forceButton.id = 'forceExit';
        forceButton.className = 'quiet exit-button';
        forceButton.textContent = '仍然退出（手机位置未确认）';
        forceButton.onclick = () => exit(true);
        notice.after(forceButton);
      }
      exiting = false;
      button.disabled = false;
    }
  }
  button.onclick = () => exit(false);
})();
