"""Flask backend + dashboard for the Hand Gesture Steering Controller.

Run:  python app.py      then open http://127.0.0.1:5000
"""
from __future__ import annotations

import atexit
import logging
from typing import Optional

from flask import Flask, Response, jsonify, render_template, request

from config import GESTURE_CHOICES, KEY_SCHEMES, Config
from database import Database
from engine import ControllerEngine, EngineError
class IgnoreStatusFilter(logging.Filter):
    def filter(self, record):
        return "/api/status" not in record.getMessage()


logging.getLogger("werkzeug").addFilter(IgnoreStatusFilter())


def create_app(config: Optional[Config] = None, engine: Optional[ControllerEngine] = None,
               db: Optional[Database] = None) -> Flask:
    config = config or Config()
    db = db or Database(config.database_path)
    user_id = db.get_or_create_default_user()
    if engine is None:
        engine = ControllerEngine(config, db=db, user_id=user_id)
    else:
        engine.db, engine.user_id = db, user_id
    engine.apply_settings(**db.get_settings(user_id))

    app = Flask(__name__)
    app.config["engine"] = engine
    app.config["db"] = db
    atexit.register(engine.stop)  # keys are released even if the server is closed

    @app.get("/")
    def index():
        return render_template("index.html", key_schemes=list(KEY_SCHEMES),
                               gestures=GESTURE_CHOICES,
                               default_scheme=config.default_key_scheme)

    @app.get("/video_feed")
    def video_feed():
        def generate():
            last_id = 0
            while True:
                item = engine.wait_for_frame(last_id, timeout=1.0)
                if item is None:
                    if not engine.running:
                        break
                    continue
                last_id, jpeg = item
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/status")
    def api_status():
        return jsonify(engine.get_status())

    @app.post("/api/start")
    def api_start():
        data = request.get_json(silent=True) or {}
        try:
            engine.start(game_name=str(data.get("game_name", "")).strip()[:80],
                         send_keys=bool(data.get("send_keys", True)),
                         key_scheme=data.get("key_scheme"))
        except EngineError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True})

    @app.post("/api/stop")
    def api_stop():
        engine.stop()
        return jsonify({"ok": True})

    @app.post("/api/calibrate")
    def api_calibrate():
        if not engine.running:
            return jsonify({"ok": False, "error": "Start the controller first"}), 400
        engine.calibrate()
        return jsonify({"ok": True})

    @app.get("/api/settings")
    def api_get_settings():
        return jsonify(engine.settings)

    @app.post("/api/settings")
    def api_set_settings():
        data = request.get_json(silent=True) or {}
        allowed = {k: data[k] for k in ("steering_sensitivity", "dead_zone",
                                         "acceleration_gesture", "brake_gesture") if k in data}
        try:
            applied = engine.apply_settings(**allowed)
        except (ValueError, TypeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        db.save_settings(user_id, **applied)
        return jsonify({"ok": True, "settings": applied})

    @app.get("/api/sessions")
    def api_sessions():
        return jsonify(db.list_sessions(user_id))

    return app


if __name__ == "__main__":
    cfg = Config()
    print(f"Open http://{cfg.host}:{cfg.port} in your browser")
    create_app(cfg).run(host=cfg.host, port=cfg.port, threaded=True, debug=False)
