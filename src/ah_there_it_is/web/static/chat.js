const STORAGE_KEY = "ah-there-it-is-conversation-id";
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
  if (!conversationId) return;
  const response = await fetch(`/api/conversations/${conversationId}`);
  if (!response.ok) { localStorage.removeItem(STORAGE_KEY); conversationId = null; return; }
  const data = await response.json();
  for (const message of data.messages) addMessage(message.role, message.content, message.run_id, message.rating, message.comment);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  addMessage("user", message);
  input.value = "";
  input.disabled = true;
  statusNode.textContent = "Working…";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message, conversation_id: conversationId}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Request failed");
    conversationId = data.conversation_id;
    localStorage.setItem(STORAGE_KEY, String(conversationId));
    addMessage("assistant", data.content, data.run_id);
    statusNode.textContent = `run #${data.run_id}, ${data.rounds} round(s)`;
  } catch (error) {
    statusNode.textContent = error.message;
  } finally {
    input.disabled = false;
    input.focus();
  }
});

newButton.addEventListener("click", () => {
  localStorage.removeItem(STORAGE_KEY);
  conversationId = null;
  log.textContent = "";
  statusNode.textContent = "New conversation.";
  input.focus();
});

restoreConversation();
