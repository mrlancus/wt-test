// Phase 1 working page: login, upload, match list, data health.

const $ = (selector) => document.querySelector(selector);
const STATUS_CLASS = { done: "ok", failed: "bad", missing: "warn", inbox: "dim" };

async function api(path, init) {
  const response = await fetch(`/api/${path}`, { credentials: "same-origin", ...init });
  if (response.status === 401) {
    showLogin();
    throw new Error("login required");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function showLogin() {
  $("#login").hidden = false;
  $("#app").hidden = true;
}

function cell(text, className = "") {
  const td = document.createElement("td");
  td.textContent = text ?? "–";
  if (className) td.className = className;
  return td;
}

async function loadMatches() {
  const { matches } = await api("matches");
  $("#login").hidden = true;
  $("#app").hidden = false;
  const rows = matches.map((m) => {
    const tr = document.createElement("tr");
    tr.append(
      cell(m.started?.slice(0, 16).replace("T", " ")),
      cell(m.map),
      cell([m.game_mode, m.difficulty, m.mission_mode].filter(Boolean).join(" ")),
      cell(JSON.parse(m.vehicles || "[]").join(", ")),
      cell(m.result, m.result === "win" ? "ok" : m.result === "loss" ? "bad" : ""),
      cell(m.kills, "num"),
      cell(m.deaths, "num"),
      cell(m.score, "num"),
      cell(m.server_status, STATUS_CLASS[m.server_status]),
      cell(m.decode_status, STATUS_CLASS[m.decode_status]),
    );
    if (m.decode_error) tr.title = m.decode_error;
    return tr;
  });
  $("#matches tbody").replaceChildren(...rows);
  loadHealth();
}

async function loadHealth() {
  const { storage } = await api("health");
  const mb = (b) => `${(b / 1048576).toFixed(1)} MB`;
  $("#health").textContent = storage.length
    ? storage.map((s) => `${s.kind}: ${s.files} files, ${mb(s.bytes)}`).join("   ·   ")
    : "No data yet.";
}

async function upload(files) {
  for (const file of files) {
    const line = document.createElement("div");
    line.textContent = `${file.name}: uploading…`;
    $("#log").prepend(line);
    try {
      const r = await api(`upload?name=${encodeURIComponent(file.name)}`, { method: "PUT", body: file });
      line.textContent = `${file.name}: ${r.new ? "uploaded, your PC will process it" : "already known"}, ${r.map}, session ${r.session}`;
    } catch (e) {
      line.textContent = `${file.name}: ${e.message}`;
      line.className = "bad";
    }
  }
  loadMatches();
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("login", { method: "POST", body: JSON.stringify({ key: $("#key").value }) });
    loadMatches();
  } catch (e) {
    $("#key").value = "";
    $("#key").placeholder = e.message;
  }
});
$("#files").addEventListener("change", (event) => upload([...event.target.files]));
const drop = $("#drop");
drop.addEventListener("dragover", (event) => { event.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (event) => {
  event.preventDefault();
  drop.classList.remove("over");
  upload([...event.dataTransfer.files].filter((f) => f.name.endsWith(".wrpl")));
});

loadMatches().catch(() => {});
setInterval(() => { if (!$("#app").hidden) loadMatches().catch(() => {}); }, 15000);
