# 开发与目录

```text
app.py                 源码启动入口
start.cmd              Windows 后台启动并打开浏览器
src/qingji/            后端模块
  app.py               HTTP 接口、操作调度、程序生命周期
  running.py           USB 定位流、跑步与持续保持
  motion.py            配速和轨迹变化
  route_store.py       路线验证与本地保存
  calibration.py       私有校准加载与坐标补偿
  phone_bridge.py      手机位置回传接收
  assets.py / paths.py  页面构建、资源路径
  device_cli.py        手机连接组件适配入口
web/                   HTML 模板、CSS、浏览器脚本
scripts/               页面构建和隔离预览工具
tests/                 Python、几何与浏览器测试
vendor/leaflet/         固定版本的地图组件及许可证
config/                不含个人数据的配置示例
docs/                  使用与开发说明
data/                  路线、私有配置和生成网页（忽略）
.local/                日志、历史调试资料和测试产物（忽略）
```

所有资源路径以项目位置解析，启动不依赖当前工作目录。仅修改前端后，运行 `python scripts/build_ui.py`，刷新页面即可；后端修改后须退出再启动。

## 单元与几何检查

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -q
node tests/test_route_geometry.mjs
```

Python 测试使用模拟 USB 会话；校准测试使用合成参数，不依赖个人配置。

## 隔离的浏览器检查

需安装 Microsoft Edge 和 Node.js 22 及以上。先在一个终端启动仅供测试的服务：

```powershell
.\.venv\Scripts\python.exe scripts/preview_server.py
```

另一个终端：

```powershell
$env:QINGJI_TEST_URL='http://127.0.0.1:8767'
node tests/test_map_browser.mjs
```

预览服务阻止所有手机操作，路线保存也使用隔离目录。测试结果写入 `.local/testing/`；测试浏览器关闭后清理自己的临时配置目录。可用 `QINGJI_BROWSER` 指定浏览器可执行文件。

## 格式与静态检查

随机轨迹的浏览器预览位于 `web/trajectory-variation.js`，实际播放生成器位于 `src/qingji/trajectory.py`。修改算法时需保持随机数调用顺序及计算一致，并运行 `npm run test:variation` 对照两端坐标（需已创建 Python 虚拟环境，可用 `QINGJI_PYTHON` 指定解释器）。后端按批续生成并只缓存少量批次的坐标，圈数、配速和里程按各圈实际生成路径统计。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
npm ci
.\.venv\Scripts\python.exe -m ruff check src tests scripts app.py
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts app.py
npm run format:check
```

上传源码不需要提交虚拟环境、依赖目录、生成网页或任何运行数据；`.gitignore` 已排除这些内容。第三方组件说明见根目录 `THIRD_PARTY.md`。
