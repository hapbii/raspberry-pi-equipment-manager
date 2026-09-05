(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

  function formatDate(value) {
    if (!value) return "기록 없음";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("ko-KR", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(date);
  }

  async function postJson(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({ ok: false, error: "서버 응답을 읽을 수 없습니다." }));
    if (!response.ok || !data.ok) throw new Error(data.error || "요청 처리에 실패했습니다.");
    return data;
  }

  const inventoryGrid = document.querySelector("#inventory-grid");
  if (inventoryGrid) {
    let dashboardTimer = null;
    let dashboardStopped = false;
    let dashboardController = null;

    async function refreshDashboard() {
      const controller = new AbortController();
      dashboardController = controller;
      const timeout = window.setTimeout(() => controller.abort(), 4000);
      try {
        const response = await fetch("/api/status", {
          cache: "no-store",
          signal: controller.signal,
        });
        const data = await response.json();
        if (!data.ok) throw new Error(data.error);
        data.inventory.forEach((item) => {
          const card = inventoryGrid.querySelector(`[data-equipment-id="${item.id}"]`);
          if (!card) return;
          card.querySelector(".available-number").textContent = item.available_qty;
          card.querySelector(".total-number").textContent = ` / ${item.total_qty}개`;
          card.querySelector(".loaned-number").textContent = item.loaned_qty;
          card.querySelector(".loan-period-number").textContent = item.loan_period_days;
          card.querySelector(".meter span").style.width = `${item.total_qty ? item.available_qty / item.total_qty * 100 : 0}%`;
          const badge = card.querySelector(".availability-badge");
          badge.textContent = item.available_qty > 0 ? "사용 가능" : "대여 불가";
          badge.classList.toggle("empty", item.available_qty <= 0);
        });
        const dot = document.querySelector("#device-dot");
        const state = document.querySelector("#device-state");
        dot.className = `status-dot ${data.device.online ? "online" : "offline"}`;
        state.textContent = data.device.online ? "인식 장치 온라인" : "인식 장치 오프라인";
        document.querySelector("#last-seen").textContent = `마지막 신호 ${formatDate(data.device.last_seen)}`;
        document.querySelector("#dashboard-updated").textContent = formatDate(data.server_time);
      } catch (error) {
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

    window.addEventListener("pagehide", () => {
      dashboardStopped = true;
      if (dashboardTimer !== null) window.clearTimeout(dashboardTimer);
      if (dashboardController !== null) dashboardController.abort();
    }, { once: true });

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
    const quantityInput = document.querySelector("#quantity");
    const resultLoanPeriod = document.querySelector("#result-loan-period");
    const actionInputs = document.querySelectorAll('input[name="action"]');
    let scanToken = null;
    let scanDueDate = null;
    let scanLoanPeriodDays = null;

    function selectedAction() {
      return document.querySelector('input[name="action"]:checked')?.value;
    }

    function syncLoanPeriodResult() {
      const showPeriod = selectedAction() === "loan" && scanDueDate !== null;
      resultLoanPeriod.classList.toggle("hidden", !showPeriod);
      if (showPeriod) {
        resultLoanPeriod.textContent = `관리자 설정: ${scanLoanPeriodDays}일 대여 · 반납 예정 ${scanDueDate}`;
      }
    }

    actionInputs.forEach((input) => input.addEventListener("change", syncLoanPeriodResult));

    function showMessage(text, success = false) {
      message.textContent = text;
      message.classList.remove("hidden", "success");
      if (success) message.classList.add("success");
    }

    function resetResult() {
      scanToken = null;
      scanDueDate = null;
      scanLoanPeriodDays = null;
      resultPanel.classList.add("hidden");
      resultLoanPeriod.classList.add("hidden");
      placeholder.classList.remove("hidden");
      message.classList.add("hidden");
    }

    detectButton.addEventListener("click", async () => {
      resetResult();
      const quantity = Number(quantityInput.value);
      if (!studentInput.value.trim()) return showMessage("학번을 먼저 입력해 주세요.");
      if (!Number.isInteger(quantity) || quantity < 1 || quantity > 20) {
        return showMessage("수량은 1개부터 20개 사이로 입력해 주세요.");
      }
      detectButton.disabled = true;
      detectButton.setAttribute("aria-busy", "true");
      detectButton.textContent = "인식 중...";
      try {
        const mockSelect = document.querySelector("#mock-equipment");
        const data = await postJson("/api/scans", {
          mock_equipment_id: mockSelect ? Number(mockSelect.value) : undefined,
          student_id: studentInput.value.trim(),
          action: selectedAction(),
        });
        scanToken = data.scan.token;
        scanDueDate = data.scan.due_date;
        scanLoanPeriodDays = data.scan.loan_period_days;
        document.querySelector("#result-name").textContent = data.scan.equipment_name;
        document.querySelector("#result-confidence").textContent = `${(data.scan.confidence * 100).toFixed(1)}%`;
        document.querySelector("#result-votes").textContent = `${data.votes}/${data.frame_count} 프레임 일치`;
        document.querySelector("#result-duration").textContent = `${(data.duration_ms / 1000).toFixed(2)}초`;
        placeholder.classList.add("hidden");
        resultPanel.classList.remove("hidden");
        syncLoanPeriodResult();
      } catch (error) {
        showMessage(error.message);
      } finally {
        detectButton.disabled = false;
        detectButton.removeAttribute("aria-busy");
        detectButton.textContent = "객체 인식 시작";
      }
    });

    confirmButton.addEventListener("click", async () => {
      const studentId = studentInput.value.trim();
      const quantity = Number(quantityInput.value);
      const action = selectedAction();
      if (!studentId) return showMessage("학번을 입력해 주세요.");
      if (!scanToken) return showMessage("먼저 기자재를 인식해 주세요.");
      confirmButton.disabled = true;
      confirmButton.setAttribute("aria-busy", "true");
      confirmButton.textContent = "저장 중...";
      try {
        const data = await postJson("/api/transactions", {
          scan_token: scanToken,
          student_id: studentId,
          action,
          quantity,
        });
        const tx = data.transaction;
        const actionName = tx.action === "loan" ? "대여" : "반납";
        const dueText = tx.due_date ? ` · 반납 예정 ${tx.due_date}` : "";
        showMessage(`${tx.equipment_name} ${tx.quantity}개 ${actionName} 처리가 완료되었습니다${dueText}. 현재 사용 가능 ${tx.available_qty}개`, true);
        studentInput.value = "";
        quantityInput.value = "1";
        scanToken = null;
        resultPanel.classList.add("hidden");
        placeholder.classList.remove("hidden");
      } catch (error) {
        showMessage(error.message);
      } finally {
        confirmButton.disabled = false;
        confirmButton.removeAttribute("aria-busy");
        confirmButton.textContent = "이 결과로 처리";
      }
    });

    retryButton.addEventListener("click", resetResult);
  }

  document.querySelectorAll("[data-utc]").forEach((cell) => {
    cell.textContent = formatDate(cell.dataset.utc);
  });
})();
