// tree.js
for (const form of document.querySelectorAll("[data-tree-form]")) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const status = form.querySelector("[data-tree-status]");
    const kind = form.dataset.kind;
    const nodeId = form.dataset.nodeId;
    const payload = {
      name: String(data.get("name") || "").trim(),
      description: String(data.get("description") || "").trim() || null,
      parent_id: data.get("parent_id") ? Number(data.get("parent_id")) : null,
    };
    status.textContent = "Saving…";
    try {
      const response = await fetch(nodeId ? `/api/${kind}/${nodeId}` : `/api/${kind}`, {
        method: nodeId ? "PATCH" : "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const body = await response.json();
      if (!response.ok) {
        status.textContent = typeof body.detail === "string" ? body.detail : "Please check the form values.";
        return;
      }
      if (nodeId) {
        window.location.reload();
      } else {
        window.location.assign(`/${kind}/${body.id}/edit`);
      }
    } catch (_error) {
      status.textContent = "Save failed. Please retry.";
    }
  });
}
