(() => {
  const dialog = document.querySelector("#usage-guide");
  const openButton = document.querySelector("#usage-guide-open");
  if (!dialog || !openButton || typeof dialog.showModal !== "function") return;

  const storageKey = "equipment-manager:usage-guide:v1";
  let acknowledged = false;
  try {
    acknowledged = window.sessionStorage.getItem(storageKey) === "seen";
  } catch {
    // The guide remains usable when browser storage is unavailable.
  }

  openButton.hidden = false;
  openButton.addEventListener("click", () => {
    if (!dialog.open) dialog.showModal();
  });
  dialog.addEventListener("close", () => {
    try {
      window.sessionStorage.setItem(storageKey, "seen");
    } catch {
      // Closing the guide must never depend on storage permissions.
    }
  });

  if (!acknowledged) dialog.showModal();
})();
