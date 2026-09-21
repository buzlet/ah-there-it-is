const form = document.getElementById("item-edit-form");
const statusNode = document.getElementById("item-save-status");

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(form);
  const nullableId = (name) => data.get(name) ? Number(data.get(name)) : null;
  const payload = {
    name: String(data.get("name") || "").trim(),
    description: String(data.get("description") || "").trim() || null,
    state: data.get("state"),
    quantity: Number(data.get("quantity")),
    category_id: nullableId("category_id"),
    location_id: nullableId("location_id"),
  };
  statusNode.textContent = "Saving…";
  const response = await fetch(`/api/items/${form.dataset.itemId}`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.json();
    statusNode.textContent = body.detail || "Save failed.";
    return;
  }
  statusNode.textContent = "Saved.";
  window.location.reload();
});
