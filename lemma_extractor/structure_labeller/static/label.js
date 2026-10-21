(function () {
  const form = document.getElementById("label-form");
  if (!form) return;

  const exampleId = form.dataset.exampleId;
  const nextId = form.dataset.nextId;
  const mode = form.dataset.mode || "sample";
  const statusEl = document.getElementById("save-status");
  const progress = document.getElementById("progress");

  function selectedVerdict() {
    const el = form.querySelector('input[name="verdict"]:checked');
    return el ? el.value : "ok";
  }

  function collectSeparators() {
    const out = {};
    form.querySelectorAll("select[data-sep-index]").forEach((sel) => {
      const idx = sel.dataset.sepIndex;
      if (sel.value) out[String(idx)] = sel.value;
    });
    return out;
  }

  function formPayload() {
    return {
      verdict: selectedVerdict(),
      note: document.getElementById("note").value,
      uncertain: document.getElementById("uncertain").checked,
      separators: collectSeparators(),
      labelled: true,
    };
  }

  function labelUrl(id) {
    return `/label/${encodeURIComponent(id)}?mode=${encodeURIComponent(mode)}`;
  }

  async function save(andNext) {
    statusEl.textContent = "Saving…";
    statusEl.className = "save-status";
    try {
      const res = await fetch(
        `/api/save/${encodeURIComponent(exampleId)}?mode=${encodeURIComponent(mode)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(formPayload()),
        }
      );
      if (!res.ok) throw new Error(await res.text());
      const body = await res.json();
      if (progress && body.stats) {
        const suffix = mode === "sample" ? " (sample)" : "";
        progress.textContent = `${body.stats.labelled} / ${body.stats.total} labelled${suffix}`;
      }
      statusEl.textContent = "Saved";
      statusEl.className = "save-status ok";
      if (andNext && nextId) {
        window.location.href = labelUrl(nextId);
      }
    } catch (err) {
      statusEl.textContent = String(err.message || err);
      statusEl.className = "save-status err";
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    save(true);
  });

  const stay = document.getElementById("btn-save-stay");
  if (stay) {
    stay.addEventListener("click", () => save(false));
  }
})();
