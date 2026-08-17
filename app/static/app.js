const APP_BASE_PATH = window.APP_CONFIG?.appBasePath || "";
const ENVIRONMENT_GRID = document.querySelector("#environment-grid");
const GLOBAL_STATUS = document.querySelector("#global-status");
const HISTORY_LIST = document.querySelector("#history-list");
const USER_NAME = document.querySelector("#user-name");
const GLOBAL_CAPACITY = document.querySelector("#global-capacity");
const REFRESH_MS = 10_000;
const NAME_STORAGE_KEY = "aidcc-genesys-name";

let currentStatus = null;

function apiUrl(path) {
  return `${APP_BASE_PATH}${path}`;
}

function normalizedName() {
  return USER_NAME.value.trim().replace(/\s+/g, " ");
}

function minutesToLabel(totalMinutes) {
  if (totalMinutes < 60) {
    return `${totalMinutes} min`;
  }
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours < 24) {
    return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
  }
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return remainingHours ? `${days} d ${remainingHours} h` : `${days} d`;
}

function absoluteTime(isoString) {
  return new Intl.DateTimeFormat("cs-CZ", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(isoString));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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
    let detail = "Požadavek se nepodařilo dokončit.";
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

function environmentCaption(environment) {
  if (environment.is_full) {
    return "PLNO — další přihlášení by překročilo limit";
  }
  if (environment.free_slots === 1) {
    return "Zbývá poslední licence";
  }
  return `Volné licence: ${environment.free_slots}`;
}

function userAlreadyActive(environment) {
  const name = normalizedName().toLocaleLowerCase("cs-CZ");
  if (!name) {
    return false;
  }
  return environment.sessions.some(
    (session) => session.user_name.toLocaleLowerCase("cs-CZ") === name
  );
}

function renderEnvironment(environment) {
  const sessions = environment.sessions.length
    ? environment.sessions
        .map(
          (session) => `
            <div class="session-row ${session.stale ? "is-stale" : ""}">
              <div class="person-avatar">${escapeHtml(session.user_name.charAt(0).toUpperCase())}</div>
              <div class="session-copy">
                <strong>${escapeHtml(session.user_name)}</strong>
                <span>${minutesToLabel(session.age_minutes)} · od ${absoluteTime(session.checked_in_at)}</span>
              </div>
              ${session.stale ? '<span class="stale-badge">dlouho</span>' : ""}
              <button class="logout-button" type="button" data-session-id="${session.id}">Odhlásit</button>
            </div>
          `
        )
        .join("")
    : `<div class="empty-environment">Nikdo není přihlášen.</div>`;

  const allowExistingUser = userAlreadyActive(environment);
  const globalBlocked = currentStatus?.global_is_full && !allowExistingUser;
  const blocked = (environment.is_full || globalBlocked) && !allowExistingUser;
  const buttonText = blocked
    ? (globalBlocked ? "Celkový limit je plný" : "Prostředí je plné")
    : allowExistingUser
      ? `Pokračovat do ${environment.label}`
      : `Přihlásit se do ${environment.label}`;

  return `
    <article class="environment-card env-${environment.key}" data-state="${environment.status_level}">
      <div class="environment-head">
        <div>
          <span class="environment-tag">${environment.key === "prod" ? "PROD" : "TEST"}</span>
          <h2>${escapeHtml(environment.label)}</h2>
        </div>
        <div class="occupancy ${environment.status_level}">
          <strong>${environment.occupied_slots}</strong><span>/ ${environment.max_slots}</span>
        </div>
      </div>
      <p class="capacity-message">${environmentCaption(environment)}</p>
      <button
        class="enter-button"
        type="button"
        data-enter-environment="${environment.key}"
        ${blocked ? "disabled" : ""}
      >
        <span>${buttonText}</span>
        <span aria-hidden="true">→</span>
      </button>
      <div class="active-list">
        <div class="active-list-title">Aktuálně přihlášeni</div>
        ${sessions}
      </div>
    </article>
  `;
}

function renderBoard(status) {
  currentStatus = status;
  if (status.global_max_slots) {
    GLOBAL_CAPACITY.textContent = `Celkem ${status.global_occupied_slots} / ${status.global_max_slots}`;
    GLOBAL_CAPACITY.dataset.state = status.global_is_full ? "full" : "available";
  } else {
    GLOBAL_CAPACITY.textContent = `Celkem ${status.global_occupied_slots} aktivních`;
    GLOBAL_CAPACITY.dataset.state = "available";
  }
  ENVIRONMENT_GRID.innerHTML = status.environments.map(renderEnvironment).join("");
}

function renderHistory(history) {
  if (!history.items.length) {
    HISTORY_LIST.innerHTML = `<div class="history-empty">Zatím bez historie.</div>`;
    return;
  }

  HISTORY_LIST.innerHTML = history.items
    .map((item) => {
      const environmentLabel = item.environment === "prod" ? "PROD" : "TEST";
      const state = item.released_at ? "odhlášen" : "aktivní";
      return `
        <div class="history-row">
          <span class="history-env">${environmentLabel}</span>
          <strong>${escapeHtml(item.user_name)}</strong>
          <span>${state}</span>
          <span>${minutesToLabel(item.duration_minutes)}</span>
        </div>
      `;
    })
    .join("");
}

async function refreshBoard() {
  const [status, history] = await Promise.all([
    requestJson(apiUrl("/api/status")),
    requestJson(apiUrl("/api/history?limit=20")),
  ]);
  renderBoard(status);
  renderHistory(history);
}

async function enterEnvironment(environmentKey, button) {
  const userName = normalizedName();
  if (userName.length < 2) {
    GLOBAL_STATUS.textContent = "Nejdřív zadej své jméno.";
    USER_NAME.focus();
    return;
  }

  localStorage.setItem(NAME_STORAGE_KEY, userName);
  GLOBAL_STATUS.textContent = "Rezervuji licenci…";
  button.disabled = true;

  try {
    const result = await requestJson(apiUrl("/api/enter"), {
      method: "POST",
      body: JSON.stringify({
        user_name: userName,
        environment: environmentKey,
      }),
    });
    GLOBAL_STATUS.textContent = `${result.message} Otevírám Genesys…`;
    window.location.assign(result.redirect_url);
  } catch (error) {
    GLOBAL_STATUS.textContent = error.message;
    button.disabled = false;
    await refreshBoard();
  }
}

async function logoutSession(sessionId, button) {
  button.disabled = true;
  try {
    await requestJson(apiUrl("/api/check-out"), {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
    GLOBAL_STATUS.textContent = "Přihlášení bylo ukončeno.";
    await refreshBoard();
  } catch (error) {
    GLOBAL_STATUS.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

document.addEventListener("click", (event) => {
  const enterButton = event.target.closest("button[data-enter-environment]");
  if (enterButton) {
    enterEnvironment(enterButton.dataset.enterEnvironment, enterButton);
    return;
  }

  const logoutButton = event.target.closest("button[data-session-id]");
  if (logoutButton) {
    logoutSession(Number(logoutButton.dataset.sessionId), logoutButton);
  }
});

USER_NAME.addEventListener("input", () => {
  GLOBAL_STATUS.textContent = "";
  if (currentStatus) {
    renderBoard(currentStatus);
  }
});

const savedName = localStorage.getItem(NAME_STORAGE_KEY);
if (savedName) {
  USER_NAME.value = savedName;
}

refreshBoard().catch((error) => {
  GLOBAL_STATUS.textContent = error.message;
});

window.setInterval(() => {
  refreshBoard().catch((error) => {
    GLOBAL_STATUS.textContent = error.message;
  });
}, REFRESH_MS);
