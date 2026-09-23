"""SSH-friendly photo preview. No model, DB, image queue, or camera worker."""
from __future__ import annotations

import secrets
import threading
from contextlib import closing
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request

from equipment_manager.vision.types import DetectionError
from equipment_manager.web_server import run_web_server


class PreviewBusy(Exception):
    pass


class PreviewSession:
    def __init__(self, source, cv2, save_photo, count):
        self.source = source
        self.cv2 = cv2
        self.save_photo = save_photo
        self.count = count
        self.saved = 0
        self.last_file = ""
        self._lock = threading.Lock()
        self._closed = False

    def take_frame(self, *, save=False):
        # Reject concurrent camera work rather than building an image/work queue.
        if not self._lock.acquire(blocking=False):
            raise PreviewBusy("카메라가 처리 중입니다. 잠시 뒤 다시 눌러 주세요.")
        try:
            if self._closed:
                raise DetectionError("촬영 프로그램이 종료되었습니다.")
            if save and self.saved >= self.count:
                raise PreviewBusy("설정한 촬영 장수에 도달했습니다.")
            # USB buffers may contain old frames after a hidden-tab pause.
            frame_count = 4 if self.source.backend_name == "opencv" else 1
            result = None
            with closing(self.source.frames(frame_count)) as frames:
                index = 0
                for frame in frames:
                    try:
                        index += 1
                        if index == frame_count:
                            if save:
                                path = self.save_photo(frame, self.saved + 1)
                                self.saved += 1
                                self.last_file = path.name
                                result = self.status()
                            else:
                                result = (self._encode_preview(frame), self.saved)
                    finally:
                        frame = None
            if result is None:
                raise DetectionError("카메라에서 화면을 받지 못했습니다.")
            return result
        finally:
            self._lock.release()

    def _encode_preview(self, frame):
        encoded = None
        try:
            height, width = frame.shape[:2]
            if width > 640:
                frame = self.cv2.resize(frame, (640, max(1, round(height * 640 / width))))
            ok, encoded = self.cv2.imencode(".jpg", frame, [self.cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise DetectionError("미리보기 이미지 변환에 실패했습니다.")
            return encoded.tobytes()
        finally:
            frame = encoded = None

    def status(self):
        return {"saved": self.saved, "limit": self.count, "file": self.last_file}

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self.source.close()


def create_preview_app(session, class_name, output_dir):
    assets = Path(__file__).with_name("capture_preview_assets")
    app = Flask(__name__, template_folder=str(assets), static_folder=str(assets), static_url_path="/assets")
    app.config.update(MAX_CONTENT_LENGTH=1024, TRUSTED_HOSTS=["127.0.0.1", "localhost"])
    token = secrets.token_urlsafe(32)

    @app.before_request
    def protect_camera():
        # The listener is loopback-only. This also blocks cross-site form/fetch
        # requests from another website visited in the same browser.
        if request.path in {"/frame.jpg", "/capture"}:
            supplied = request.headers.get("X-Preview-Token", "")
            if not secrets.compare_digest(supplied, token):
                abort(403)

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.get("/")
    def index():
        return render_template("index.html", token=token, class_name=class_name,
                               output_dir=str(output_dir), limit=session.count)

    @app.get("/frame.jpg")
    def frame():
        jpeg, saved = session.take_frame()
        return Response(jpeg, mimetype="image/jpeg", headers={"X-Saved-Count": str(saved)})

    @app.post("/capture")
    def capture():
        return jsonify(session.take_frame(save=True))

    @app.errorhandler(PreviewBusy)
    def busy(error):
        return jsonify(error=str(error)), 409

    @app.errorhandler(Exception)
    def failed(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException):
            return error
        app.logger.error("Photo preview request failed: %s", error)
        return jsonify(error="카메라 또는 저장 오류입니다. 라파 터미널 메시지를 확인하세요."), 503

    return app


def run_preview(source, cv2, save_photo, class_name, count, output_dir, port):
    session = PreviewSession(source, cv2, save_photo, count)
    try:
        app = create_preview_app(session, class_name, output_dir)
        print(f"사진 저장 위치: {output_dir}")
        print(f"PC에서 SSH 터널 연결 후 http://127.0.0.1:{port} 에 접속하세요.")
        print("실시간 화면에서 사진 촬영 버튼을 누르세요. 종료: 이 터미널에서 Ctrl+C")
        run_web_server(app, host="127.0.0.1", port=port, threads=2, connection_limit=8,
                       backlog=8, max_request_body_size=1024, channel_timeout=15)
    except KeyboardInterrupt:
        print("\n미리보기 종료. 저장한 사진은 유지됩니다.")
        return 130
    except OSError as exc:
        print(f"미리보기 실행 실패: {exc}")
        return 1
    finally:
        session.close()
    return 0
