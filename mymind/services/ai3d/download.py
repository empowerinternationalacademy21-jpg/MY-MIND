"""Safe download of a provider's result file: HTTPS only, host allow-list, no redirects, hard size cap, GLB check."""
from urllib.parse import urlparse
import requests
from flask import current_app
from services.ai3d import glb


class DownloadError(Exception):
    pass


def host_allowed(host, allowed):
    host = (host or "").lower().rstrip(".")
    for a in allowed:
        a = a.lower().strip()
        if not a:
            continue
        if a.startswith("."):
            if host.endswith(a) and len(host) > len(a):
                return True
        elif host == a:
            return True
    return False


def fetch_glb(url):
    cfg = current_app.config
    p = urlparse(url or "")
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise DownloadError("The provider returned a model link that is not a plain HTTPS link.")
    if not host_allowed(p.hostname, cfg["AI3D_DOWNLOAD_HOSTS"]):
        raise DownloadError(f"The model link points to a host that is not allowed ({p.hostname}). Add it to AI3D_DOWNLOAD_HOSTS only if you trust it.")
    limit = cfg["AI3D_MAX_DOWNLOAD_BYTES"]
    try:
        with requests.get(url, stream=True, timeout=(10, 60), allow_redirects=False) as r:
            if r.status_code != 200:
                raise DownloadError(f"Downloading the model failed (HTTP {r.status_code}).")
            if int(r.headers.get("Content-Length") or 0) > limit:
                raise DownloadError("The model file is larger than the allowed size.")
            buf = bytearray()
            for chunk in r.iter_content(65536):
                buf += chunk
                if len(buf) > limit:
                    raise DownloadError("The model file is larger than the allowed size.")
    except requests.RequestException as exc:
        raise DownloadError(f"Downloading the model failed ({type(exc).__name__}).")
    data = bytes(buf)
    try:
        glb.parse(data)
    except glb.GlbError as exc:
        raise DownloadError(str(exc))
    return data
