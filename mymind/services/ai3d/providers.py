"""Thin REST clients for the 3D and concept-image providers.

IMPORTANT: request/response shapes follow each provider's published REST documentation as understood when this was written. They were
exercised only against mocks (the build environment has no provider keys or network access to them), so run ONE test job per provider
and read the error text on the admin page before relying on a provider. Keys come from config (server-side only) and are never logged,
stored in the database, or included in error messages shown to anyone.
"""
import base64
import io
from dataclasses import dataclass, field
import requests
from flask import current_app
from PIL import Image

TIMEOUT = (10, 60)


class ProviderError(Exception):
    """A provider call failed. The message is safe to show to an administrator (no keys, no raw bodies)."""


@dataclass
class Result:
    status: str                      # pending | running | success | failed
    progress: int = 0
    urls: dict = field(default_factory=dict)
    error: str = ""


def _cfg(name, default=""):
    return current_app.config.get(name, default)


def _safe_err(resp):
    try:
        body = resp.json()
        msg = body.get("message") or body.get("error") or (body.get("data") or {}).get("message") or body.get("detail") or ""
        if isinstance(msg, dict):
            msg = msg.get("message", "")
    except ValueError:
        msg = ""
    return f"HTTP {resp.status_code}" + (f": {str(msg)[:160]}" if msg else "")


def _call(method, url, headers, **kw):
    try:
        resp = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kw)
    except requests.RequestException as exc:
        raise ProviderError(f"Network error talking to the provider ({type(exc).__name__}).")
    if resp.status_code >= 400:
        raise ProviderError(_safe_err(resp))
    return resp


def _data_uri(png_bytes):
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


# ----------------------------------------------------------------------------------------------- Meshy
class Meshy:
    name = "meshy"
    # stages for each flow (see pipeline.py)
    ITEM_STAGES = ["preview", "refine", "fetch"]
    CHAR_STAGES = ["concept", "image3d", "rig", "fetch"]
    IMG_STAGES = ["concept", "image3d", "fetch"]            # concept image first, then image-to-3D: more controllable than text alone (landmarks)

    @staticmethod
    def configured():
        return bool(_cfg("MESHY_API_KEY"))

    def _h(self):
        return {"Authorization": f"Bearer {_cfg('MESHY_API_KEY')}"}

    def _url(self, path):
        return _cfg("MESHY_BASE").rstrip("/") + path

    def start(self, stage, prompt=None, parent=None, image_png=None):
        polys, model = _cfg("AI3D_TARGET_POLYS"), _cfg("MESHY_MODEL")
        if stage == "preview":
            body = {"mode": "preview", "prompt": prompt, "ai_model": model, "topology": "triangle", "target_polycount": polys, "should_remesh": True}
            return self._id(_call("POST", self._url("/v2/text-to-3d"), self._h(), json=body))
        if stage == "refine":
            body = {"mode": "refine", "preview_task_id": parent, "enable_pbr": True, "ai_model": model}
            return self._id(_call("POST", self._url("/v2/text-to-3d"), self._h(), json=body))
        if stage == "image3d":
            body = {"image_url": _data_uri(image_png), "ai_model": model, "topology": "triangle", "target_polycount": polys, "should_remesh": True,
                    "should_texture": True, "enable_pbr": True, "pose_mode": "t-pose"}
            return self._id(_call("POST", self._url("/v1/image-to-3d"), self._h(), json=body))
        if stage == "rig":
            return self._id(_call("POST", self._url("/v1/rigging"), self._h(), json={"input_task_id": parent, "height_meters": 1.0}))
        raise ProviderError(f"Unknown stage {stage}")

    @staticmethod
    def _id(resp):
        tid = (resp.json() or {}).get("result")
        if not tid or not isinstance(tid, str):
            raise ProviderError("The provider did not return a task id.")
        return tid

    def poll(self, stage, task_id):
        path = {"preview": "/v2/text-to-3d/", "refine": "/v2/text-to-3d/", "image3d": "/v1/image-to-3d/", "rig": "/v1/rigging/"}[stage]
        d = _call("GET", self._url(path + task_id), self._h()).json() or {}
        raw = (d.get("status") or "").upper()
        if raw == "SUCCEEDED":
            urls = {}
            if stage in ("preview", "refine", "image3d"):
                glb = (d.get("model_urls") or {}).get("glb")
                if glb:
                    urls["glb"] = glb
            else:
                res = d.get("result") or {}
                basic = res.get("basic_animations") or {}
                for key, url in (("glb", res.get("rigged_character_glb_url")), ("walk", basic.get("walking_glb_url")), ("run", basic.get("running_glb_url"))):
                    if url:
                        urls[key] = url
            if "glb" not in urls and stage != "preview":
                return Result("failed", 100, {}, "The provider finished but returned no model file.")
            return Result("success", 100, urls)
        if raw in ("FAILED", "CANCELED", "CANCELLED"):
            return Result("failed", int(d.get("progress") or 0), {}, ((d.get("task_error") or {}).get("message") or "The provider could not make this model.")[:200])
        return Result("running" if raw == "IN_PROGRESS" else "pending", int(d.get("progress") or 0))


