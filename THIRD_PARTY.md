# 第三方组件

| 组件 | 版本 | 用途 | 上游 |
| --- | --- | --- | --- |
| Leaflet | 1.9.4 | 地图界面，源码内附 BSD-2-Clause 许可证 | https://leafletjs.com/ |
| pymobiledevice3 | 11.40.0 | iPhone USB／开发者服务连接，GPL-3.0-or-later | https://github.com/doronz88/pymobiledevice3 |
| qrcode | 8.2 | 本地二维码生成 | https://github.com/lincolnloop/python-qrcode |

Leaflet 文件位于 `vendor/leaflet/`，构建时验证固定摘要。其他 Python 组件通过 `requirements.txt` 安装，不将本机安装目录放入仓库。

OpenStreetMap 瓦片在线加载，界面保留来源标注；瓦片服务说明见 https://operations.osmfoundation.org/policies/tiles/ 。

各组件许可证文本及其依赖信息以上游发布内容为准。此文件是第三方来源清单。
