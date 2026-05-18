import json
import math
import os
import random
from pathlib import Path
from typing import Dict, Tuple, Optional

import execjs


_JS_LOCKED = False
_JS_RUNTIME: Optional[execjs.ExternalRuntime] = None
_XRAY_RUNTIME: Optional[execjs.ExternalRuntime] = None


def _load_js_runtime() -> Tuple[Optional[execjs.ExternalRuntime], Optional[execjs.ExternalRuntime]]:
    global _JS_LOCKED, _JS_RUNTIME, _XRAY_RUNTIME
    if _JS_LOCKED:
        return _JS_RUNTIME, _XRAY_RUNTIME
    _JS_LOCKED = True

    base_dir = Path(__file__).resolve().parent / "xhs_static"
    xs_path = base_dir / "xhs_xs_xsc_56.js"
    xray_path = base_dir / "xhs_xray.js"
    node_modules = str(base_dir / "node_modules")
    if os.path.isdir(node_modules):
        current = os.environ.get("NODE_PATH", "")
        if node_modules not in current.split(os.pathsep):
            os.environ["NODE_PATH"] = os.pathsep.join([p for p in [node_modules, current] if p])

    try:
        _JS_RUNTIME = execjs.compile(xs_path.read_text(encoding="utf-8"))
    except Exception:
        _JS_RUNTIME = None

    try:
        _XRAY_RUNTIME = execjs.compile(xray_path.read_text(encoding="utf-8"))
    except Exception:
        _XRAY_RUNTIME = None

    return _JS_RUNTIME, _XRAY_RUNTIME


def _generate_x_b3_traceid(length: int = 16) -> str:
    x_b3_traceid = ""
    for _ in range(length):
        x_b3_traceid += "abcdef0123456789"[math.floor(16 * random.random())]
    return x_b3_traceid


def _generate_xray_traceid() -> str:
    _, xray_runtime = _load_js_runtime()
    if xray_runtime:
        try:
            return xray_runtime.call("traceId")
        except Exception:
            pass
    return _generate_x_b3_traceid(32)


def _get_request_headers_template() -> Dict[str, str]:
    return {
        "authority": "edith.xiaohongshu.com",
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "cache-control": "no-cache",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.xiaohongshu.com",
        "pragma": "no-cache",
        "referer": "https://www.xiaohongshu.com/",
        "sec-ch-ua": "\"Not A(Brand\";v=\"99\", \"Microsoft Edge\";v=\"121\", \"Chromium\";v=\"121\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
        "x-b3-traceid": "",
        "x-mns": "unload",
        "x-s": "",
        "x-s-common": "",
        "x-t": "",
        "x-xray-traceid": _generate_xray_traceid(),
    }


def _trans_cookies(cookies_str: str) -> Dict[str, str]:
    if "; " in cookies_str:
        pairs = cookies_str.split("; ")
    else:
        pairs = cookies_str.split(";")
    return {i.split("=")[0]: "=".join(i.split("=")[1:]) for i in pairs if "=" in i}


def _generate_headers(a1: str, api: str, data: str = "", method: str = "POST") -> Tuple[Dict[str, str], str]:
    runtime, _ = _load_js_runtime()
    if not runtime:
        raise RuntimeError("xhs_xs_xsc_56.js 未加载，无法生成签名")

    ret = runtime.call("get_request_headers_params", api, data, a1, method)
    xs = ret["xs"]
    xt = ret["xt"]
    xs_common = ret["xs_common"]

    x_b3_traceid = _generate_x_b3_traceid()
    headers = _get_request_headers_template()
    headers["x-s"] = xs
    headers["x-t"] = str(xt)
    headers["x-s-common"] = xs_common
    headers["x-b3-traceid"] = x_b3_traceid

    if data:
        data = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return headers, data


def splice_str(api: str, params: Dict[str, str]) -> str:
    url = api + "?"
    for key, value in params.items():
        url += f"{key}={value}&"
    return url[:-1]


def generate_request_params(
    cookies_str: str,
    api: str,
    data: str = "",
    method: str = "POST",
) -> Tuple[Dict[str, str], Dict[str, str], str]:
    cookies = _trans_cookies(cookies_str)
    a1 = cookies.get("a1") or ""
    headers, data = _generate_headers(a1, api, data, method)
    return headers, cookies, data
