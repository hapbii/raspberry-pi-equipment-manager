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
  let saved = 0, timer = null, pending = false, stopped = false;
  let objectUrl = null, active = null, ready = false, generation = 0;

  function updateButton() {
    button.disabled = stopped || doc.hidden || !ready || pending || Boolean(active?.capture) || saved >= limit;
  }
  function clearTimer() {
    if (timer !== null) env.clearTimeout(timer);
    timer = null;
  }
  function clearDeadline(request) {
    if (request?.deadline !== null && request?.deadline !== undefined) {
      env.clearTimeout(request.deadline);
      request.deadline = null;
    }
  }
  function releaseImage() {
    preview.removeAttribute("src");
    preview.hidden = true;
    if (objectUrl) env.URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
  function schedule(delay = 200) {
    clearTimer();
    if (!stopped && !doc.hidden && !active) timer = env.setTimeout(tick, delay);
  }
  async function tick() {
    timer = null;
    if (stopped || doc.hidden || active) return;
    const request = {controller: new env.AbortController(), capture: pending, generation, deadline: null};
    active = request;
    pending = false;
    request.deadline = env.setTimeout(() => request.controller.abort(), 15000);
    const isCurrent = () => !stopped && !doc.hidden && request.generation === generation;
    let delay = 200;
    updateButton();
    try {
      const response = await env.fetch(request.capture ? "/capture" : "/frame.jpg", {
        method: request.capture ? "POST" : "GET", headers, cache: "no-store", signal: request.controller.signal
      });
      if (!isCurrent()) {
        await response.body?.cancel();
        return;
      }
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || `연결 오류 (${response.status}). 새로고침하거나 SSH 연결을 확인하세요.`);
      }
      if (request.capture) {
        const result = await response.json();
        if (!isCurrent()) return;
        saved = result.saved;
        status.textContent = `저장 완료: ${result.file}`;
      } else {
        const blob = await response.blob();
        if (!isCurrent()) return;
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
      if (!isCurrent()) return;
      ready = false;
      pending = false;
      releaseImage();
      status.textContent = request.capture
        ? `저장 결과를 확인하지 못했습니다. 자동 재촬영하지 않습니다. 저장 장수와 라파 폴더를 확인하세요. ${error.message}`
        : `화면을 불러오지 못했습니다. ${error.message}`;
      delay = 1500;
    } finally {
      clearDeadline(request);
      if (active === request) active = null;
      updateButton();
      schedule(pending ? 0 : delay);
    }
  }
  button.addEventListener("click", () => {
    if (button.disabled || stopped) return;
    pending = true;
    status.textContent = "사진을 저장하는 중입니다…";
    updateButton();
    schedule(0);
  });
  function suspend(leaving) {
    generation += 1;
    pending = false;
    ready = false;
    clearTimer();
    releaseImage();
    // Hiding a tab must not cancel an in-flight save. Leaving the page can
    // abort its response, but neither path retries that save automatically.
    if (active && (leaving || !active.capture)) {
      clearDeadline(active);
      active.controller.abort();
    }
    updateButton();
  }
  doc.addEventListener("visibilitychange", () => {
    if (doc.hidden) suspend(false);
    else schedule(0);
  });
  env.addEventListener("pagehide", () => {
    stopped = true;
    suspend(true);
  });
  env.addEventListener("pageshow", (event) => {
    if (event.persisted) { stopped = false; ready = false; updateButton(); schedule(0); }
  });
  schedule(0);
}

if (typeof module !== "undefined" && module.exports) module.exports = {startPreview};
else startPreview();
