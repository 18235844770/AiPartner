const $ = (selector) => document.querySelector(selector);
const pages = [...document.querySelectorAll(".page")];
const mutationHeaders = { "Content-Type": "application/json", "X-Companion-Request": "1" };

let session = new AbortController();
let account;
let companion;
let source;
let refresh;
let reconnect;
let page;
let registering = false;
let cursor = 0;
let pendingSend;
let noticeTimer;
const messages = new Map();
const turns = new Map();
const previews = new Map();

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(path, options = {}, signal = session.signal) {
  const { method = "GET", data, retry = true } = options;
  const request = () => fetch(`/api${path}`, {
    method,
    headers: method === "GET" ? undefined : mutationHeaders,
    body: data === undefined ? undefined : JSON.stringify(data),
    cache: "no-store",
    signal,
  });
  let response = await request();
  if (response.status === 401 && retry && await renewSession(signal)) response = await request();
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new ApiError(response.status, detail.message || "服务暂时不可用，请稍后重试");
  }
  return response.headers.get("Content-Type")?.includes("application/json") ? response.json() : null;
}

function renewSession(signal) {
  if (refresh) return refresh;
  const rotate = async () => {
    const current = await fetch("/api/user/me", { cache: "no-store", signal });
    if (current.ok) return true;
    const response = await fetch("/api/auth/refresh", { method: "POST", headers: mutationHeaders, cache: "no-store", signal });
    return response.ok;
  };
  const task = navigator.locks ? navigator.locks.request("companion-session-refresh", { signal }, rotate) : rotate();
  refresh = task;
  const clear = () => { if (refresh === task) refresh = undefined; };
  task.then(clear, clear);
  return task;
}

function show(target) {
  page = target;
  for (const section of pages) section.hidden = section.id !== target;
  $("#tabs").hidden = !["home", "chat", "settings"].includes(target);
  document.querySelectorAll("#tabs button").forEach((button) => {
    if (button.dataset.page === target) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  if (target === "chat") renderChat(true);
}

function notify(message) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 4200);
}

function report(error) {
  if (error.name !== "AbortError") notify(error.message || "请求失败，请重试");
}

function invalidate() {
  session.abort();
  session = new AbortController();
  source?.close();
  source = undefined;
  clearTimeout(reconnect);
  clearTimeout(noticeTimer);
  $("#notice").hidden = true;
  $("#notice").textContent = "";
  refresh = undefined;
  account = companion = pendingSend = undefined;
  cursor = 0;
  messages.clear();
  turns.clear();
  previews.clear();
  for (const form of document.forms) form.reset();
  $("#messages").replaceChildren();
  for (const selector of ["#profile-username", "#last-content", "#last-time", "#today", "#connection"]) $(selector).textContent = "";
  for (const selector of ["#home-name", "#chat-name"]) $(selector).textContent = "伴侣";
  document.querySelectorAll("[data-companion-mark]").forEach((mark) => { mark.textContent = "伴"; });
  drawEmotion();
  $("#last-message").hidden = true;
  $("#older").hidden = true;
  $(".settings details").open = false;
}

function fillProfile() {
  const form = $("#profile-form");
  $("#profile-username").textContent = account.username;
  form.elements.display_name.value = account.display_name;
  form.elements.timezone.value = account.timezone;
  $("#today").textContent = new Intl.DateTimeFormat("zh-CN", {
    weekday: "long", month: "long", day: "numeric", timeZone: account.timezone,
  }).format(new Date());
}

async function loadSession() {
  const signal = session.signal;
  const profile = await api("/user/me", {}, signal);
  if (signal.aborted) return;
  account = profile;
  fillProfile();
  await loadCompanion(signal);
}

async function loadCompanion(signal = session.signal, probes = 0) {
  const next = await api("/companion/me", {}, signal);
  if (signal.aborted) return;
  companion = next;
  if (next.initialization_status !== "ready") {
    const failed = next.initialization_status === "failed";
    $("#setup-title").textContent = failed ? "初始化未完成" : "正在初始化伴侣";
    $("#retry-setup").hidden = !failed && probes < 4;
    show("setup");
    if (!failed && probes < 4) setTimeout(() => {
      if (!signal.aborted && page === "setup") loadCompanion(signal, probes + 1).catch(report);
    }, 1800);
    return;
  }
  $("#home-name").textContent = next.name;
  $("#chat-name").textContent = next.name;
  document.querySelectorAll("[data-companion-mark]").forEach((mark) => { mark.textContent = [...next.name][0] || "伴"; });
  const [history, state] = await Promise.all([api("/chat/messages", {}, signal), api("/companion/state", {}, signal)]);
  if (signal.aborted) return;
  history.messages.forEach((message) => mergeMessage(message, true));
  $("#older").hidden = !history.has_more;
  drawEmotion(state.emotion);
  show("home");
  connectStream(signal);
}

