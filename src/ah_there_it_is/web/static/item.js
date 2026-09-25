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
    category_id: nullableId("category_id"),
    attributes,
    aliases: lines("aliases"),
    tags: lines("tags"),
  };
  if (data.has("state")) payload.state = data.get("state");
  if (data.has("quantity_mode")) {
    payload.quantity_mode = data.get("quantity_mode");
    payload.quantity = data.get("quantity_mode") === "unknown" ? null : Number(data.get("quantity"));
  }

  const creating = !itemForm.dataset.itemId;
  if (creating) payload.location_id = nullableId("location_id");
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

const updateRestoreLocation = (form) => {
  const selectedMode = form.querySelector('input[name="location_mode"]:checked')?.value;
  const location = form.querySelector('select[name="location_id"]');
  if (!location) return;
  const known = selectedMode === "known";
  location.disabled = !known;
  location.required = known;
};

document.querySelectorAll('input[name="location_mode"]').forEach((input) => {
  input.addEventListener("change", () => updateRestoreLocation(input.form));
});
document.querySelectorAll('[data-transition-kind="restore"]').forEach(updateRestoreLocation);

document.querySelectorAll("form[data-transition-url]").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = form.querySelector('[role="status"]');
    const data = new FormData(form);
    const kind = form.dataset.transitionKind;
    const payload = {};
    if (kind === "move") {
      payload.location_id = Number(data.get("location_id"));
    } else if (kind === "restore") {
      payload.state = data.get("state");
      payload.location_id = data.get("location_mode") === "known"
        ? Number(data.get("location_id"))
        : null;
    } else if (kind === "quantity") {
      payload.quantity_mode = data.get("quantity_mode");
      payload.quantity = data.get("quantity_mode") === "unknown" ? null : Number(data.get("quantity"));
      payload.reason = data.get("reason");
      payload.reason_source = "explicit";
    } else if (kind === "remove") {
      payload.reason = data.get("reason");
      payload.reason_source = "explicit";
    }

    if (status) status.textContent = "Saving…";
    try {
      const response = await fetch(form.dataset.transitionUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: Object.keys(payload).length ? JSON.stringify(payload) : undefined,
      });
      const body = await response.json();
      if (!response.ok) {
        if (status) {
          status.textContent = typeof body.detail === "string" ? body.detail : "Please check the action values.";
        }
        return;
      }
      window.location.reload();
    } catch (_error) {
      if (status) status.textContent = "Action failed. Please retry.";
    }
  });
});
