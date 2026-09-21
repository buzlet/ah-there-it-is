// experiment.js
(() => {
  const form = document.querySelector('#experiment-review');
  if (!form) return;
  const status = document.querySelector('#review-status');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const runId = form.dataset.runId;
    const data = new FormData(form);
    const rawRating = data.get('variant_rating');
    const payload = {
      choice: data.get('choice'),
      variant_rating: rawRating ? Number(rawRating) : null,
      comment: data.get('comment') || null,
    };
    const response = await fetch(`/api/experiments/${runId}/review`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    status.textContent = response.ok ? 'Saved.' : 'Save failed.';
  });
})();
