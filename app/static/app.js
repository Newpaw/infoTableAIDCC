const CHECK_IN_FORM = document.querySelector("#check-in-form");
const FORM_STATUS = document.querySelector("#form-status");
const ACTIVE_SESSIONS = document.querySelector("#active-sessions");
const HISTORY_LIST = document.querySelector("#history-list");
const SUMMARY_CARD = document.querySelector("#summary-card");
const OCCUPIED_SLOTS = document.querySelector("#occupied-slots");
const FREE_SLOTS = document.querySelector("#free-slots");
const SUMMARY_MESSAGE = document.querySelector("#summary-message");

const REFRESH_MS = 15_000;

function minutesToLabel(totalMinutes) {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) {
    return `${minutes}m`;
  }
  if (minutes === 0) {
    return `${hours}h`;
  }
  return `${hours}h ${minutes}m`;
}

function absoluteTime(isoString) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(isoString));
}

function relativeStamp(totalMinutes) {
  if (totalMinutes < 1) {
    return "just now";
  }
  return `${minutesToLabel(totalMinutes)} ago`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = "Request failed.";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }

  return response.json();
}

function renderSummary(status) {
  SUMMARY_CARD.dataset.state = status.status_level;
  OCCUPIED_SLOTS.textContent = String(status.occupied_slots);
  FREE_SLOTS.textContent = `${status.free_slots} free`;

  if (status.is_full) {
    SUMMARY_MESSAGE.textContent = "All shared slots are currently occupied.";
    return;
  }

  if (status.status_level === "warning") {
    SUMMARY_MESSAGE.textContent = `Only ${status.free_slots} slot left before the board is full.`;
    return;
  }

  SUMMARY_MESSAGE.textContent = `${status.free_slots} slots are currently available.`;
}

function renderSessions(status) {
  if (!status.sessions.length) {
    ACTIVE_SESSIONS.innerHTML = `<div class="empty-state">No one is checked in right now. It is safe to log into Genesys Cloud.</div>`;
    return;
  }

  ACTIVE_SESSIONS.innerHTML = status.sessions
    .map(
      (session) => `
        <article class="session-card" data-stale="${session.stale}">
          <div class="session-head">
            <div>
              <p class="session-name">${escapeHtml(session.user_name)}</p>
              <p class="session-meta">Checked in ${relativeStamp(session.age_minutes)} | ${absoluteTime(session.checked_in_at)}</p>
            </div>
            <span class="session-badge ${session.stale ? "badge-stale" : "badge-active"}">
              ${session.stale ? "Stale" : "Active"}
            </span>
          </div>
          <p class="session-note">${session.note ? escapeHtml(session.note) : "No note provided."}</p>
          <div class="session-actions">
            <span class="session-meta">Elapsed: ${minutesToLabel(session.age_minutes)}</span>
            <div>
              <button class="ghost-button" type="button" data-action="checkout" data-session-id="${session.id}">Release slot</button>
              <button class="ghost-button" type="button" data-action="force-release" data-session-id="${session.id}">Force release</button>
            </div>
          </div>
        </article>
      `
    )
    .join("");
}

function renderHistory(history) {
  if (!history.items.length) {
    HISTORY_LIST.innerHTML = `<div class="empty-state">No session history yet.</div>`;
    return;
  }

  HISTORY_LIST.innerHTML = history.items
    .map((item) => {
      const reason = item.release_reason || "active";
      const badgeClass = {
        manual: "badge-manual",
        force: "badge-force",
        auto: "badge-auto",
        active: "badge-active",
      }[reason] || "badge-manual";

      return `
        <article class="history-item">
          <div class="history-head">
            <div>
              <p class="history-name">${escapeHtml(item.user_name)}</p>
              <p class="history-meta">Started ${absoluteTime(item.checked_in_at)}</p>
            </div>
            <span class="history-badge ${badgeClass}">${escapeHtml(reason)}</span>
          </div>
          <p class="history-note">${item.note ? escapeHtml(item.note) : "No note provided."}</p>
          <p class="history-meta">
            ${
              item.released_at
                ? `Released ${absoluteTime(item.released_at)} | Duration ${minutesToLabel(item.duration_minutes)}`
                : `Still active | Duration ${minutesToLabel(item.duration_minutes)}`
            }
          </p>
        </article>
      `;
    })
    .join("");
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function refreshBoard() {
  const [status, history] = await Promise.all([
    requestJson("/api/status"),
    requestJson("/api/history"),
  ]);

  renderSummary(status);
  renderSessions(status);
  renderHistory(history);
}

CHECK_IN_FORM.addEventListener("submit", async (event) => {
  event.preventDefault();
  FORM_STATUS.textContent = "Saving your check-in...";

  const payload = {
    user_name: document.querySelector("#user-name").value,
    note: document.querySelector("#user-note").value,
  };

  try {
    await requestJson("/api/check-in", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    CHECK_IN_FORM.reset();
    FORM_STATUS.textContent = "Slot reserved.";
    await refreshBoard();
  } catch (error) {
    FORM_STATUS.textContent = error.message;
  }
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }

  const sessionId = Number(button.dataset.sessionId);
  const action = button.dataset.action;
  const endpoint =
    action === "force-release"
      ? `/api/force-release/${sessionId}`
      : "/api/check-out";

  try {
    button.disabled = true;
    await requestJson(endpoint, {
      method: "POST",
      body: action === "force-release" ? null : JSON.stringify({ session_id: sessionId }),
    });
    FORM_STATUS.textContent =
      action === "force-release" ? "Session force-released." : "Slot released.";
    await refreshBoard();
  } catch (error) {
    FORM_STATUS.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

refreshBoard().catch((error) => {
  FORM_STATUS.textContent = error.message;
});

window.setInterval(() => {
  refreshBoard().catch((error) => {
    FORM_STATUS.textContent = error.message;
  });
}, REFRESH_MS);