# ----------------------------------------------------------------------------------------------- Tripo
class Tripo:
    name = "tripo"
    ITEM_STAGES = ["text3d", "fetch"]
    CHAR_STAGES = ["concept", "image3d", "rig", "anim_walk", "anim_run", "fetch"]
    IMG_STAGES = ["concept", "image3d", "fetch"]
    PRESETS = {"anim_walk": "preset:walk", "anim_run": "preset:run"}

    @staticmethod
    def configured():
        return bool(_cfg("TRIPO_API_KEY"))

    def _h(self):
        return {"Authorization": f"Bearer {_cfg('TRIPO_API_KEY')}"}

    def _url(self, path):
        return _cfg("TRIPO_BASE").rstrip("/") + path

    def _task(self, body):
        d = _call("POST", self._url("/task"), self._h(), json=body).json() or {}
        tid = (d.get("data") or {}).get("task_id")
        if d.get("code") not in (0, None) or not tid:
            raise ProviderError(f"The provider refused the task (code {d.get('code')}).")
        return tid

    def start(self, stage, prompt=None, parent=None, image_png=None):
        common = {"model_version": _cfg("TRIPO_MODEL"), "face_limit": _cfg("AI3D_TARGET_POLYS"), "smart_low_poly": True, "texture": True, "pbr": True}
        if stage == "text3d":
            return self._task({"type": "text_to_model", "prompt": prompt, **common})
        if stage == "image3d":
            up = _call("POST", self._url("/upload"), self._h(), files={"file": ("concept.png", image_png, "image/png")}).json() or {}
            token = (up.get("data") or {}).get("image_token")
            if not token:
                raise ProviderError("The image upload to the provider failed.")
            return self._task({"type": "image_to_model", "file": {"type": "png", "file_token": token}, **common})
        if stage == "rig":
            return self._task({"type": "animate_rig", "original_model_task_id": parent, "out_format": "glb", "spec": "tripo"})
        if stage in self.PRESETS:
            return self._task({"type": "animate_retarget", "original_model_task_id": parent, "animation": self.PRESETS[stage],
                               "out_format": "glb", "bake_animation": True})
        raise ProviderError(f"Unknown stage {stage}")

    def poll(self, stage, task_id):
        d = (_call("GET", self._url(f"/task/{task_id}"), self._h()).json() or {}).get("data") or {}
        raw = (d.get("status") or "").lower()
        if raw == "success":
            out = d.get("output") or {}
            url = out.get("pbr_model") or out.get("model")
            if not url:
                return Result("failed", 100, {}, "The provider finished but returned no model file.")
            return Result("success", 100, {"glb": url})
        if raw in ("failed", "cancelled", "canceled", "banned", "expired", "unknown"):
            return Result("failed", int(d.get("progress") or 0), {}, f"The provider reported: {raw}.")
        return Result("running" if raw == "running" else "pending", int(d.get("progress") or 0))


PROVIDERS = {"meshy": Meshy, "tripo": Tripo}


def get(name):
    if name not in PROVIDERS:
        raise ProviderError("Unknown provider.")
    return PROVIDERS[name]()


# ----------------------------------------------------------------------------------------------- concept image (characters only)
def concept_provider():
    return (_cfg("CONCEPT_PROVIDER") or "openai").lower()


def concept_configured():
    return bool(_cfg("OPENAI_API_KEY") if concept_provider() == "openai" else _cfg("STABILITY_API_KEY"))


def make_concept(prompt):
    """-> PNG bytes of a front-view concept image on a plain background. Validated and re-encoded, never trusted as delivered."""
    prompt = prompt + ", full body, front view, plain white background, soft even lighting"
    if concept_provider() == "openai":
        h = {"Authorization": f"Bearer {_cfg('OPENAI_API_KEY')}"}
        body = {"model": _cfg("OPENAI_IMAGE_MODEL"), "prompt": prompt, "size": "1024x1024", "n": 1}
        d = _call("POST", "https://api.openai.com/v1/images/generations", h, json=body).json() or {}
        item = (d.get("data") or [{}])[0]
        if item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            raise ProviderError("The image provider returned a link instead of image data; this app only accepts inline images.")
        else:
            raise ProviderError("The image provider returned no image.")
    else:
        h = {"Authorization": f"Bearer {_cfg('STABILITY_API_KEY')}", "Accept": "image/*"}
        resp = _call("POST", "https://api.stability.ai/v2beta/stable-image/generate/core", h,
                     files={"none": ""}, data={"prompt": prompt, "output_format": "png", "aspect_ratio": "1:1"})
        raw = resp.content
    return _validated_png(raw)


def _validated_png(raw):
    if not raw or len(raw) > 12 * 1024 * 1024:
        raise ProviderError("The concept image was empty or too large.")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.width < 256 or img.height < 256:
            raise ProviderError("The concept image was too small.")
        out = io.BytesIO()
        img.convert("RGB").save(out, "PNG")
        return out.getvalue()
    except ProviderError:
        raise
    except Exception:
        raise ProviderError("The concept image could not be read.")
