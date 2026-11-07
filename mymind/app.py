"""MyMind — Built and Powered by Emtrixz. Application factory."""
import json
import logging
import os
import click
from flask import Flask, g, session, request, jsonify, render_template, Response, flash, redirect, url_for
from sqlalchemy.exc import OperationalError as SAOperationalError
from config import Config
from database import db
from database.db import Session
from database.models import User
from database.migrate import run_migrations
from markupsafe import Markup, escape
from routes.helpers import csrf_token, check_csrf, wants_json
from services import settings_service, demo_service, cache, verification_service

BRAND = "MyMind"
FOOTER = "MyMind — Built and Powered by Emtrixz."


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if app.config["PRODUCTION"] and app.config["SECRET_KEY"].startswith("dev-only"):
        raise RuntimeError("Set a strong SECRET_KEY before running in production.")
    logging.basicConfig(level=logging.INFO)

    db.init_engine(app.config["DATABASE_URL"])
    with app.app_context():
        run_migrations()
        settings_service.ensure_defaults()
    verification_service.check_startup(app)

    from routes import auth, subscriptions, onboarding, feed, pictures, videos, shots, music, journey, profile, admin, api, verification, parent_view, world, admin_world, admin_ai3d, world_share, caretaker
    for mod in (auth, subscriptions, onboarding, feed, pictures, videos, shots, music, journey, profile, admin, api, verification, parent_view, world, admin_world, admin_ai3d, world_share, caretaker):
        app.register_blueprint(mod.bp)
    app.register_blueprint(parent_view.manage)

    @app.before_request
    def load_user():
        g.user = None
        g.auth_role = None
        uid = session.get("uid")
        if uid:
            user = Session.get(User, uid)
            if user and user.account_status == "active":
                g.user = user
                stored_role = session.get("login_role")
                g.auth_role = stored_role if stored_role in ("caregiver", "child") else user.role
            else:
                session.clear()
                if user:
                    flash("This account is suspended. Please contact the administrator.", "error")

    @app.before_request
    def protect():
        if request.path == "/verify/webhook":        # server-to-server call from Sumsub: authenticated by its HMAC signature instead of CSRF
            return
        if request.method == "POST" and request.path == "/admin/world/upload":      # admin art uploads need a larger body than other forms
            request.max_content_length = app.config["WORLD_UPLOAD_MAX_BYTES"] + 64 * 1024
        if request.method == "POST" and request.path == "/admin/world/upload-folder":      # a whole folder of art in one request
            request.max_content_length = app.config["WORLD_FOLDER_MAX_BYTES"] + 64 * 1024
            request.max_form_parts = app.config["WORLD_FOLDER_MAX_FILES"] * 2 + 50       # one part per image plus a few small form fields
        if request.method == "POST" and request.path == "/admin/3d/upload":          # admin uploads of a Blender .glb
            request.max_content_length = app.config["AI3D_MANUAL_MAX_BYTES"] + 64 * 1024
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and not check_csrf():
            if wants_json():
                return jsonify(error="Security check failed. Please refresh the page."), 400
            flash("Your session expired. Please try again.", "error")
            return redirect(request.referrer or url_for("auth.login"))
        if request.path.startswith("/api/") and g.user:
            if cache.rate_limited(f"api:{g.user.id}", app.config["API_MAX_PER_MINUTE"], 60):
                return jsonify(error="Slow down a little, please."), 429

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        embedded_preview = request.endpoint == "world_share.caretaker_preview"
        resp.headers["X-Frame-Options"] = "SAMEORIGIN" if embedded_preview else "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        csp = (
            "default-src 'self'; img-src 'self' data: blob: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; script-src 'self' 'wasm-unsafe-eval'; "      # wasm: Draco/Meshopt decoders for 3D models
            "frame-src 'self' https://www.youtube-nocookie.com https://open.spotify.com; media-src 'self' blob:; "
            "worker-src 'self' blob:; connect-src 'self' blob:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        if request.path.startswith("/verify"):      # only the verification page may load the Sumsub WebSDK and frame it
            csp = (csp.replace("script-src 'self'", "script-src 'self' https://static.sumsub.com")
                      .replace("frame-src ", "frame-src https://static.sumsub.com https://*.sumsub.com ")
                      .replace("connect-src 'self' blob:", "connect-src 'self' blob: https://*.sumsub.com"))
        if embedded_preview:
            csp = csp.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
        resp.headers["Content-Security-Policy"] = csp
        if request.path.startswith(("/p/", "/world/share/")):  # secret family links must never be indexed, cached or leaked via Referer
            resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            resp.headers["Referrer-Policy"] = "no-referrer"
            resp.headers["Cache-Control"] = "no-store"
        if (request.path.startswith("/api/") or g.get("user")) and not resp.headers.get("Cache-Control"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.teardown_appcontext
    def cleanup(_):
        Session.remove()

    @app.context_processor
    def inject():
        cg = {}
        if g.get("user") and g.user.role == "caregiver":
            cg = settings_service.caregiver_settings(g.user.id)
        child = None
        read_only_child = False
        if g.get("user") and g.user.role == "caregiver":
            from routes.helpers import child_of
            from services import plan_service
            child = child_of(g.user)
            read_only_child = bool(g.auth_role == "child" and plan_service.child_is_read_only(g.user.id, child))
        return dict(csrf_token=csrf_token, brand=BRAND, footer_text=FOOTER, user=g.get("user"), auth_role=g.get("auth_role"),
                    cg=cg, child_profile=child, read_only_child=read_only_child,
                    tagline=settings_service.get("brand_tagline") or "Your thoughts. Your world.")

    def icon(name, cls=""):
        """Inline Lucide line icon (black by default, inherits currentColor)."""
        return Markup(f'<svg class="ic {escape(cls)}" aria-hidden="true" focusable="false"><use href="#i-{escape(name)}"/></svg>')
    app.jinja_env.globals["icon"] = icon

    @app.route("/robots.txt")
    def robots():
        return Response("User-agent: *\nDisallow: /p/\nDisallow: /world/share/\n", mimetype="text/plain")

    @app.route("/demo-art/<category>/<int:n>.svg")
    def demo_art(category, n):
        return Response(demo_service.art_svg(category, n), mimetype="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

    @app.errorhandler(403)
    def e403(_):
        return (jsonify(error="Not allowed.") if wants_json() else render_template("error.html", code=403, msg="You don't have access to this page.")), 403

    @app.errorhandler(413)
    def e413(_):
        msg = "That upload is too large."
        if wants_json():
            return jsonify(error=msg), 413
        flash(msg, "error")
        return redirect(request.referrer or url_for("auth.index"))

    @app.errorhandler(404)
    def e404(_):
        return (jsonify(error="Not found.") if wants_json() else render_template("error.html", code=404, msg="We couldn't find that page.")), 404

    @app.errorhandler(SAOperationalError)
    def e_db(exc):
        """Database unreachable (e.g. Turso connection dropped even after retries): friendly 503, not a crash."""
        app.logger.warning("database unavailable: %s", getattr(exc, "orig", exc))
        try:
            Session.rollback()
        except Exception:
            pass
        msg = "We can't reach our database right now. Please try again in a moment."
        if wants_json():
            return jsonify(error=msg), 503
        try:
            return render_template("error.html", code=503, msg=msg), 503
        except Exception:   # the template itself may need the database (settings); never fail inside an error handler
            return Response(msg, status=503, mimetype="text/plain")

    @app.errorhandler(500)
    def e500(exc):
        app.logger.exception("server error")
        return (jsonify(error="Something went wrong.") if wants_json() else render_template("error.html", code=500, msg="Something went wrong on our side.")), 500

    @app.cli.command("init-db")
    def init_db_cmd():
        run_migrations(); settings_service.ensure_defaults(); click.echo("Database initialised.")

    @app.cli.command("create-admin")
    @click.option("--username", envvar="ADMIN_USERNAME", prompt=True)
    @click.option("--password", envvar="ADMIN_PASSWORD", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin_cmd(username, password):
        from services import auth_service
        try:
            click.echo(auth_service.create_admin(username, password))
        except auth_service.AuthError as exc:
            raise click.ClickException(str(exc))

    @app.cli.command("ai3d-worker")
    @click.option("--once", is_flag=True, help="Advance due jobs once and exit (for cron).")
    @click.option("--interval", default=10, show_default=True, help="Seconds between passes when looping.")
    def ai3d_worker_cmd(once, interval):
        """Advance AI 3D jobs (provider polling, downloading, optimising). Run it as a second process next to the web server."""
        import time
        from services.ai3d import pipeline
        while True:
            try:
                n = pipeline.run_due()
                if n:
                    click.echo(f"advanced {n} job(s)")
            except Exception as exc:                      # keep the loop alive; the next pass retries
                app.logger.exception("ai3d worker pass failed")
                click.echo(f"pass failed: {type(exc).__name__}")
            finally:
                Session.remove()
            if once:
                break
            time.sleep(max(2, interval))

    @app.cli.command("sumsub-check")
    def sumsub_check_cmd():
        """Check your Sumsub setup end to end (credentials, level, clock, webhook secret, SDK URL). Safe: it creates nothing but a token."""
        import email.utils
        import hashlib
        import hmac as _hmac
        import requests
        from services import sumsub_service as sx, verification_service as vs
        bad = []

        def row(ok, label, detail=""):
            click.echo(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
            if not ok:
                bad.append(label)

        c = app.config
        click.echo(f"Verification mode: {vs.mode()}  (ID_VERIFICATION={c['ID_VERIFICATION'] or 'auto'})")
        row(bool(c["SUMSUB_APP_TOKEN"]), "SUMSUB_APP_TOKEN is set")
        row(bool(c["SUMSUB_SECRET_KEY"]), "SUMSUB_SECRET_KEY is set")
        row(bool(c["SUMSUB_WEBHOOK_SECRET"]), "SUMSUB_WEBHOOK_SECRET is set", "the 'Secret key' you typed when creating the webhook in the dashboard")
        env = "sandbox" if (c["SUMSUB_APP_TOKEN"] or "").startswith("sbx:") else "production" if c["SUMSUB_APP_TOKEN"] else "unknown"
        click.echo(f"       token looks like a {env} token; level name = {c['SUMSUB_LEVEL_NAME']!r} (case-sensitive, must exist in the same environment)")
        if not (c["SUMSUB_APP_TOKEN"] and c["SUMSUB_SECRET_KEY"]):
            raise click.ClickException("Set the Sumsub keys first (see README).")
        try:                                              # clock: signatures are rejected if our clock is more than ~1 minute off
            r = requests.head(c["SUMSUB_BASE_URL"], timeout=10)
            theirs = email.utils.parsedate_to_datetime(r.headers["Date"]).timestamp()
            import time as _t
            skew = abs(_t.time() - theirs)
            row(skew < 30, "Server clock matches Sumsub's", f"{skew:.0f}s apart")
        except Exception as exc:
            row(False, "Reach Sumsub", type(exc).__name__)
        with app.app_context():
            try:
                sx.get_applicant_by_external(0)
                row(True, "Signed request accepted (unexpected: test applicant exists)")
            except sx.SumsubError as exc:
                if exc.status == 404:
                    row(True, "Signed request accepted", "credentials and signature are valid (404 = no such test applicant, as expected)")
                elif exc.kind == "auth":
                    row(False, "Signed request accepted", "Sumsub rejected the token/secret/signature: check the keys and that they match this environment")
                else:
                    row(False, "Signed request accepted", f"{exc.kind} (HTTP {exc.status})")
            try:
                tok = sx.access_token(0, ttl=60)
                row(bool(tok), "Level exists and SDK tokens can be issued", c["SUMSUB_LEVEL_NAME"])
            except sx.SumsubError as exc:
                row(False, "Level exists and SDK tokens can be issued", f"{exc.kind} (HTTP {exc.status}): check SUMSUB_LEVEL_NAME spelling and environment")
        body = b'{"type":"applicantReviewed"}'
        sig = _hmac.new(c["SUMSUB_WEBHOOK_SECRET"].encode(), body, hashlib.sha256).hexdigest()
        with app.test_request_context():
            ok = sx.verify_webhook(body, {"X-Payload-Digest-Alg": "HMAC_SHA256_HEX", "X-Payload-Digest": sig}) if c["SUMSUB_WEBHOOK_SECRET"] else False
        row(ok, "Webhook signature check works with your secret")
        click.echo("       In the Sumsub dashboard the webhook URL must be:  https://<your-domain>/verify/webhook  (event: Applicant reviewed)")
        try:
            row(requests.head(c["SUMSUB_SDK_URL"], timeout=10).status_code == 200, "WebSDK script URL is reachable", c["SUMSUB_SDK_URL"])
        except Exception as exc:
            row(False, "WebSDK script URL is reachable", type(exc).__name__)
        click.echo("\nStill needs a human: run one test applicant through /verify in the sandbox (use Sumsub's test documents) and watch it return as verified;"
                   " test the camera on a real phone over HTTPS.")
        if bad:
            raise click.ClickException(f"{len(bad)} check(s) failed.")

    @app.cli.command("ai3d-check")
    def ai3d_check_cmd():
        """Check the AI 3D setup against the real providers: keys, balances, model names, storage and the optimiser. Creates nothing and costs nothing."""
        import tempfile
        import requests
        from services.ai3d import optimize, providers
        bad = []

        def row(state, label, detail=""):
            click.echo(f"[{state}] {label}" + (f": {detail}" if detail else ""))
            if state == "FAIL":
                bad.append(label)

        c = app.config

        def probe(label, url, headers, extra=None):
            try:
                r = requests.get(url, headers=headers, timeout=15)
            except requests.RequestException as exc:
                return row("FAIL", label, f"could not reach the provider ({type(exc).__name__})")
            if r.status_code in (401, 403):
                return row("FAIL", label, f"the key was rejected (HTTP {r.status_code})")
            if r.status_code != 200:
                return row("FAIL", label, f"HTTP {r.status_code}: the endpoint or base URL may differ, check the provider's current docs")
            try:
                body = r.json()
            except ValueError:
                body = {}
            note = extra(body) if extra else ""
            return row("PASS", label, note or "key accepted")

        def credits(body):
            for key in ("balance", "credits", "remaining"):
                v = body.get(key, (body.get("data") or {}).get(key) if isinstance(body.get("data"), dict) else None)
                if isinstance(v, (int, float)):
                    return f"key accepted, balance {v}"
            return ""

        if c["MESHY_API_KEY"]:
            probe("Meshy key", c["MESHY_BASE"].rstrip("/") + "/v1/balance", {"Authorization": f"Bearer {c['MESHY_API_KEY']}"}, credits)
            click.echo(f"       model in use: {c['MESHY_MODEL']!r} (confirm it is current in the Meshy dashboard)")
        else:
            row("SKIP", "Meshy", "MESHY_API_KEY not set")
        if c["TRIPO_API_KEY"]:
            probe("Tripo key", c["TRIPO_BASE"].rstrip("/") + "/user/balance", {"Authorization": f"Bearer {c['TRIPO_API_KEY']}"}, credits)
            click.echo(f"       model in use: {c['TRIPO_MODEL']!r} (confirm it is current in the Tripo dashboard)")
        else:
            row("SKIP", "Tripo", "TRIPO_API_KEY not set")
        which = providers.concept_provider()
        if which == "openai" and c["OPENAI_API_KEY"]:
            def has_model(body):
                ids = {m.get("id") for m in body.get("data", []) if isinstance(m, dict)}
                if c["OPENAI_IMAGE_MODEL"] not in ids:
                    bad.append("OpenAI image model")
                    return f"key accepted, but the model {c['OPENAI_IMAGE_MODEL']!r} is NOT available to this key. Set OPENAI_IMAGE_MODEL to one that is"
                return f"key accepted, image model {c['OPENAI_IMAGE_MODEL']!r} is available"
            probe("OpenAI key and image model", "https://api.openai.com/v1/models", {"Authorization": f"Bearer {c['OPENAI_API_KEY']}"}, has_model)
        elif which == "stability" and c["STABILITY_API_KEY"]:
            probe("Stability key", "https://api.stability.ai/v1/user/balance", {"Authorization": f"Bearer {c['STABILITY_API_KEY']}"}, credits)
        else:
            row("SKIP", "Concept images", f"no key for CONCEPT_PROVIDER={which} (characters need one)")
        for label, path in (("World Library storage", c["WORLD_ASSET_DIR"]), ("Private 3D storage", c["AI3D_PRIVATE_DIR"])):
            try:
                import os
                os.makedirs(path, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=path):
                    pass
                row("PASS", label + " is writable", path)
            except OSError as exc:
                row("FAIL", label + " is writable", f"{path}: {exc.strerror}")
        row("PASS" if optimize.available() else "WARN", "Model optimiser (gltf-transform)", "installed" if optimize.available() else "not installed: models are kept as delivered (npm i -g @gltf-transform/cli)")
        click.echo("\nStill needs a human: run ONE test job per provider from Admin -> AI 3D, watch it reach review, and look at the model from every side.")
        if bad:
            raise click.ClickException(f"{len(bad)} check(s) failed.")

    return app


app = create_app() if os.getenv("MYMIND_NO_AUTOAPP") != "1" else None

if __name__ == "__main__":
    app.run(debug=not Config.PRODUCTION, port=5000)
