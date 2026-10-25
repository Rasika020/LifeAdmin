"use strict";

const state = { reminders: [], filter: "upcoming", editingId: null };
const list = document.querySelector("#reminder-list");
const loading = document.querySelector("#loading");
const notice = document.querySelector("#notice");
const dialog = document.querySelector("#reminder-dialog");
const form = document.querySelector("#reminder-form");
const saveButton = document.querySelector("#save-reminder");
const formError = document.querySelector("#form-error");
const search = document.querySelector("#search");

const filters = {
  upcoming: { title: "Coming up", empty: "Nothing coming up", message: "Enjoy the breathing room. Add a reminder whenever you need one." },
  overdue: { title: "Needs a look", empty: "All caught up", message: "Nothing is overdue. You’re right on track." },
  completed: { title: "Done & dusted", empty: "No completed reminders yet", message: "When you finish something, mark it done and it’ll show up here." },
  all: { title: "All reminders", empty: "Your list is a clean slate", message: "Add your first reminder and give future-you a little help." },
};

function localDate(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateDistance(value) {
  const today = new Date(`${localDate()}T12:00:00`);
  const due = new Date(`${value}T12:00:00`);
  return Math.round((due - today) / 86_400_000);
}

function formatDate(value) {
  const date = new Date(`${value}T12:00:00`);
  return {
    day: new Intl.DateTimeFormat(undefined, { day: "numeric" }).format(date),
    month: new Intl.DateTimeFormat(undefined, { month: "short" }).format(date),
    full: new Intl.DateTimeFormat(undefined, { weekday: "short", month: "long", day: "numeric", year: "numeric" }).format(date),
  };
}

function visibleReminders() {
  const today = localDate();
  const query = search.value.trim().toLocaleLowerCase();
  return state.reminders.filter((reminder) => {
    const matchesFilter = state.filter === "all"
      || (state.filter === "completed" && reminder.status === "completed")
      || (state.filter === "overdue" && reminder.status === "open" && reminder.due_date < today)
      || (state.filter === "upcoming" && reminder.status === "open" && reminder.due_date >= today);
    const searchable = `${reminder.title} ${reminder.category || ""} ${reminder.notes || ""}`.toLocaleLowerCase();
    return matchesFilter && searchable.includes(query);
  });
}

function updateSummary() {
  const today = localDate();
  const counts = {
    upcoming: state.reminders.filter((item) => item.status === "open" && item.due_date >= today).length,
    overdue: state.reminders.filter((item) => item.status === "open" && item.due_date < today).length,
    completed: state.reminders.filter((item) => item.status === "completed").length,
    all: state.reminders.length,
  };
  for (const [key, count] of Object.entries(counts)) {
    document.querySelector(`[data-count="${key}"]`).textContent = String(count);
    const stat = document.querySelector(`[data-stat="${key}"]`);
    if (stat) stat.textContent = String(count);
  }
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function setNotice(message = "") {
  notice.textContent = message;
  notice.hidden = !message;
}

function makeAction(label, symbol, className, onClick) {
  const button = makeElement("button", `icon-button ${className}`, symbol);
  button.type = "button";
  button.setAttribute("aria-label", label);
  button.title = label;
  button.addEventListener("click", onClick);
  return button;
}

function makeReminderCard(reminder) {
  const completed = reminder.status === "completed";
  const date = formatDate(reminder.due_date);
  const card = makeElement("article", `reminder-card${completed ? " completed-card" : ""}`);
  const dateTile = makeElement("div", "date-tile");
  dateTile.append(makeElement("span", "month", date.month), makeElement("span", "day", date.day));
  const copy = makeElement("div", "reminder-copy");
  copy.append(makeElement("h3", "reminder-title", reminder.title));
  const meta = makeElement("div", "reminder-meta");
  meta.append(makeElement("span", "", reminder.due_time ? `${date.full} · ${reminder.due_time}` : date.full));
  if (reminder.category) meta.append(makeElement("span", "category-chip", reminder.category));
  if (completed) meta.append(makeElement("span", "completed-label", "Completed"));
  else {
    const days = dateDistance(reminder.due_date);
    const dueText = days === 0 ? "Today" : days === 1 ? "Tomorrow" : days < 0 ? `${Math.abs(days)}d overdue` : `In ${days} days`;
    meta.append(makeElement("span", days < 0 ? "completed-label" : "", dueText));
  }
  copy.append(meta);
  if (reminder.notes) copy.append(makeElement("p", "reminder-notes", reminder.notes));

  const actions = makeElement("div", "card-actions");
  if (!completed) {
    actions.append(makeAction("Mark complete", "✓", "complete-button", () => completeReminder(reminder)));
    actions.append(makeAction("Edit reminder", "✎", "", () => openEditor(reminder)));
  }
  card.append(dateTile, copy, actions);
  return card;
}

function render() {
  updateSummary();
  document.querySelector("#list-title").textContent = filters[state.filter].title;
  document.querySelectorAll("[data-filter]").forEach((button) => {
    const active = button.dataset.filter === state.filter;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  list.replaceChildren();
  const reminders = visibleReminders();
  if (reminders.length) {
    reminders.forEach((reminder) => list.append(makeReminderCard(reminder)));
    return;
  }
  const empty = makeElement("div", "empty-state");
  empty.append(makeElement("span", "empty-mark", "✳"), makeElement("strong", "", filters[state.filter].empty));
  empty.append(makeElement("p", "", search.value.trim() ? "Try another search, or clear the search field." : filters[state.filter].message));
  if (state.filter !== "completed" && !search.value.trim()) {
    const add = makeElement("button", "button button-primary", "＋ Add a reminder");
    add.type = "button";
    add.addEventListener("click", () => openEditor());
    empty.append(add);
  }
  list.append(empty);
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

async function loadReminders() {
  loading.hidden = false;
  setNotice();
  try {
    const data = await request("/api/reminders?status=all");
    state.reminders = data.reminders;
    render();
  } catch (error) {
    setNotice(`Couldn’t load reminders: ${error.message}`);
    list.replaceChildren();
  } finally {
    loading.hidden = true;
  }
}

function openEditor(reminder = null) {
  state.editingId = reminder ? reminder.id : null;
  form.reset();
  formError.hidden = true;
  formError.textContent = "";
  document.querySelector("#dialog-title").textContent = reminder ? "Edit reminder" : "Add a reminder";
  saveButton.textContent = reminder ? "Save changes" : "Save reminder";
  document.querySelector("#title").value = reminder?.title || "";
  document.querySelector("#due-date").value = reminder?.due_date || localDate();
  document.querySelector("#due-time").value = reminder?.due_time || "";
  document.querySelector("#category").value = reminder?.category || "";
  document.querySelector("#notes").value = reminder?.notes || "";
  dialog.showModal();
  document.querySelector("#title").focus();
}

async function completeReminder(reminder) {
  setNotice();
  try {
    await request(`/api/reminders/${encodeURIComponent(reminder.id)}/complete`, { method: "POST", body: "{}" });
    await loadReminders();
  } catch (error) {
    setNotice(`Couldn’t complete that reminder: ${error.message}`);
  }
}

async function saveReminder(event) {
  event.preventDefault();
  formError.hidden = true;
  saveButton.disabled = true;
  saveButton.textContent = "Saving…";
  const body = {
    title: document.querySelector("#title").value.trim(),
    due_date: document.querySelector("#due-date").value,
    due_time: document.querySelector("#due-time").value || null,
    category: document.querySelector("#category").value.trim(),
    notes: document.querySelector("#notes").value,
  };
  if (state.editingId && !body.due_time) {
    body.due_time = null;
    body.clear_due_time = true;
  }
  try {
    const path = state.editingId ? `/api/reminders/${encodeURIComponent(state.editingId)}` : "/api/reminders";
    await request(path, { method: state.editingId ? "PATCH" : "POST", body: JSON.stringify(body) });
    dialog.close();
    await loadReminders();
  } catch (error) {
    formError.textContent = error.message;
    formError.hidden = false;
  } finally {
    saveButton.disabled = false;
    saveButton.textContent = state.editingId ? "Save changes" : "Save reminder";
  }
}

function setToday(data) {
  const date = formatDate(data.current_date);
  document.querySelector("#today-label").textContent = `${date.month.toUpperCase()} ${date.day} · ${date.full.split(",")[0].toUpperCase()}`;
  document.querySelector("#today-date").textContent = "Your deadlines, in one place.";
  document.querySelector("#timezone-label").textContent = `Dates use your local time${data.timezone ? ` · ${data.timezone}` : ""}`;
}

document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    render();
  });
});
document.querySelector("#add-reminder").addEventListener("click", () => openEditor());
document.querySelector("#close-dialog").addEventListener("click", () => dialog.close());
document.querySelector("#cancel-dialog").addEventListener("click", () => dialog.close());
form.addEventListener("submit", saveReminder);
search.addEventListener("input", render);
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !dialog.open && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    event.preventDefault();
    search.focus();
  }
});

request("/api/date")
  .then(setToday)
  .catch((error) => { setNotice(`Couldn’t read the local date: ${error.message}`); });
loadReminders();
