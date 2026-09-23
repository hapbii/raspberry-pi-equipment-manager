(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const dateFormatter = new Intl.DateTimeFormat("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const pendingRequests = new Set();
  window.addEventListener("pagehide", () => {
    pendingRequests.forEach((controller) => controller.abort());
  });

  function formatDate(value) {
    if (!value) return "기록 없음";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return dateFormatter.format(date);
  }

  async function postJson(url, body) {
    const controller = new AbortController();
    pendingRequests.add(controller);
    const timeout = window.setTimeout(() => controller.abort(), 120000);
    try {
      const pending = fetch(url, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify(body),
      });
      body = null;
      const response = await pending;
      const data = await response.json();
      if (!response.ok || !data.ok) {
        const error = new Error(data.error || "요청 처리에 실패했습니다.");
        error.code = data.code || "request_failed";
        throw error;
      }
      return data;
    } catch (error) {
      if (url === "/api/transactions" && !error.code) {
        throw new Error("저장 응답을 확인하지 못했습니다. 거래 기록을 확인한 후 다시 시도해 주세요.");
      }
      if (error.name === "AbortError") {
        throw new Error("인식 응답을 기다리는 시간이 초과되었거나 요청이 중단되었습니다.");
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
      pendingRequests.delete(controller);
    }
  }

  const inventoryGrid = document.querySelector("#inventory-grid");
  if (inventoryGrid) {
    let dashboardTimer = null;
    let dashboardStopped = document.hidden;
    let dashboardController = null;

    async function refreshDashboard() {
      dashboardTimer = null;
      if (dashboardStopped || dashboardController !== null) return;
      const controller = new AbortController();
      dashboardController = controller;
      const timeout = window.setTimeout(() => controller.abort(), 4000);
      try {
        const response = await fetch("/api/status", {
          cache: "no-store",
          signal: controller.signal,
        });
        const data = await response.json();
        if (dashboardStopped || controller.signal.aborted) return;
        if (!response.ok || !data.ok) throw new Error(data.error || "현황을 읽지 못했습니다.");
        data.inventory.forEach((item) => {
          const card = inventoryGrid.querySelector(`[data-equipment-id="${item.id}"]`);
          if (!card) return;
          card.querySelector(".available-number").textContent = item.available_qty;
          card.querySelector(".total-number").textContent = ` / ${item.total_qty}개`;
          card.querySelector(".loaned-number").textContent = item.loaned_qty;
          card.querySelector(".quantity-warning")?.classList.toggle("hidden", !item.quantity_mismatch);
          card.querySelector(".loan-period-number").textContent = item.loan_period_days;
          card.querySelector(".meter span").style.width = `${item.total_qty ? item.available_qty / item.total_qty * 100 : 0}%`;
          const badge = card.querySelector(".availability-badge");
          badge.textContent = item.available_qty > 0 ? "사용 가능" : "대여 불가";
          badge.classList.toggle("empty", item.available_qty <= 0);
        });
        const dot = document.querySelector("#device-dot");
        const state = document.querySelector("#device-state");
        dot.className = `status-dot ${data.device.online ? "online" : "offline"}`;
        state.textContent = data.device.online ? "서버 온라인" : "서버 응답 지연";
        if (data.recognition) {
          document.querySelector("#recognition-title").textContent = data.recognition.title;
          document.querySelector("#recognition-message").textContent = data.recognition.message;
        }
        document.querySelector("#last-seen").textContent = `마지막 신호 ${formatDate(data.device.last_seen)}`;
        document.querySelector("#dashboard-updated").textContent = formatDate(data.server_time);
      } catch (error) {
        if (dashboardStopped) return;
        const dot = document.querySelector("#device-dot");
        dot.className = "status-dot offline";
        document.querySelector("#device-state").textContent = "서버 연결 실패";
        document.querySelector("#last-seen").textContent = error.name === "AbortError"
          ? "상태 요청 시간 초과"
          : error.message;
      } finally {
        window.clearTimeout(timeout);
        dashboardController = null;
        if (!dashboardStopped) {
          dashboardTimer = window.setTimeout(refreshDashboard, 5000);
        }
      }
    }

    function stopDashboard() {
      dashboardStopped = true;
      if (dashboardTimer !== null) window.clearTimeout(dashboardTimer);
      dashboardTimer = null;
      if (dashboardController !== null) dashboardController.abort();
    }

    function resumeDashboard() {
      if (document.hidden) return;
      dashboardStopped = false;
      if (dashboardController === null && dashboardTimer === null) refreshDashboard();
    }

    window.addEventListener("pagehide", stopDashboard);
    window.addEventListener("pageshow", (event) => {
      if (event.persisted) resumeDashboard();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopDashboard();
      else resumeDashboard();
    });

    refreshDashboard();
  }

  const scanApp = document.querySelector("#scan-app");
  if (scanApp) {
    const detectButton = document.querySelector("#detect-button");
    const confirmButton = document.querySelector("#confirm-button");
    const retryButton = document.querySelector("#retry-button");
    const placeholder = document.querySelector("#scan-placeholder");
    const resultPanel = document.querySelector("#scan-result");
    const message = document.querySelector("#scan-message");
    const studentInput = document.querySelector("#student-id");
    const reasonInput = document.querySelector("#loan-reason");
    const reasonField = document.querySelector("#loan-reason-field");
    const recognitionReady = scanApp.dataset.mode === "yolo" && scanApp.dataset.canScan !== "false";
    const resultLoanPeriod = document.querySelector("#result-loan-period");
    const actionInputs = document.querySelectorAll('input[name="action"]');
    let scanToken = null;
    let scanDueDate = null;
    let scanLoanPeriodDays = null;
    let saving = false;
    let scanning = false;
    let expiryTimer = null;
    let scanDeadline = 0;
    let scanPageHidden = false;
    const expiryLabel = document.querySelector("#scan-expiry");

    function clearExpiryTimer() {
      if (expiryTimer !== null) window.clearTimeout(expiryTimer);
      expiryTimer = null;
    }

    function refreshExpiry() {
      clearExpiryTimer();
      if (!scanToken || scanPageHidden) return;
      const remaining = Math.ceil((scanDeadline - Date.now()) / 1000);
      if (remaining <= 0) {
        scanToken = null;
        expiryLabel.textContent = "인식 결과가 만료되었습니다. 다시 인식해 주세요.";
        if (!saving) showMessage(expiryLabel.textContent);
        updateControls();
        return;
      }
      expiryLabel.textContent = `확정까지 남은 시간: ${remaining}초`;
      expiryTimer = window.setTimeout(refreshExpiry, 1000);
    }

    window.addEventListener("pagehide", () => {
      scanPageHidden = true;
      clearExpiryTimer();
    });
    window.addEventListener("pageshow", (event) => {
      if (event.persisted) {
        scanPageHidden = false;
        refreshExpiry();
      }
    });

    function updateControls() {
      const busy = saving || scanning;
      [confirmButton, retryButton, studentInput, ...actionInputs].forEach((element) => {
        element.disabled = busy;
      });
      detectButton.disabled = busy || !recognitionReady;
      confirmButton.disabled = busy || !scanToken;
      reasonInput.disabled = busy || selectedAction() === "return";
    }

    function setSaving(value) {
      saving = value;
      updateControls();
      confirmButton.toggleAttribute("aria-busy", value);
      confirmButton.textContent = value ? "저장 중..." : `이 기자재 ${selectedAction() === "loan" ? "대여" : "반납"}하기`;
    }

    function selectedAction() {
      return document.querySelector('input[name="action"]:checked')?.value;
    }

    function syncLoanPeriodResult() {
      const isLoan = selectedAction() === "loan";
      reasonField.classList.toggle("hidden", !isLoan);
      reasonInput.required = isLoan;
      if (!saving) confirmButton.textContent = `이 기자재 ${isLoan ? "대여" : "반납"}하기`;
      updateControls();
      const showPeriod = selectedAction() === "loan" && scanDueDate !== null;
      resultLoanPeriod.classList.toggle("hidden", !showPeriod);
      if (showPeriod) {
        resultLoanPeriod.textContent = `관리자 설정: ${scanLoanPeriodDays}일 대여 · 반납 예정 ${scanDueDate}`;
      }
    }

    actionInputs.forEach((input) => input.addEventListener("change", syncLoanPeriodResult));
    syncLoanPeriodResult();

    function formError() {
      if (!studentInput.value.trim()) return "학번을 입력해 주세요.";
      if (selectedAction() === "loan") {
        if (!reasonInput.value.trim()) return "대여 사유를 입력해 주세요.";
        if (reasonInput.value.trim().length > 200) return "대여 사유는 200자 이내로 입력해 주세요.";
      }
      return null;
    }

    function showMessage(text, success = false) {
      message.textContent = text;
      message.classList.remove("hidden", "success");
      if (success) message.classList.add("success");
    }

    function resetResult() {
      clearExpiryTimer();
      scanDeadline = 0;
      expiryLabel.textContent = "";
      scanToken = null;
      scanDueDate = null;
      scanLoanPeriodDays = null;
      ["#result-name", "#result-confidence", "#result-votes", "#result-duration"].forEach((selector) => {
        document.querySelector(selector).textContent = "";
      });
      resultLoanPeriod.textContent = "";
      resultPanel.classList.add("hidden");
      resultLoanPeriod.classList.add("hidden");
      placeholder.classList.remove("hidden");
      message.classList.add("hidden");
      updateControls();
    }

    detectButton.addEventListener("click", async () => {
      if (scanning || saving || !recognitionReady) return;
      resetResult();
      const error = formError();
      if (error) return showMessage(error);
      scanning = true;
      updateControls();
      detectButton.setAttribute("aria-busy", "true");
      detectButton.textContent = "인식 중...";
      try {
        const data = await postJson("/api/scans", {
          student_id: studentInput.value.trim(),
          action: selectedAction(),
        });
        if (scanPageHidden) return;
        scanToken = data.scan.token;
        const ttl = Date.parse(data.scan.expires_at) - Date.parse(data.server_time);
        scanDeadline = Date.now() + (Number.isFinite(ttl) ? Math.max(0, ttl) : 0);
        scanDueDate = data.scan.due_date;
        scanLoanPeriodDays = data.scan.loan_period_days;
        document.querySelector("#result-name").textContent = `${data.scan.equipment_name} 기자재입니다.`;
        document.querySelector("#result-confidence").textContent = `${(data.scan.confidence * 100).toFixed(1)}%`;
        document.querySelector("#result-votes").textContent = `${data.votes}/${data.frame_count} 프레임 일치`;
        document.querySelector("#result-duration").textContent = `${(data.duration_ms / 1000).toFixed(2)}초`;
        placeholder.classList.add("hidden");
        resultPanel.classList.remove("hidden");
        syncLoanPeriodResult();
        refreshExpiry();
      } catch (error) {
        showMessage(error.message);
      } finally {
        scanning = false;
        updateControls();
        detectButton.removeAttribute("aria-busy");
        detectButton.textContent = "객체 인식 시작";
      }
    });

    async function submitTransaction() {
      if (saving) return;
      refreshExpiry();
      const studentId = studentInput.value.trim();
      const action = selectedAction();
      const error = formError();
      if (error) {
        return showMessage(error);
      }
      if (!scanToken) return showMessage("먼저 기자재를 인식해 주세요.");
      setSaving(true);
      try {
        const pending = postJson("/api/transactions", {
          scan_token: scanToken,
          student_id: studentId,
          action,
          quantity: 1,
          reason: action === "loan" ? reasonInput.value.trim() : "",
        });
        const data = await pending;
        const tx = data.transaction;
        const actionName = tx.action === "loan" ? "대여" : "반납";
        const dueText = tx.due_date ? ` · 반납 예정 ${tx.due_date}` : "";
        if (!studentInput.readOnly) studentInput.value = "";
        reasonInput.value = "";
        resetResult();
        showMessage(`${tx.equipment_name} ${tx.quantity}개 ${actionName} 처리가 완료되었습니다${dueText}. 현재 사용 가능 ${tx.available_qty}개`, true);
      } catch (error) {
        if (error.code === "login_required") resetResult();
        showMessage(error.message);
      } finally {
        setSaving(false);
      }
    }

    confirmButton.addEventListener("click", () => {
      if (saving) return;
      refreshExpiry();
      const error = formError();
      if (error) return showMessage(error);
      if (!scanToken) return showMessage("먼저 기자재를 인식해 주세요.");
      submitTransaction();
    });

    retryButton.addEventListener("click", resetResult);
  }

  document.querySelectorAll("[data-utc]").forEach((cell) => {
    cell.textContent = formatDate(cell.dataset.utc);
  });
})();
