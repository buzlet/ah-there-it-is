document.addEventListener("submit", async (event) => {
  const form = event.target.closest(".recovery-form");
  if (!form) return;
  event.preventDefault();

  const status = form.querySelector(".status");
  const note = form.elements.note.value.trim();
  const acknowledged = form.elements.ack.checked;
  if (!note || !acknowledged) return;

  const sourceKey = form.dataset.sourceKey;
  const newKey = "recovery-" + crypto.randomUUID();
  const button = form.querySelector("button");
  button.disabled = true;
  status.textContent = "Running explicit recovery attempt…";

  try {
    const response = await fetch(
      "/api/chat-requests/" + encodeURIComponent(sourceKey) + "/recover",
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          new_request_key: newKey,
          note,
          acknowledge_duplicate_risk: true
        })
      }
    );
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail || "Recovery request failed");
    }
    status.textContent = "Recovery completed as " + newKey + ". Reloading…";
    location.reload();
  } catch (error) {
    status.textContent = String(error.message || error);
    button.disabled = false;
  }
});
