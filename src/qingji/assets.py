"""Build the local web page from source and verified vendored Leaflet assets."""

import base64
import hashlib

from .paths import DATA_DIR, PROJECT_ROOT, WEB_DIR


def build_ui():
    root = PROJECT_ROOT
    vendor = root / "vendor" / "leaflet"
    expected = {
        "leaflet.js": "20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=",
        "leaflet.css": "p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=",
    }
    for name, digest in expected.items():
        actual = base64.b64encode(hashlib.sha256((vendor / name).read_bytes()).digest()).decode()
        if actual != digest:
            raise SystemExit(f"Leaflet integrity mismatch: {name}")
    page = (WEB_DIR / "ui.template.html").read_text(encoding="utf-8")
    for placeholder, source in {
        "__LEAFLET_STYLE__": vendor / "leaflet.css",
        "__LEAFLET_SCRIPT__": vendor / "leaflet.js",
        "__APP_STYLE__": WEB_DIR / "app.css",
        "__APP_SCRIPT__": WEB_DIR / "app.js",
        "__MAP_STYLE__": WEB_DIR / "map.css",
        "__MAP_SCRIPT__": WEB_DIR / "map-picker.js",
        "__PHONE_SCRIPT__": WEB_DIR / "phone-ui.js",
        "__ROUTE_SCRIPT__": WEB_DIR / "route-editor.js",
        "__GEOMETRY_SCRIPT__": WEB_DIR / "route-geometry.js",
        "__EXIT_SCRIPT__": WEB_DIR / "exit-ui.js",
        "__RUN_SCRIPT__": WEB_DIR / "run-ui.js",
        "__PREVIEW_SCRIPT__": WEB_DIR / "trajectory-preview.js",
        "__VARIATION_SCRIPT__": WEB_DIR / "trajectory-variation.js",
    }.items():
        page = page.replace(placeholder, source.read_text(encoding="utf-8"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "ui.html").write_text(page, encoding="utf-8")
    print("Built ui.html with verified Leaflet 1.9.4 assets.")
