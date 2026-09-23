// item.js
const itemForm = document.getElementById("item-form");
const itemStatus = document.getElementById("item-save-status");

itemForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(itemForm);
  const nullableId = (name) => data.get(name) ? Number(data.get(name)) : null;
  const lines = (name) => String(data.get(name) || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  let attributes;
  try {
    attributes = JSON.parse(String(data.get("attributes") || "{}"));
    if (attributes === null || typeof attributes !== "object" || Array.isArray(attributes)) {
      throw new Error("Attributes must be a JSON object.");
    }
  } catch (_error) {
    itemStatus.textContent = "Attributes must be a JSON object.";
    return;
  }
  const payload = {
    name: String(data.get("name") || "").trim(),
    description: String(data.get("description") || "").trim() || null,
    state: data.get("state"),
    quantity: Number(data.get("quantity")),
    category_id: nullableId("category_id"),
    location_id: nullableId("location_id"),
    attributes,
    aliases: lines("aliases"),
    tags: lines("tags"),
  };
  const creating = !itemForm.dataset.itemId;
  itemStatus.textContent = "Saving…";
  try {
    const response = await fetch(creating ? "/api/items" : `/api/items/${itemForm.dataset.itemId}`, {
      method: creating ? "POST" : "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) {
      itemStatus.textContent = typeof body.detail === "string" ? body.detail : "Please check the form values.";
      return;
    }
    if (creating) {
      window.location.assign(`/items/${body.id}`);
    } else {
      window.location.reload();
    }
  } catch (_error) {
    itemStatus.textContent = "Save failed. Please retry.";
  }
});
