const ENVIRONMENT_GRID = document.querySelector("#environment-grid");
const GLOBAL_STATUS = document.querySelector("#global-status");
const HISTORY_LIST = document.querySelector("#history-list");
const USER_NAME = document.querySelector("#user-name");
const GLOBAL_CAPACITY = document.querySelector("#global-capacity");
const REFRESH_MS = 10_000;
const NAME_STORAGE_KEY = "aidcc-genesys-name";
let currentStatus = null;

function normalizedName() { return USER_NAME.value.trim().replace(/\s+/g, " "); }
function minutesToLabel(totalMinutes) {
  if (totalMinutes < 60) return `${totalMinutes} min`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours < 24) return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return remainingHours ? `${days} d ${remainingHours} h` : `${days} d`;
}
function absoluteTime(isoString) {
  return new Intl.DateTimeFormat("cs-CZ", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(isoString));
}
function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
async function requestJson(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  if (!response.ok) {
    let detail = "Požadavek se nepodařilo dokončit.";
    try { const payload = await response.json(); detail = payload.detail || detail; } catch { detail = response.statusText || detail; }
    throw new Error(detail);
  }
  return response.json();
}
function environmentMeta(environment) {
  return environment.key === "prod"
    ? { tag: "PRODUKCE", description: "Ostré produkční prostředí", location: "Germany · .de" }
    : { tag: "TEST", description: "Testovací a vývojové prostředí", location: "Ireland · .ie" };
}
function environmentCaption(environment) {
  if (environment.is_full) return "Plná kapacita";
  if (environment.free_slots === 1) return "Poslední volná licence";
  if (environment.free_slots === environment.max_slots) return "Všechny licence jsou volné";
  return `${environment.free_slots} volné licence`;
}
function userAlreadyActive(environment) {
  const name = normalizedName().toLocaleLowerCase("cs-CZ");
  return Boolean(name) && environment.sessions.some((session) => session.user_name.toLocaleLowerCase("cs-CZ") === name);
}
function renderLicenseMeter(environment) {
  return Array.from({ length: environment.max_slots }, (_, index) => `<span class="license-segment ${index < environment.occupied_slots ? "used" : "free"}" aria-hidden="true"></span>`).join("");
}
function renderSessions(environment) {
  if (!environment.sessions.length) return `<div class="empty-environment"><span class="empty-dot"></span>Nikdo tu teď není přihlášen.</div>`;
  return environment.sessions.map((session) => `
    <div class="session-row ${session.stale ? "is-stale" : ""}">
      <div class="person-avatar">${escapeHtml(session.user_name.charAt(0).toUpperCase())}</div>
      <div class="session-copy"><strong>${escapeHtml(session.user_name)}</strong><span>Přihlášen ${minutesToLabel(session.age_minutes)} · od ${absoluteTime(session.checked_in_at)}</span></div>
      ${session.stale ? '<span class="stale-badge">dlouho aktivní</span>' : ""}
      <button class="logout-button" type="button" data-session-id="${session.id}">Odhlásit</button>
    </div>`).join("");
}
function renderEnvironment(environment) {
  const meta = environmentMeta(environment);
  const allowExistingUser = userAlreadyActive(environment);
  const globalBlocked = currentStatus?.global_is_full && !allowExistingUser;
  const blocked = (environment.is_full || globalBlocked) && !allowExistingUser;
  let buttonText = `Vstoupit do ${meta.tag}`;
  if (allowExistingUser) buttonText = `Pokračovat do ${meta.tag}`;
  else if (globalBlocked) buttonText = "Celkový limit licencí je plný";
  else if (environment.is_full) buttonText = `${meta.tag} je plný`;
  return `
    <article class="environment-card env-${environment.key}" data-state="${environment.status_level}">
      <div class="environment-top">
        <div><span class="environment-tag">${meta.tag}</span><h3>${escapeHtml(environment.label)}</h3><p class="environment-description">${meta.description}</p></div>
        <div class="capacity-pill ${environment.status_level}"><strong>${environment.occupied_slots}</strong><span>/ ${environment.max_slots} obsazeno</span></div>
      </div>
      <div class="target-box"><span class="target-label">Cíl přihlášení</span><strong>${escapeHtml(environment.url)}</strong><span>${meta.location}</span></div>
      <div class="capacity-row"><div class="license-meter" aria-label="${environment.occupied_slots} z ${environment.max_slots} licencí obsazeno">${renderLicenseMeter(environment)}</div><span class="capacity-caption">${environmentCaption(environment)}</span></div>
      <button class="enter-button" type="button" data-enter-environment="${environment.key}" ${blocked ? "disabled" : ""}><span>${buttonText}</span><span class="button-arrow" aria-hidden="true">→</span></button>
      <div class="active-list"><div class="active-list-title"><span>Aktuálně přihlášeni</span><span>${environment.occupied_slots}</span></div>${renderSessions(environment)}</div>
    </article>`;
}
function renderBoard(status) {
  currentStatus = status;
  if (status.global_max_slots) {
    const free = Math.max(0, status.global_max_slots - status.global_occupied_slots);
    GLOBAL_CAPACITY.innerHTML = `<span class="summary-label">Sdílené licence celkem</span><div class="summary-value"><strong>${status.global_occupied_slots} / ${status.global_max_slots}</strong><span>${status.global_is_full ? "PLNO" : `${free} volné`}</span></div>`;
    GLOBAL_CAPACITY.dataset.state = status.global_is_full ? "full" : "available";
  } else {
    GLOBAL_CAPACITY.innerHTML = `<span class="summary-label">Aktivní přihlášení</span><div class="summary-value"><strong>${status.global_occupied_slots}</strong><span>bez společného limitu</span></div>`;
    GLOBAL_CAPACITY.dataset.state = "available";
  }
  ENVIRONMENT_GRID.innerHTML = status.environments.map(renderEnvironment).join("");
}
function renderHistory(history) {
  if (!history.items.length) { HISTORY_LIST.innerHTML = `<div class="history-empty">Zatím bez historie.</div>`; return; }
  HISTORY_LIST.innerHTML = history.items.map((item) => `<div class="history-row"><span class="history-env env-${item.environment}">${item.environment === "prod" ? "PROD" : "TEST"}</span><strong>${escapeHtml(item.user_name)}</strong><span>${item.released_at ? "odhlášen" : "aktivní"}</span><span>${minutesToLabel(item.duration_minutes)}</span></div>`).join("");
}
function showMessage(message, kind = "info") { GLOBAL_STATUS.textContent = message; GLOBAL_STATUS.dataset.kind = message ? kind : ""; }
async function refreshBoard() {
  const [status, history] = await Promise.all([requestJson("/api/status"), requestJson("/api/history?limit=20")]);
  renderBoard(status); renderHistory(history);
}
async function enterEnvironment(environmentKey, button) {
  const userName = normalizedName();
  if (userName.length < 2) { showMessage("Nejdřív zadej své jméno.", "error"); USER_NAME.focus(); return; }
  localStorage.setItem(NAME_STORAGE_KEY, userName); showMessage("Rezervuji licenci a připravuji přesměrování…", "info"); button.disabled = true;
  try {
    const result = await requestJson("/api/enter", { method: "POST", body: JSON.stringify({ user_name: userName, environment: environmentKey }) });
    showMessage(`${result.message} Otevírám Genesys…`, "success"); window.location.assign(result.redirect_url);
  } catch (error) { showMessage(error.message, "error"); button.disabled = false; await refreshBoard(); }
}
async function logoutSession(sessionId, button) {
  button.disabled = true;
  try { await requestJson("/api/check-out", { method: "POST", body: JSON.stringify({ session_id: sessionId }) }); showMessage("Přihlášení bylo ukončeno a licence je znovu volná.", "success"); await refreshBoard(); }
  catch (error) { showMessage(error.message, "error"); } finally { button.disabled = false; }
}
document.addEventListener("click", (event) => {
  const enterButton = event.target.closest("button[data-enter-environment]");
  if (enterButton) { enterEnvironment(enterButton.dataset.enterEnvironment, enterButton); return; }
  const logoutButton = event.target.closest("button[data-session-id]");
  if (logoutButton) logoutSession(Number(logoutButton.dataset.sessionId), logoutButton);
});
USER_NAME.addEventListener("input", () => { showMessage(""); if (currentStatus) renderBoard(currentStatus); });
const savedName = localStorage.getItem(NAME_STORAGE_KEY); if (savedName) USER_NAME.value = savedName;
refreshBoard().catch((error) => showMessage(`Nepodařilo se načíst stav licencí: ${error.message}`, "error"));
window.setInterval(() => refreshBoard().catch((error) => showMessage(`Nepodařilo se obnovit stav licencí: ${error.message}`, "error")), REFRESH_MS);
