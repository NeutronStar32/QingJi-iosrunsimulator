"""Validated local route storage. Files never contain phone pairing secrets."""

import json
import math
import re
import time
import uuid
from pathlib import Path


def validate_route(data):
    if not isinstance(data, dict):
        raise ValueError("路线格式无效。")
    name = data.get("name", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("路线名称需要 1～80 个字符。")
    points = data.get("points")
    closed = data.get("closed", False)
    if not isinstance(closed, bool) or not isinstance(points, list) or not 2 <= len(points) <= 2000:
        raise ValueError("路线需要 2～2000 个点，闭环需要至少 3 个不同位置。")
    clean = []
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("路线坐标格式无效。")
        if any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in point
        ):
            raise ValueError("路线坐标必须为有效数字。")
        if abs(point[0]) > 90 or abs(point[1]) > 180:
            raise ValueError("路线坐标超出范围。")
        clean.append(list(point))
    if len({tuple(p) for p in clean}) < (3 if closed else 2):
        raise ValueError("路线不同位置过少，闭环至少需要 3 个不同位置。")
    result = {"name": name.strip(), "points": clean, "closed": closed}
    editor = data.get("editor")
    if editor is not None:
        if not isinstance(editor, dict):
            raise ValueError("路线编辑信息无效。")
        if editor.get("mode") == "smooth":
            controls = validate_route(
                {"name": name, "points": editor.get("control_points"), "closed": closed}
            )
            result["editor"] = {"mode": "smooth", "control_points": controls["points"]}
        elif editor.get("mode") == "track":
            shape = editor.get("track")
            if not closed or not isinstance(shape, dict):
                raise ValueError("操场模板必须闭环。")
            center = shape.get("center")
            if (
                not isinstance(center, list)
                or len(center) != 2
                or any(
                    isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                    for v in center
                )
                or abs(center[0]) > 90
                or abs(center[1]) > 180
            ):
                raise ValueError("操场中心坐标无效。")
            for key, low, high in (("length", 20, 1000), ("width", 10, 500), ("angle", -360, 360)):
                value = shape.get(key)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or not low <= value <= high
                ):
                    raise ValueError("操场模板尺寸或角度无效。")
            if shape["width"] >= shape["length"]:
                raise ValueError("跑道宽度必须小于总长度。")
            result["editor"] = {
                "mode": "track",
                "track": {key: shape[key] for key in ("center", "length", "width", "angle")},
            }
        else:
            raise ValueError("路线编辑方式无效。")
    return result


class RouteStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _path(self, route_id):
        if not isinstance(route_id, str) or not re.fullmatch("[a-f0-9]{32}", route_id):
            raise ValueError("路线标识无效。")
        return self.directory / (route_id + ".json")

    def list(self):
        if not self.directory.exists():
            return []
        records = []
        for file in self.directory.glob("*.json"):
            try:
                route = json.loads(file.read_text(encoding="utf-8"))
                self._path(route["id"])
                route.update(validate_route(route))
                records.append(route)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(records, key=lambda r: r.get("updated_at", 0), reverse=True)

    def save(self, data):
        route = validate_route(data)
        route_id = data.get("id") or uuid.uuid4().hex
        file = self._path(route_id)
        route.update(id=route_id, updated_at=time.time())
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = file.with_suffix(".tmp")
        temporary.write_text(json.dumps(route, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(file)
        return route

    def delete(self, route_id):
        file = self._path(route_id)
        if not file.exists():
            raise ValueError("该路线已不存在，请刷新路线列表。")
        file.unlink()
