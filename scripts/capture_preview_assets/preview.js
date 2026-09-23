"use strict";

// One request at a time; revoke old blobs and pause on hidden tabs.
function startPreview(doc = document, env = window) {
  const app = doc.getElementById("capture-app");
  const preview = doc.getElementById("preview");
  const button = doc.getElementById("capture");
  const status = doc.getElementById("status");
  const counter = doc.getElementById("saved");
  const headers = {"X-Preview-Token": app.dataset.token};
  const limit = Number(app.dataset.limit);
  let saved = 0, timer = null, busy = false, pending = false, stopped = false;
  let objectUrl = null, controller = null, ready = false, saving = false;

  function updateButton() { button.disabled = !ready || pending || saving || saved >= limit; }
  function schedule(delay = 200) {
    if (timer !== null) env.clearTimeout(timer);
    timer = null;
    if (!stopped && !doc.hidden) timer = env.setTimeout(tick, delay);
  }
  async function tick() {
    timer = null;
    if (stopped || doc.hidden || busy) return;
    busy = true;
    controller = new env.AbortController();
    const timeout = env.setTimeout(() => controller?.abort(), 15000);
    let delay = 200;
    const capture = pending;
    saving = capture;
    try {
      const response = await env.fetch(capture ? "/capture" : "/frame.jpg", {
        method: capture ? "POST" : "GET", headers, cache: "no-store", signal: controller.signal
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || `연결 오류 (${response.status}). 새로고침하거나 SSH 연결을 확인하세요.`);
      }
      if (capture) {
        const result = await response.json();
        saved = result.saved;
        status.textContent = `저장 완료: ${result.file}`;
      } else {
        const blob = await response.blob();
        if (stopped) return;
        const nextUrl = env.URL.createObjectURL(blob);
        const previousUrl = objectUrl;
        objectUrl = nextUrl;
        preview.src = nextUrl;
        if (previousUrl) env.URL.revokeObjectURL(previousUrl);
        preview.hidden = false;
        saved = Number(response.headers.get("X-Saved-Count"));
        if (!ready) status.textContent = "화면 연결 완료. 구도를 확인하고 사진 촬영을 눌러 주세요.";
        ready = true;
      }
      counter.textContent = String(saved);
      if (saved >= limit) status.textContent = `${saved}장 촬영 완료! 종료하려면 SSH 터미널에서 Ctrl+C를 누르세요.`;
    } catch (error) {
      ready = false;
      if (!stopped) status.textContent = capture
        ? `저장 결과를 확인하지 못했습니다. 자동 재촬영하지 않습니다. 저장 장수와 라파 폴더를 확인하세요. ${error.message}`
        : `화면을 불러오지 못했습니다. ${error.message}`;
      delay = 1500;
    } finally {
      env.clearTimeout(timeout);
      if (capture) pending = false;
      saving = false;
      controller = null;
      busy = false;
      updateButton();
      schedule(pending ? 0 : delay);
    }
  }
  button.addEventListener("click", () => {
    if (button.disabled || stopped) return;
    pending = true;
    status.textContent = "사진을 저장하는 중입니다…";
    updateButton();
    if (!busy) schedule(0);
  });
  doc.addEventListener("visibilitychange", () => {
    // Never automatically abort/retry a save: its disk write may have succeeded.
    if (doc.hidden) {
      if (timer !== null) env.clearTimeout(timer);
      timer = null;
      pending = false;
      updateButton();
    } else if (!busy) schedule(0);
  });
  env.addEventListener("pagehide", () => {
    stopped = true;
    if (timer !== null) env.clearTimeout(timer);
    controller?.abort();
    if (objectUrl) env.URL.revokeObjectURL(objectUrl);
    objectUrl = null;
    preview.removeAttribute("src");
  });
  env.addEventListener("pageshow", (event) => {
    if (event.persisted) { stopped = false; ready = false; updateButton(); schedule(0); }
  });
  schedule(0);
}

if (typeof module !== "undefined" && module.exports) module.exports = {startPreview};
else startPreview();
