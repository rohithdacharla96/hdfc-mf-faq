/* HDFC MF FAQ Assistant — ChatGPT-style chat UI with local history. */
(() => {
  "use strict";

  const STORAGE_KEY = "hdfc-faq-chats-v1";
  const ACTIVE_KEY = "hdfc-faq-active-chat-v1";
  const THEME_KEY = "hdfc-faq-theme-v1";
  const MAX_STORED_CHATS = 40;

  const $ = (id) => document.getElementById(id);

  const els = {
    chat: $("chat"),
    welcome: $("welcome"),
    messages: $("messages"),
    history: $("history"),
    historySearch: $("historySearch"),
    form: $("form"),
    query: $("query"),
    send: $("send"),
    newChat: $("newChat"),
    clearAll: $("clearAll"),
    sidebar: $("sidebar"),
    overlay: $("overlay"),
    sidebarOpen: $("sidebarOpen"),
    sidebarClose: $("sidebarClose"),
    statusDot: $("statusDot"),
    statusText: $("statusText"),
    themeToggle: $("themeToggle"),
    topbarTitle: $("topbarTitle"),
    toast: $("toast"),
  };

  const state = {
    chats: loadChats(),
    activeId: loadActiveId(),
    search: "",
    pending: false,
    error: "",
  };

  let toastTimer = 0;

  /* ------------------------------------------------------------------ storage */

  function loadChats() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      if (!Array.isArray(raw)) return [];
      return raw
        .filter((c) => c && typeof c.id === "string" && Array.isArray(c.messages))
        .map((c) => ({
          id: c.id,
          title: typeof c.title === "string" && c.title ? c.title : "Untitled chat",
          createdAt: Number(c.createdAt) || Date.now(),
          updatedAt: Number(c.updatedAt) || Date.now(),
          messages: c.messages.filter(
            (m) =>
              m &&
              (m.role === "user" || m.role === "assistant") &&
              typeof m.text === "string"
          ),
        }));
    } catch {
      return [];
    }
  }

  function saveChats() {
    try {
      const ordered = sortedChats().slice(0, MAX_STORED_CHATS);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(ordered));
    } catch {
      /* storage can be unavailable or full — history just won't persist */
    }
  }

  function loadActiveId() {
    try {
      return localStorage.getItem(ACTIVE_KEY) || null;
    } catch {
      return null;
    }
  }

  function saveActive() {
    try {
      if (state.activeId) localStorage.setItem(ACTIVE_KEY, state.activeId);
      else localStorage.removeItem(ACTIVE_KEY);
    } catch {
      /* ignore */
    }
  }

  function newId() {
    return "c_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  function getActive() {
    return state.chats.find((c) => c.id === state.activeId) || null;
  }

  function sortedChats() {
    return [...state.chats].sort((a, b) => b.updatedAt - a.updatedAt);
  }

  /* -------------------------------------------------------------------- theme */

  function currentTheme() {
    return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
    const dark = theme === "dark";
    els.themeToggle.textContent = dark ? "☀" : "☾";
    els.themeToggle.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    els.themeToggle.title = dark ? "Switch to light theme" : "Switch to dark theme";
  }

  /* -------------------------------------------------------------------- toast */

  function toast(message) {
    els.toast.textContent = message;
    els.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => els.toast.classList.remove("show"), 2200);
  }

  /* ------------------------------------------------------------------ history */

  function dayStart(date) {
    const d = new Date(date);
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }

  function historyGroups(chats) {
    const now = Date.now();
    const today = dayStart(now);
    const yesterday = today - 86400000;
    const weekAgo = today - 6 * 86400000;
    const groups = [
      { label: "Today", items: [] },
      { label: "Yesterday", items: [] },
      { label: "Previous 7 days", items: [] },
      { label: "Older", items: [] },
    ];
    for (const chat of chats) {
      const t = dayStart(chat.updatedAt);
      if (t >= today) groups[0].items.push(chat);
      else if (t >= yesterday) groups[1].items.push(chat);
      else if (t >= weekAgo) groups[2].items.push(chat);
      else groups[3].items.push(chat);
    }
    return groups.filter((g) => g.items.length);
  }

  function matchesSearch(chat, term) {
    if (!term) return true;
    if (chat.title.toLowerCase().includes(term)) return true;
    return chat.messages.some((m) => m.text.toLowerCase().includes(term));
  }

  function formatWhen(ts) {
    const date = new Date(ts);
    const today = dayStart(Date.now());
    if (date.getTime() >= today) {
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    if (date.getTime() >= today - 6 * 86400000) {
      return date.toLocaleDateString([], { weekday: "short" });
    }
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function renderHistory() {
    const term = state.search.trim().toLowerCase();
    const chats = sortedChats().filter((c) => matchesSearch(c, term));
    els.clearAll.disabled = !state.chats.length;
    els.history.replaceChildren();

    if (!chats.length) {
      const empty = document.createElement("div");
      empty.className = "history-empty";
      empty.textContent = term
        ? "No chats match your search."
        : "No chats yet. Ask your first question to start a conversation.";
      els.history.appendChild(empty);
      return;
    }

    for (const group of historyGroups(chats)) {
      const label = document.createElement("div");
      label.className = "history-group-label";
      label.textContent = group.label;
      els.history.appendChild(label);

      for (const chat of group.items) {
        const item = document.createElement("div");
        item.className = "history-item" + (chat.id === state.activeId ? " active" : "");
        item.setAttribute("role", "button");
        item.setAttribute("tabindex", "0");
        item.setAttribute("aria-label", `Open chat: ${chat.title}`);

        const icon = document.createElement("span");
        icon.className = "history-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = "H";

        const body = document.createElement("div");
        body.className = "history-body";
        const title = document.createElement("div");
        title.className = "history-title";
        title.textContent = chat.title;
        const meta = document.createElement("div");
        meta.className = "history-meta";
        const count = chat.messages.length;
        meta.textContent = `${count} message${count === 1 ? "" : "s"} · ${formatWhen(chat.updatedAt)}`;
        body.append(title, meta);

        const del = document.createElement("button");
        del.className = "history-delete";
        del.type = "button";
        del.title = "Delete chat";
        del.setAttribute("aria-label", `Delete chat: ${chat.title}`);
        del.textContent = "×";
        del.addEventListener("click", (event) => {
          event.stopPropagation();
          deleteChat(chat.id);
        });

        item.append(icon, body, del);
        item.addEventListener("click", () => openChat(chat.id));
        item.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openChat(chat.id);
          }
        });

        els.history.appendChild(item);
      }
    }
  }

  function openChat(id) {
    state.activeId = id;
    state.error = "";
    saveActive();
    renderHistory();
    renderChat();
    closeSidebar();
    scrollToBottom();
    els.query.focus({ preventScroll: true });
  }

  function deleteChat(id) {
    const chat = state.chats.find((c) => c.id === id);
    state.chats = state.chats.filter((c) => c.id !== id);
    if (state.activeId === id) {
      state.activeId = null;
      state.error = "";
    }
    saveActive();
    saveChats();
    renderHistory();
    renderChat();
    toast(chat ? "Chat deleted" : "Deleted");
  }

  function clearAllChats() {
    if (!state.chats.length) return;
    if (!window.confirm("Delete all chats from this browser? This can't be undone.")) return;
    state.chats = [];
    state.activeId = null;
    state.error = "";
    saveActive();
    saveChats();
    renderHistory();
    renderChat();
    toast("All chats cleared");
  }

  /* ------------------------------------------------------------------- render */

  function renderChat() {
    const active = getActive();
    const hasMessages = Boolean(active && active.messages.length);

    els.welcome.hidden = hasMessages;
    els.messages.hidden = !hasMessages;
    els.messages.replaceChildren();

    if (hasMessages) {
      for (const message of active.messages) {
        els.messages.appendChild(messageEl(message));
      }
    }

    if (state.error) {
      els.messages.hidden = false;
      const error = document.createElement("div");
      error.className = "msg msg-assistant";
      error.innerHTML = "";
      const content = document.createElement("div");
      content.className = "msg-content";
      const body = document.createElement("div");
      body.className = "assistant-body";
      body.textContent = state.error;
      content.appendChild(body);
      error.appendChild(content);
      els.messages.appendChild(error);
    }

    els.topbarTitle.textContent = active ? active.title : "New chat";
    updateComposer();
    scrollToBottom();
  }

  function messageEl(message) {
    return message.role === "user" ? userMessageEl(message) : assistantMessageEl(message);
  }

  function userMessageEl(message) {
    const row = document.createElement("div");
    row.className = "msg msg-user";
    const bubble = document.createElement("div");
    bubble.className = "bubble-user";
    bubble.textContent = message.text;
    row.appendChild(bubble);
    return row;
  }

  function assistantMessageEl(message) {
    const row = document.createElement("div");
    row.className = "msg msg-assistant" + (message.refusal ? " refusal" : "");

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "H";

    const content = document.createElement("div");
    content.className = "msg-content";

    const head = document.createElement("div");
    head.className = "assistant-head";
    const name = document.createElement("span");
    name.className = "assistant-name";
    name.textContent = "HDFC Facts";
    const badge = document.createElement("span");
    badge.className = "mini-badge" + (message.refusal ? " refusal" : "");
    badge.textContent = message.refusal ? "Limited answer" : "Official source";
    head.append(name, badge);

    const body = document.createElement("div");
    body.className = "assistant-body";
    appendRichText(body, message.text);

    content.append(head, body);

    if (message.citationUrl) {
      content.appendChild(sourceCard(message.citationUrl));
    }

    const meta = document.createElement("div");
    meta.className = "msg-meta";

    if (message.updatedAt) {
      const updated = document.createElement("span");
      updated.textContent = `Last updated from sources: ${message.updatedAt}`;
      meta.appendChild(updated);
    }

    const copy = document.createElement("button");
    copy.className = "ghost-btn";
    copy.type = "button";
    copy.textContent = "Copy";
    copy.addEventListener("click", () => copyAnswer(message, copy));
    meta.appendChild(copy);

    content.appendChild(meta);

    if (Array.isArray(message.retrieved) && message.retrieved.length) {
      content.appendChild(retrievalDetails(message.retrieved));
    }

    row.append(avatar, content);
    return row;
  }

  function appendRichText(container, text) {
    const lines = String(text || "").split(/\r?\n/);
    let list = null;
    let paragraph = [];

    const flushParagraph = () => {
      if (!paragraph.length) return;
      const p = document.createElement("p");
      p.textContent = paragraph.join(" ");
      container.appendChild(p);
      paragraph = [];
    };

    const flushList = () => {
      if (list) {
        container.appendChild(list);
        list = null;
      }
    };

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) {
        flushParagraph();
        flushList();
        continue;
      }
      if (/^([-•*]|\d+[.)])\s+/.test(line)) {
        flushParagraph();
        if (!list) list = document.createElement("ul");
        const li = document.createElement("li");
        li.textContent = line.replace(/^([-•*]|\d+[.)])\s+/, "");
        list.appendChild(li);
        continue;
      }
      flushList();
      paragraph.push(line);
    }

    flushParagraph();
    flushList();

    if (!container.childNodes.length) {
      const p = document.createElement("p");
      p.textContent = "No answer returned.";
      container.appendChild(p);
    }
  }

  function sourceCard(url) {
    const link = document.createElement("a");
    link.className = "source-card";
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = "Open the official Groww page";

    const icon = document.createElement("span");
    icon.className = "source-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.1 0l3-3a5 5 0 0 0-7.1-7.1l-1.6 1.6"/><path d="M14 11a5 5 0 0 0-7.1 0l-3 3a5 5 0 0 0 7.1 7.1l1.6-1.6"/></svg>';

    const text = document.createElement("span");
    text.className = "source-text";
    const label = document.createElement("span");
    label.className = "source-label";
    label.textContent = "Source";
    const value = document.createElement("span");
    value.className = "source-url";
    value.textContent = url;
    text.append(label, value);

    link.append(icon, text);
    return link;
  }

  function retrievalDetails(rows) {
    const details = document.createElement("details");
    details.className = "retrieval";

    const summary = document.createElement("summary");
    summary.textContent = `Retrieval · ${rows.length} chunk${rows.length === 1 ? "" : "s"}`;
    details.appendChild(summary);

    const list = document.createElement("div");
    list.className = "retrieval-list";

    for (const row of rows) {
      const item = document.createElement("div");
      item.className = "retrieval-row";

      const section = document.createElement("span");
      section.className = "retrieval-section";
      section.textContent = row.section || "Section";
      section.title = row.section || "";

      const score = document.createElement("span");
      score.className = "retrieval-score";
      score.textContent = Number(row.score).toFixed(3);

      const id = document.createElement("span");
      id.className = "retrieval-id";
      id.textContent = row.chunk_id || "";

      item.append(section, score, id);
      list.appendChild(item);
    }

    details.appendChild(list);
    return details;
  }

  function copyAnswer(message, button) {
    const parts = [message.text];
    if (message.citationUrl) parts.push(`Source: ${message.citationUrl}`);
    if (message.updatedAt) parts.push(`Last updated from sources: ${message.updatedAt}`);
    const value = parts.filter(Boolean).join("\n\n");

    const done = () => {
      const original = button.textContent;
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = original;
      }, 1400);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(done).catch(() => toast("Copy failed"));
    } else {
      const area = document.createElement("textarea");
      area.value = value;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
        done();
      } catch {
        toast("Copy failed");
      }
      area.remove();
    }
  }

  function typingEl() {
    const row = document.createElement("div");
    row.className = "msg msg-assistant";

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "H";

    const content = document.createElement("div");
    content.className = "msg-content";
    const head = document.createElement("div");
    head.className = "assistant-head";
    const name = document.createElement("span");
    name.className = "assistant-name";
    name.textContent = "HDFC Facts";
    head.appendChild(name);

    const body = document.createElement("div");
    body.className = "assistant-body typing-body";
    body.setAttribute("role", "status");
    body.setAttribute("aria-live", "polite");
    for (let i = 0; i < 3; i++) body.appendChild(document.createElement("span"));
    const label = document.createElement("span");
    label.className = "typing-label";
    label.textContent = "Checking official pages…";
    body.appendChild(label);

    content.append(head, body);
    row.append(avatar, content);
    return row;
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      els.chat.scrollTop = els.chat.scrollHeight;
    });
  }

  /* ------------------------------------------------------------------ composer */

  function autosize() {
    els.query.style.height = "auto";
    els.query.style.height = Math.min(els.query.scrollHeight, 200) + "px";
  }

  function updateComposer() {
    els.send.disabled = state.pending || !els.query.value.trim();
  }

  function setPending(pending) {
    state.pending = pending;
    updateComposer();
    if (pending) els.query.blur();
    else els.query.focus({ preventScroll: true });
  }

  /* ------------------------------------------------------------------- asking */

  function splitAnswer(answer, fallbackUpdatedAt) {
    const raw = String(answer || "").trim();
    const updatedMatch = raw.match(/Last updated from sources:\s*([^\n]+)\s*$/i);
    const updatedAt = (updatedMatch ? updatedMatch[1] : fallbackUpdatedAt || "").trim();

    let body = raw;
    const sourceMatch = body.search(/\n\s*Source:\s*\S+/i);
    if (sourceMatch !== -1) body = body.slice(0, sourceMatch);
    body = body.replace(/\n?\s*Last updated from sources:[^\n]*$/i, "").trim();

    return { body, updatedAt };
  }

  async function ask(rawQuery) {
    const query = String(rawQuery || "").replace(/\s+/g, " ").trim();
    if (!query || state.pending) return;

    let chat = getActive();
    if (!chat) {
      chat = {
        id: newId(),
        title: deriveTitle(query),
        createdAt: Date.now(),
        updatedAt: Date.now(),
        messages: [],
      };
      state.chats.push(chat);
      state.activeId = chat.id;
      saveActive();
    }

    const chatId = chat.id;
    const isFirstMessage = chat.messages.length === 0;

    state.error = "";
    chat.messages.push({ role: "user", text: query, createdAt: Date.now() });
    chat.updatedAt = Date.now();
    if (isFirstMessage) chat.title = deriveTitle(query);

    saveChats();
    renderHistory();
    renderChat();

    els.query.value = "";
    autosize();
    setPending(true);

    const typing = typingEl();
    els.messages.appendChild(typing);
    scrollToBottom();

    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });

      if (!res.ok) {
        let detail = "The assistant could not answer right now. Please try again.";
        try {
          const err = await res.json();
          if (err && typeof err.detail === "string") detail = err.detail;
        } catch {
          /* keep default */
        }
        throw new Error(detail);
      }

      const data = await res.json();
      const parsed = splitAnswer(data.answer, data.updated_at);

      const target = state.chats.find((c) => c.id === chatId);
      if (!target) return; // chat was deleted while the request was in flight

      target.messages.push({
        role: "assistant",
        text: parsed.body || "That fact is not available in the scoped official pages.",
        citationUrl: data.citation_url || "",
        updatedAt: parsed.updatedAt,
        refusal: Boolean(data.refusal),
        retrieved: Array.isArray(data.retrieved) ? data.retrieved.slice(0, 6) : [],
        traceId: data.trace_id || "",
        createdAt: Date.now(),
      });
      target.updatedAt = Date.now();
      saveChats();
      renderHistory();

      if (state.activeId === chatId) {
        renderChat();
      }
    } catch (error) {
      if (state.activeId === chatId) {
        state.error =
          error && error.message
            ? error.message
            : "The assistant could not answer right now. Please try again.";
        renderChat();
      }
      toast("Request failed");
    } finally {
      setPending(false);
    }
  }

  function deriveTitle(query) {
    const clean = query.replace(/\s+/g, " ").trim();
    return clean.length > 52 ? clean.slice(0, 52).trimEnd() + "…" : clean;
  }

  /* ------------------------------------------------------------------ sidebar */

  function openSidebar() {
    els.sidebar.classList.add("open");
    els.overlay.classList.add("visible");
    els.overlay.setAttribute("aria-hidden", "false");
  }

  function closeSidebar() {
    els.sidebar.classList.remove("open");
    els.overlay.classList.remove("visible");
    els.overlay.setAttribute("aria-hidden", "true");
  }

  /* ------------------------------------------------------------------- health */

  async function checkHealth() {
    try {
      const res = await fetch("/health", { cache: "no-store" });
      if (!res.ok) throw new Error("offline");
      els.statusDot.classList.add("online");
      els.statusDot.classList.remove("offline");
      els.statusText.textContent = "Online";
    } catch {
      els.statusDot.classList.add("offline");
      els.statusDot.classList.remove("online");
      els.statusText.textContent = "Offline";
    }
  }

  /* -------------------------------------------------------------------- wiring */

  els.form.addEventListener("submit", (event) => {
    event.preventDefault();
    ask(els.query.value);
  });

  els.query.addEventListener("input", () => {
    autosize();
    updateComposer();
  });

  els.query.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      ask(els.query.value);
    }
  });

  document.querySelectorAll(".example-card").forEach((button) => {
    button.addEventListener("click", () => {
      const query = button.dataset.query || "";
      if (query) ask(query);
    });
  });

  els.newChat.addEventListener("click", () => {
    state.activeId = null;
    state.error = "";
    saveActive();
    saveChats();
    renderHistory();
    renderChat();
    closeSidebar();
    els.query.focus({ preventScroll: true });
  });

  els.clearAll.addEventListener("click", clearAllChats);

  els.historySearch.addEventListener("input", () => {
    state.search = els.historySearch.value;
    renderHistory();
  });

  els.sidebarOpen.addEventListener("click", openSidebar);
  els.sidebarClose.addEventListener("click", closeSidebar);
  els.overlay.addEventListener("click", closeSidebar);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && els.sidebar.classList.contains("open")) closeSidebar();
  });

  els.themeToggle.addEventListener("click", () => {
    applyTheme(currentTheme() === "dark" ? "light" : "dark");
  });

  window.addEventListener("resize", closeSidebarOnDesktop);
  function closeSidebarOnDesktop() {
    if (window.innerWidth > 900) closeSidebar();
  }

  /* ---------------------------------------------------------------------- init */

  applyTheme(currentTheme());
  if (state.activeId && !state.chats.some((c) => c.id === state.activeId)) {
    state.activeId = null;
    saveActive();
  }
  renderHistory();
  renderChat();
  autosize();
  checkHealth();
  window.setInterval(checkHealth, 45000);
  if (window.innerWidth > 900) els.query.focus({ preventScroll: true });
})();