function drawEmotion(emotion) {
  const labels = { calm: "平静", joy: "开心", happy: "开心", sadness: "低落", sad: "低落", anger: "生气", worried: "担心" };
  const mood = !emotion ? "calm" : emotion.valence >= .65 ? "warm" : emotion.valence <= .35 ? "low" : "calm";
  const label = labels[emotion?.primary] || (mood === "warm" ? "心情不错" : mood === "low" ? "有点低落" : "在");
  $("#home-emotion").textContent = label;
  $("#chat-emotion").textContent = label;
  document.querySelectorAll(".emotion-mark").forEach((mark) => { mark.dataset.mood = mood; });
}

function mergeMessage(message, advance = false) {
  messages.set(message.id, message);
  previews.delete(message.id);
  if (advance) cursor = Math.max(cursor, message.sequence_number);
  const latest = [...messages.values()].filter((item) => item.sender_type === "companion")
    .reduce((current, item) => !current || item.sequence_number > current.sequence_number ? item : current, undefined);
  if (latest) {
    $("#last-message").hidden = false;
    $("#last-content").textContent = latest.content;
    $("#last-time").textContent = new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit", minute: "2-digit", timeZone: account.timezone,
    }).format(new Date(latest.created_at));
  }
}

function renderChat(scroll = false) {
  if (page !== "chat") return;
  const view = $("#thread");
  const stick = scroll || view.scrollHeight - view.scrollTop - view.clientHeight < 80;
  const list = $("#messages");
  const activeIds = new Set();
  const entries = [...messages.values()].sort((a, b) => a.sequence_number - b.sequence_number).concat([...previews.values()]);
  const elements = new Map([...list.children].map((item) => [item.dataset.id, item]));
  let position = list.firstChild;
  for (const item of entries) {
    activeIds.add(item.id);
    const element = elements.get(item.id) || document.createElement("li");
    element.dataset.id = item.id;
    element.className = `message ${item.sender_type === "user" ? "user" : "companion"}`;
    updateBubble(element, item);
    if (element !== position) list.insertBefore(element, position);
    position = element.nextSibling;
  }
  for (const element of list.children.length ? [...list.children] : []) {
    if (!activeIds.has(element.dataset.id)) element.remove();
  }
  if (stick) view.scrollTop = view.scrollHeight;
}

function updateBubble(element, item) {
  let bubble = element.querySelector(".bubble");
  if (!bubble) {
    bubble = document.createElement("p");
    bubble.className = "bubble";
    element.append(bubble);
  }
  if (bubble.textContent !== item.content) bubble.textContent = item.content;
  const turn = turns.get(item.sequence_number);
  if (turn?.status === "failed") {
    if (!element.querySelector("button")) addBubbleButton(element, "回复失败，重试", () => retryTurn(turn.turn_id));
  } else if (item.sender_type === "user") {
    element.querySelector("button")?.remove();
  } else if (item.sequence_number && item.sender_type === "companion") {
    const asset = item.metadata?.audio_asset_id;
    if (asset && !element.querySelector("audio")) {
      element.querySelector("button")?.remove();
      const player = document.createElement("audio");
      player.controls = true;
      player.preload = "none";
      player.src = `/api/chat/audio/${encodeURIComponent(asset)}`;
      element.append(player);
    } else if (!asset && !element.querySelector("button")) {
      addBubbleButton(element, "听语音", async () => {
        const signal = session.signal;
        const result = await api(`/chat/messages/${item.id}/audio`, { method: "POST" }, signal);
        if (!signal.aborted) applyAudio(result);
      });
    }
  }
}

function addBubbleButton(element, label, run) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "plain";
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await run(); } catch (error) { report(error); }
    finally { button.disabled = false; }
  });
  element.append(button);
}

function applyAudio(result) {
  const item = messages.get(result.message_id);
  if (item && result.audio_url?.startsWith("/api/chat/audio/")) {
    item.metadata = { ...item.metadata, audio_asset_id: result.audio_url.split("/").at(-1) };
    renderChat();
  }
}

async function retryTurn(turnId) {
  const signal = session.signal;
  const result = await api(`/chat/turns/${turnId}/retry`, { method: "POST" }, signal);
  if (signal.aborted) return;
  turns.set(result.trigger_sequence, result);
  renderChat();
}

