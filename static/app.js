const categoryEmoji = {
  Frutas: "🍊",
  Verduras: "🥬",
  Lácteos: "🥛",
  Proteínas: "🥚",
  Despensa: "🫙",
  Otros: "🧺",
};

let dashboardData = { foods: [], stats: { active: 0, urgent: 0, used: 0, wasted: 0 } };
let toastTimer;
let authMode = "login";

const escapeHtml = (value) =>
  String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "No se pudo completar la acción.");
  return result;
}

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
}

function setAuthMode(mode) {
  authMode = mode;
  const registering = mode === "register";
  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    const active = button.dataset.authMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const nameField = document.getElementById("auth-name");
  nameField.required = registering;
  document.getElementById("auth-name-wrap").classList.toggle("hidden", !registering);
  document.getElementById("auth-password").autocomplete = registering ? "new-password" : "current-password";
  document.getElementById("auth-submit").innerHTML = registering
    ? "Crear cuenta <span>→</span>"
    : "Iniciar sesión <span>→</span>";
  document.getElementById("auth-error").classList.add("hidden");
}

function showAuthError(message) {
  const error = document.getElementById("auth-error");
  error.textContent = message;
  error.classList.remove("hidden");
}

async function enterApp(user) {
  document.getElementById("auth-screen").classList.remove("visible");
  const name = user.name || "Mi hogar";
  document.getElementById("profile-name").textContent = name;
  document.getElementById("profile-email").textContent = user.email;
  const initial = name.trim().charAt(0).toLocaleUpperCase("es");
  document.querySelector(".profile .avatar").textContent = initial;
  document.getElementById("topbar-avatar").textContent = initial;
  const welcomeTitle = document.getElementById("welcome-title");
  welcomeTitle.firstChild.textContent = "Hola, " + name + " ";
  switchView(location.hash.slice(1) || "inicio");
  await refreshData();
}

function expiryLabel(food) {
  if (food.days_left < 0) return "Venció hace " + Math.abs(food.days_left) + (Math.abs(food.days_left) === 1 ? " día" : " días");
  if (food.days_left === 0) return "Vence hoy";
  if (food.days_left === 1) return "Vence mañana";
  return "Vence en " + food.days_left + " días";
}

function expiryClass(food) {
  if (food.days_left < 0) return "expired";
  return food.days_left <= 3 ? "" : "fresh";
}

function foodRow(food) {
  return `<div class="food-row">
    <div class="food-emoji">${categoryEmoji[food.category] || "🧺"}</div>
    <div class="food-row-copy"><strong>${escapeHtml(food.name)}</strong><small>${escapeHtml(food.quantity)} ${escapeHtml(food.unit)} · ${escapeHtml(food.category)}</small></div>
    <span class="expiry-badge ${expiryClass(food)}">${escapeHtml(expiryLabel(food))}</span>
  </div>`;
}

function renderDashboard() {
  const { foods, stats } = dashboardData;
  document.getElementById("stat-active").textContent = stats.active;
  document.getElementById("stat-urgent").textContent = stats.urgent;
  document.getElementById("stat-used").textContent = stats.used;
  document.getElementById("stat-wasted").textContent = stats.wasted;
  document.getElementById("nav-count").textContent = stats.active;
  const priorities = foods.filter((food) => food.days_left <= 3).slice(0, 3);
  document.getElementById("priority-list").innerHTML = priorities.length
    ? priorities.map(foodRow).join("")
    : '<p class="no-items">Todo al día. Agrega alimentos y aquí verás cuáles usar primero.</p>';
}

function renderPantry() {
  const query = document.getElementById("food-search").value.trim().toLocaleLowerCase("es");
  const filter = document.getElementById("food-filter").value;
  const foods = dashboardData.foods.filter((food) => {
    const matchesQuery = food.name.toLocaleLowerCase("es").includes(query);
    const matchesFilter = filter === "all" || (filter === "urgent" ? food.days_left <= 3 : food.days_left > 3);
    return matchesQuery && matchesFilter;
  });
  const list = document.getElementById("pantry-list");
  const empty = document.getElementById("pantry-empty");
  if (dashboardData.foods.length === 0) {
    list.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }
  list.classList.remove("hidden");
  empty.classList.add("hidden");
  list.innerHTML = foods.length ? foods.map((food) => `
    <article class="pantry-card">
      <div class="pantry-card-top"><span class="pantry-emoji">${categoryEmoji[food.category] || "🧺"}</span><button class="more-button" data-delete="${food.id}" aria-label="Quitar ${escapeHtml(food.name)}">×</button></div>
      <h3>${escapeHtml(food.name)}</h3><p class="pantry-meta">${escapeHtml(food.quantity)} ${escapeHtml(food.unit)} · ${escapeHtml(food.category)}</p>
      <div class="pantry-card-bottom"><span class="expiry-badge ${expiryClass(food)}">${escapeHtml(expiryLabel(food))}</span><div class="card-actions"><button class="small-action use-action" data-status="used" data-id="${food.id}">Aproveché</button><button class="small-action" data-status="wasted" data-id="${food.id}">Desperdicio</button></div></div>
    </article>`).join("") : '<p class="no-items">No hay alimentos que coincidan con tu búsqueda.</p>';
}

