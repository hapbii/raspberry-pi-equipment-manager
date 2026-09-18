(() => {
  const editor = document.querySelector('#equipment-editor');
  if (!editor) return;
  const all = editor.querySelector('#equipment-select-all');
  const count = editor.querySelector('#equipment-selection-count');
  const message = editor.querySelector('#equipment-edit-message');
  const bulkButtons = [...editor.querySelectorAll('[data-bulk-action]')];
  const fields = ['total_qty', 'available_qty', 'loan_period_days'];
  const rows = () => [...editor.querySelectorAll('.inventory-edit')];
  let busy = false;
  let controller = null;
  const selected = () => rows().filter(row => row.querySelector('.equipment-select').checked);
  const announce = (text, error = false) => {
    message.textContent = text;
    message.className = error ? 'flash flash-error' : 'flash flash-success';
  };
  function refreshSelection() {
    const total = rows().length;
    const n = selected().length;
    count.textContent = `${n}개 선택`;
    all.checked = total > 0 && n === total;
    all.indeterminate = n > 0 && n < total;
    all.disabled = busy || total === 0;
    bulkButtons.forEach(button => { button.disabled = busy || n === 0; });
  }
  function refreshSummary() {
    document.querySelector('#equipment-kind-count').textContent = rows().length;
    document.querySelector('#equipment-total-count').textContent = rows().reduce(
      (sum, row) => sum + JSON.parse(row.dataset.original).total_qty, 0);
  }
  function markChanged(row) {
    const original = JSON.parse(row.dataset.original);
    row.classList.toggle('equipment-dirty', fields.some(key => row.elements[key].value !== String(original[key])));
  }
  async function save(action, targets) {
    if (busy) return;
    if (!targets.length || targets.length > 100) return announce('기자재를 1~100개 선택해 주세요.', true);
    if (action === 'update') {
      for (const row of targets) {
        if (!row.reportValidity()) return;
      }
    }
    if (action === 'remove' && !window.confirm(`선택한 기자재 ${targets.length}개를 삭제할까요? 미반납 항목이 있으면 전체 삭제가 취소되고 거래 기록은 보존됩니다.`)) return;
    const items = targets.map(row => {
      const item = { id: Number(row.dataset.equipmentId), expected: JSON.parse(row.dataset.original) };
      if (action === 'update') fields.forEach(key => { item[key] = Number(row.elements[key].value); });
      return item;
    });
    busy = true;
    editor.querySelectorAll('input, button').forEach(input => { input.disabled = true; });
    announce('선택 항목을 처리하고 있습니다…');
    controller = new AbortController();
    const timeout = window.setTimeout(() => controller?.abort(), 30000);
    try {
      const response = await fetch(editor.dataset.endpoint, {
        method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content },
        body: JSON.stringify({ action, items }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        if (response.status >= 500) throw new Error('서버 응답을 확인하지 못했습니다. 다른 탭에서 반영 여부를 확인한 뒤 다시 시도하세요.');
        throw new Error(data.error || '저장하지 못했습니다. 입력값은 유지됩니다.');
      }
      targets.forEach(row => {
        if (action === 'remove') return row.remove();
        const updated = data.items.find(item => item.id === Number(row.dataset.equipmentId));
        row.dataset.original = JSON.stringify(updated);
        fields.forEach(key => { row.elements[key].value = updated[key]; });
        row.querySelector('.equipment-select').checked = false;
        markChanged(row);
      });
      refreshSummary();
      announce(`${targets.length}개 기자재 ${action === 'update' ? '수정' : '삭제'} 완료. 선택하지 않은 항목의 입력값은 그대로 유지됩니다.`);
    } catch (error) {
      announce(error instanceof SyntaxError || error.name === 'AbortError' || error instanceof TypeError
        ? '처리 결과를 확인하지 못했습니다. 입력값은 유지됩니다. 중복 요청 전에 다른 탭에서 반영 여부를 확인하세요.'
        : error.message, true);
    } finally {
      window.clearTimeout(timeout);
      controller = null;
      busy = false;
      editor.querySelectorAll('input, button').forEach(input => { input.disabled = false; });
      refreshSelection();
    }
  }
  all.addEventListener('change', () => {
    rows().forEach(row => { row.querySelector('.equipment-select').checked = all.checked; });
    refreshSelection();
  });
  rows().forEach(row => {
    // One shared confirmation path for row and bulk deletion.
    row.querySelector('[data-row-action="remove"]').removeAttribute('onclick');
    row.addEventListener('submit', event => {
      event.preventDefault();
      save(event.submitter?.dataset.rowAction || 'update', [row]);
    });
    row.addEventListener('change', refreshSelection);
    row.addEventListener('input', () => markChanged(row));
  });
  bulkButtons.forEach(button => button.addEventListener('click', () => save(button.dataset.bulkAction, selected())));
  window.addEventListener('pagehide', () => controller?.abort());
  window.addEventListener('beforeunload', event => {
    if (busy || rows().some(row => row.classList.contains('equipment-dirty'))) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  refreshSelection();
})();