function connectStream(signal) {
  if (signal.aborted) return;
  source?.close();
  const live = new EventSource(`/api/chat/stream?after_sequence=${cursor}`);
  source = live;
  const listen = (name, handler) => live.addEventListener(name, (event) => {
    if (!signal.aborted && live === source) handler(JSON.parse(event.data));
  });
  live.onopen = () => { if (!signal.aborted) $("#connection").textContent = ""; };
  live.onerror = () => {
    live.close();
    if (signal.aborted || live !== source) return;
    previews.clear();
    renderChat();
    $("#connection").textContent = "正在重连";
    reconnect = setTimeout(async () => {
      if (signal.aborted) return;
      try {
        const next = await api("/user/me", {}, signal);
        if (signal.aborted) return;
        if (next.id !== account.id) {
          invalidate();
          await loadSession();
        } else connectStream(signal);
      } catch (error) {
        if (signal.aborted) return;
        if (error.status === 401) { invalidate(); show("auth"); }
        else connectStream(signal);
      }
    }, 1800);
  };
  listen("message.persisted", (message) => { mergeMessage(message, true); renderChat(); });
  listen("message.delta", (delta) => {
    if (!messages.has(delta.message_id)) {
      const old = previews.get(delta.message_id);
      previews.set(delta.message_id, { id: delta.message_id, sender_type: "companion", content: (old?.content || "") + delta.delta });
      renderChat();
    }
  });
  listen("turn.status", (turn) => { turns.set(turn.trigger_sequence, turn); renderChat(); });
  listen("state.updated", (state) => drawEmotion(state.emotion));
  listen("media.ready", applyAudio);
}

function bindForm(selector, handler) {
  $(selector).addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try { await handler(Object.fromEntries(new FormData(form)), form, session.signal); }
    catch (error) { report(error); }
    finally { button.disabled = false; }
  });
}

$("#toggle-auth").addEventListener("click", () => {
  registering = !registering;
  $("#auth-title").textContent = registering ? "创建账号" : "登录";
  $("#toggle-auth").textContent = registering ? "返回登录" : "创建账号";
  const form = $("#auth-form");
  form.querySelector('button[type="submit"]').textContent = registering ? "注册" : "登录";
  form.elements.password.autocomplete = registering ? "new-password" : "current-password";
  form.elements.password.minLength = registering ? 8 : 1;
});

bindForm("#auth-form", async (credentials, form, signal) => {
  if (registering) {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    await api("/auth/register", { method: "POST", data: { ...credentials, timezone }, retry: false }, signal);
  }
  await api("/auth/login", { method: "POST", data: credentials, retry: false }, signal);
  if (signal.aborted) return;
  form.reset();
  invalidate();
  await loadSession();
});

document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => show(button.dataset.page)));
document.querySelectorAll("[data-logout]").forEach((button) => button.addEventListener("click", async () => {
  button.disabled = true;
  const signal = session.signal;
  try {
    await api("/auth/logout", { method: "POST", retry: false }, signal);
    if (!signal.aborted) { invalidate(); show("auth"); }
  } catch (error) { report(error); }
  finally { button.disabled = false; }
}));

$("#retry-setup").addEventListener("click", async () => {
  const signal = session.signal;
  try {
    await api("/companion/me/retry", { method: "POST" }, signal);
    if (!signal.aborted) await loadCompanion(signal);
  } catch (error) { report(error); }
});

bindForm("#send-form", async ({ content }, form, signal) => {
  const trimmed = content.trim();
  if (!trimmed) return;
  if (pendingSend?.content !== trimmed) pendingSend = { content: trimmed, client_message_id: crypto.randomUUID() };
  const result = await api("/chat/messages", { method: "POST", data: pendingSend }, signal);
  if (signal.aborted) return;
  pendingSend = undefined;
  if (form.elements.content.value === content) form.reset();
  mergeMessage(result.message);
  renderChat(true);
});

$("#older").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const sequence = Math.min(...[...messages.values()].map((message) => message.sequence_number));
  if (!Number.isFinite(sequence)) return;
  const signal = session.signal;
  button.disabled = true;
  try {
    const result = await api(`/chat/messages?before_sequence=${sequence}`, {}, signal);
    if (signal.aborted) return;
    const view = $("#thread");
    const previous = view.scrollHeight;
    result.messages.forEach((message) => mergeMessage(message));
    button.hidden = !result.has_more;
    renderChat();
    view.scrollTop += view.scrollHeight - previous;
  } catch (error) { report(error); }
  finally { button.disabled = false; }
});

bindForm("#profile-form", async (changes, _form, signal) => {
  const updated = await api("/user/me", { method: "PATCH", data: changes }, signal);
  if (signal.aborted) return;
  account = updated;
  fillProfile();
  notify("资料已保存");
});

bindForm("#password-form", async (passwords, form, signal) => {
  await api("/user/password", { method: "POST", data: passwords, retry: false }, signal);
  if (!signal.aborted) { form.reset(); notify("密码已更新，其他设备已退出"); }
});

bindForm("#delete-form", async (data, _form, signal) => {
  await api("/user/me", { method: "DELETE", data, retry: false }, signal);
  if (!signal.aborted) { invalidate(); show("auth"); notify("注销申请已提交"); }
});

loadSession().catch((error) => {
  show("auth");
  if (error.status !== 401) report(error);
});