async function renderIdeas() {
  const { recipes, has_food: hasFood } = await api("/api/ideas");
  document.getElementById("recipe-list").innerHTML = recipes.map((recipe) => `
    <article class="recipe-card"><div class="recipe-card-icon">${recipe.icon}</div><h2>${escapeHtml(recipe.title)}</h2><p>${escapeHtml(recipe.description)}</p><span class="match-label">${recipe.matches.length ? "Podrías usar:" : "Ideas para inspirarte"}</span><div class="match-chips">${recipe.matches.length ? recipe.matches.map((name) => `<span class="match-chip">${escapeHtml(name)}</span>`).join("") : `<span class="no-match">${hasFood ? "Aún no detectamos ingredientes relacionados." : "Agrega alimentos para ver coincidencias."}</span>`}</div></article>`).join("");
}

async function renderHistory() {
  const { events } = await api("/api/history");
  document.getElementById("impact-used").textContent = dashboardData.stats.used;
  document.getElementById("impact-wasted").textContent = dashboardData.stats.wasted;
  document.getElementById("history-list").innerHTML = events.length ? events.map((event) => {
    const wasted = event.status === "wasted";
    const date = new Date(event.updated_at + "Z").toLocaleDateString("es", { day: "numeric", month: "short" });
    return `<div class="history-row"><span class="history-status ${wasted ? "wasted" : ""}"></span><div class="history-copy">${escapeHtml(event.name)} · ${escapeHtml(event.quantity)} ${escapeHtml(event.unit)}<small>${date}</small></div><span class="history-tag ${wasted ? "wasted" : ""}">${wasted ? "Desperdicio" : "Aprovechado"}</span></div>`;
  }).join("") : '<p class="no-items">Aquí aparecerá tu actividad cuando registres un alimento aprovechado o desperdiciado.</p>';
}

async function refreshData() {
  dashboardData = await api("/api/dashboard");
  renderDashboard();
  renderPantry();
}

function switchView(view) {
  const views = ["inicio", "despensa", "ideas", "impacto", "faq"];
  if (!views.includes(view)) return;
  document.querySelectorAll(".view").forEach((section) => section.classList.toggle("active", section.id === "view-" + view));
  document.querySelectorAll(".nav-link").forEach((link) => link.classList.toggle("active", link.dataset.view === view));
  const names = { inicio: "Resumen", despensa: "Mi despensa", ideas: "Ideas para cocinar", impacto: "Mi impacto", faq: "Preguntas y defensa" };
  document.getElementById("breadcrumb-current").textContent = names[view];
  if (view === "ideas") renderIdeas().catch((error) => showToast(error.message));
  if (view === "impacto") renderHistory().catch((error) => showToast(error.message));
  if (view === "despensa") renderPantry();
}

function openFoodDialog() {
  const dialog = document.getElementById("food-dialog");
  const dateInput = document.querySelector('[name="expires_on"]');
  dateInput.value = new Date().toISOString().slice(0, 10);
  document.getElementById("form-error").classList.add("hidden");
  dialog.showModal();
}

document.querySelectorAll("[data-view]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    const view = link.dataset.view;
    history.replaceState(null, "", "#" + view);
    switchView(view);
  });
});
document.querySelectorAll("[data-open-form]").forEach((button) => button.addEventListener("click", openFoodDialog));
document.getElementById("quick-add").addEventListener("click", openFoodDialog);
document.getElementById("close-dialog").addEventListener("click", () => document.getElementById("food-dialog").close());
document.getElementById("food-search").addEventListener("input", renderPantry);
document.getElementById("food-filter").addEventListener("change", renderPantry);

document.querySelectorAll("[data-auth-mode]").forEach((button) => {
  button.addEventListener("click", () => setAuthMode(button.dataset.authMode));
});

document.getElementById("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  document.getElementById("auth-error").classList.add("hidden");
  try {
    const endpoint = authMode === "register" ? "/api/register" : "/api/login";
    const result = await api(endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await enterApp(result.user);
  } catch (exception) {
    showAuthError(exception.message);
  }
});

document.getElementById("logout-button").addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST", body: "{}" });
    dashboardData = { foods: [], stats: { active: 0, urgent: 0, used: 0, wasted: 0 } };
    document.getElementById("auth-form").reset();
    document.getElementById("auth-screen").classList.add("visible");
    setAuthMode("login");
    document.getElementById("auth-email").focus();
  } catch (exception) {
    showToast(exception.message);
  }
});

document.getElementById("food-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form));
  payload.quantity = Number(payload.quantity);
  const error = document.getElementById("form-error");
  try {
    await api("/api/foods", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    document.getElementById("food-dialog").close();
    await refreshData();
    showToast("Alimento agregado a tu despensa.");
  } catch (exception) {
    error.textContent = exception.message;
    error.classList.remove("hidden");
  }
});

document.getElementById("pantry-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  try {
    if (button.dataset.status) {
      const status = button.dataset.status;
      await api("/api/foods/" + button.dataset.id, { method: "PATCH", body: JSON.stringify({ status }) });
      await refreshData();
      showToast(status === "used" ? "¡Qué bien! Alimento marcado como aprovechado." : "Desperdicio agregado a tu registro.");
    } else if (button.dataset.delete) {
      await api("/api/foods/" + button.dataset.delete, { method: "DELETE" });
      await refreshData();
      showToast("Alimento quitado de tu despensa.");
    }
  } catch (exception) {
    showToast(exception.message);
  }
});

document.getElementById("today-label").textContent = new Date().toLocaleDateString("es", { weekday: "short", day: "numeric", month: "short" });
document.getElementById("auth-screen").classList.add("visible");
api("/api/session")
  .then(({ user }) => {
    if (user) return enterApp(user);
    setAuthMode("login");
    document.getElementById("auth-email").focus();
  })
  .catch((error) => showAuthError(error.message));
