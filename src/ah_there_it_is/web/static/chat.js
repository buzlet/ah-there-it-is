const STORAGE_KEY = "ah-there-it-is-conversation-id";
const PENDING_KEY = "ah-there-it-is-pending-chat";
const log = document.getElementById("chat-log");
const form = document.getElementById("chat-form");
const input = document.getElementById("message");
const statusNode = document.getElementById("chat-status");
const newButton = document.getElementById("new-conversation");
let conversationId = Number(localStorage.getItem(STORAGE_KEY)) || null;

function addMessage(role, content, runId = null, rating = null, comment = null) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  const text = document.createElement("div");
  text.textContent = content;
  node.appendChild(text);
  if (role === "assistant" && runId) node.appendChild(feedbackControls(runId, rating, comment));
  log.appendChild(node);
  node.scrollIntoView({block: "nearest"});
}

function feedbackControls(runId, currentRating, currentComment) {
  const box = document.createElement("div");
  box.className = "feedback";
  const label = document.createElement("span");
  label.textContent = "Rate:";
  box.appendChild(label);
  const comment = document.createElement("input");
  comment.type = "text";
  comment.maxLength = 2000;
  comment.placeholder = "optional note";
  comment.value = currentComment || "";
  for (let rating = 1; rating <= 5; rating++) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = String(rating);
    button.title = `Rate this run ${rating}/5`;
    if (rating === currentRating) button.classList.add("selected");
    button.addEventListener("click", async () => {
      const response = await fetch(`/api/runs/${runId}/feedback`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({rating, comment: comment.value || null}),
      });
      if (!response.ok) { statusNode.textContent = "Could not save rating."; return; }
      for (const sibling of box.querySelectorAll("button")) sibling.classList.remove("selected");
      button.classList.add("selected");
      statusNode.textContent = `Saved rating ${rating}/5 for run #${runId}.`;
    });
    box.appendChild(button);
  }
  box.appendChild(comment);
  return box;
}

async function restoreConversation() {
  if (!conversationId) return [];
  const response = await fetch(`/api/conversations/${conversationId}`);
  if (!response.ok) {
    localStorage.removeItem(STORAGE_KEY);
    conversationId = null;
    return [];
  }
  const data = await response.json();
  for (const message of data.messages) {
    addMessage(message.role, message.content, message.run_id, message.rating, message.comment);
  }
  return data.messages;
}

function makeRequestKey() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

async function sendPending(pending, displayUser = true) {
  if (displayUser) addMessage("user", pending.message);
  input.disabled = true;
  statusNode.textContent = "Working…";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(pending),
    });
    const data = await response.json();
    if (!response.ok) {
      if (response.status !== 425) localStorage.removeItem(PENDING_KEY);
      throw new Error(data.detail || "Request failed");
    }
    localStorage.removeItem(PENDING_KEY);
    conversationId = data.conversation_id;
    localStorage.setItem(STORAGE_KEY, String(conversationId));
    addMessage("assistant", data.content, data.run_id);
    const replay = data.replayed ? ", replayed safely" : "";
    statusNode.textContent = `run #${data.run_id}, ${data.rounds} round(s)${replay}`;
  } catch (error) {
    statusNode.textContent = error.message;
  } finally {
    const stillPending = localStorage.getItem(PENDING_KEY) !== null;
    input.disabled = stillPending;
    if (!stillPending) input.focus();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || localStorage.getItem(PENDING_KEY)) return;
  const pending = {
    message,
    conversation_id: conversationId,
    request_key: makeRequestKey(),
  };
  localStorage.setItem(PENDING_KEY, JSON.stringify(pending));
  input.value = "";
  await sendPending(pending, true);
});

newButton.addEventListener("click", () => {
  localStorage.removeItem(STORAGE_KEY);
  conversationId = null;
  log.textContent = "";
  statusNode.textContent = "New conversation.";
  input.focus();
});

async function bootstrapChat() {
  const restored = await restoreConversation();
  const raw = localStorage.getItem(PENDING_KEY);
  if (!raw) return;
  try {
    const pending = JSON.parse(raw);
    const alreadyRendered = restored.some(
      (message) => message.role === "user" && message.content === pending.message
    );
    await sendPending(pending, !alreadyRendered);
  } catch {
    localStorage.removeItem(PENDING_KEY);
    input.disabled = false;
  }
}

bootstrapChat();
