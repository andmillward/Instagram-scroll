(() => {
  const player = document.getElementById("player");
  const seek = document.getElementById("seek");
  const playBtn = document.getElementById("playBtn");
  const prevBtn = document.getElementById("prevBtn");
  const nextBtn = document.getElementById("nextBtn");
  const back10Btn = document.getElementById("back10Btn");
  const fwd10Btn = document.getElementById("fwd10Btn");
  const speedBtn = document.getElementById("speedBtn");
  const autoBtn = document.getElementById("autoBtn");
  const fsBtn = document.getElementById("fsBtn");
  const importBtn = document.getElementById("importBtn");
  const jumpBtn = document.getElementById("jumpBtn");
  const senderName = document.getElementById("senderName");
  const sentDate = document.getElementById("sentDate");
  const captionText = document.getElementById("captionText");
  const counter = document.getElementById("counter");
  const statusOverlay = document.getElementById("statusOverlay");
  const statusText = document.getElementById("statusText");
  const statusLink = document.getElementById("statusLink");
  const retryBtn = document.getElementById("retryBtn");
  const stage = document.getElementById("stage");

  const notesPane = document.getElementById("notesPane");
  const notesCards = document.getElementById("notesCards");

  const importModal = document.getElementById("importModal");
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const importResult = document.getElementById("importResult");
  const closeImportBtn = document.getElementById("closeImportBtn");

  const jumpModal = document.getElementById("jumpModal");
  const jumpDate = document.getElementById("jumpDate");
  const jumpResult = document.getElementById("jumpResult");
  const jumpGoBtn = document.getElementById("jumpGoBtn");
  const jumpCancelBtn = document.getElementById("jumpCancelBtn");

  const SPEEDS = [1, 1.25, 1.5, 2];

  // A notes pane plays back like a video: a virtual clock counts up to a
  // duration (longer for bigger message groups), driving the same seek bar
  // and play/pause/±10s/speed controls, and auto-advancing at the end.
  const NOTE_BASE_SECONDS = 10;
  const NOTE_PER_EXTRA_MESSAGE_SECONDS = 4;
  const NOTE_MAX_SECONDS = 30;

  // Long enough to actually notice and tap the "Open in Instagram" link
  // before it auto-skips a reel that failed to fetch.
  const FAILED_AUTO_SKIP_MS = 6000;

  const THREADS_HOSTS = new Set(["threads.net", "threads.com"]);

  let timeline = [];
  let index = 0;
  let speedIdx = 0;
  let autoAdvance = true;
  let isScrubbing = false;
  let statusPollTimer = null;
  let autoSkipTimer = null;
  let lastSavedAt = 0;

  const noteClock = { duration: 0, elapsed: 0, playing: false, intervalId: null };

  function fmtDate(ms) {
    if (!ms) return "";
    const d = new Date(ms);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  function fmtDateTime(ms) {
    if (!ms) return "";
    const d = new Date(ms);
    return d.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : null;
  }

  function current() {
    return timeline[index];
  }

  function clearTimers() {
    if (statusPollTimer) { clearTimeout(statusPollTimer); statusPollTimer = null; }
    if (autoSkipTimer) { clearTimeout(autoSkipTimer); autoSkipTimer = null; }
  }

  function updateMeta() {
    const item = current();
    if (!item) return;
    if (item.kind === "reel") {
      senderName.textContent = item.sender ? `From ${item.sender}` : "";
      sentDate.textContent = fmtDate(item.sent_at);
      captionText.textContent = item.caption || "";
    } else {
      const senders = [...new Set(item.messages.map((m) => m.sender).filter(Boolean))];
      senderName.textContent = senders.length ? `From ${senders.join(", ")}` : "Messages";
      sentDate.textContent = fmtDate(item.sent_at);
      captionText.textContent = "";
    }
    counter.textContent = `${index + 1} / ${timeline.length}`;
  }

  function showStatus(text, showRetry, linkUrl) {
    statusText.textContent = text;
    retryBtn.classList.toggle("hidden", !showRetry);
    if (linkUrl) {
      statusLink.href = linkUrl;
      statusLink.classList.remove("hidden");
    } else {
      statusLink.classList.add("hidden");
    }
    statusOverlay.classList.remove("hidden");
  }

  function hideStatus() {
    statusOverlay.classList.add("hidden");
  }

  // --- Threads embeds -----------------------------------------------------

  function threadsUrl(url) {
    try {
      const host = new URL(url).hostname.replace(/^www\./, "");
      return THREADS_HOSTS.has(host) ? url : null;
    } catch (e) {
      return null;
    }
  }

  function renderThreadsEmbed(url) {
    const wrap = document.createElement("div");
    wrap.className = "thread-embed";
    const bq = document.createElement("blockquote");
    bq.className = "text-post-media";
    bq.setAttribute("data-text-post-permalink", url);
    bq.setAttribute("data-text-post-version", "0");
    bq.id = `ig-tp-${Math.random().toString(36).slice(2)}`;
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = url;
    bq.appendChild(a);
    wrap.appendChild(bq);
    return wrap;
  }

  function loadThreadsEmbedScript() {
    // Meta's embed widget scans the DOM for unprocessed blockquotes when
    // its script runs; adding a fresh <script> element re-triggers that
    // scan for blockquotes inserted after the first load.
    const s = document.createElement("script");
    s.async = true;
    s.src = "https://www.threads.net/embed.js";
    s.onload = () => s.remove();
    s.onerror = () => s.remove();
    document.body.appendChild(s);
  }

  // --- Notes pane rendering ------------------------------------------------

  function notesDuration(item) {
    return Math.min(
      NOTE_MAX_SECONDS,
      NOTE_BASE_SECONDS + Math.max(0, item.messages.length - 1) * NOTE_PER_EXTRA_MESSAGE_SECONDS
    );
  }

  function renderNotes(item) {
    notesCards.innerHTML = "";
    let hasThreadsLink = false;

    for (const msg of item.messages) {
      const card = document.createElement("div");
      card.className = "note-card";

      const meta = document.createElement("div");
      meta.className = "note-meta";
      meta.textContent = [msg.sender, fmtDateTime(msg.sent_at)].filter(Boolean).join(" · ");
      card.appendChild(meta);

      if (msg.text) {
        const text = document.createElement("div");
        text.className = "note-text";
        text.textContent = msg.text;
        card.appendChild(text);
      }

      if (msg.links && msg.links.length) {
        const linksWrap = document.createElement("div");
        linksWrap.className = "note-links";
        for (const url of msg.links) {
          const threads = threadsUrl(url);
          if (threads) {
            linksWrap.appendChild(renderThreadsEmbed(threads));
            hasThreadsLink = true;
            continue;
          }
          const a = document.createElement("a");
          a.className = "note-link";
          a.href = url;
          a.target = "_blank";
          a.rel = "noopener";
          let label = url;
          try { label = new URL(url).hostname.replace(/^www\./, "") + " ↗"; } catch (e) {}
          a.textContent = label;
          linksWrap.appendChild(a);
        }
        card.appendChild(linksWrap);
      }

      notesCards.appendChild(card);
    }

    if (hasThreadsLink) loadThreadsEmbedScript();
  }

  // --- Notes virtual clock -------------------------------------------------

  function stopNoteClock() {
    if (noteClock.intervalId) {
      clearInterval(noteClock.intervalId);
      noteClock.intervalId = null;
    }
    noteClock.playing = false;
  }

  function updateNoteSeekUI() {
    if (!isScrubbing && noteClock.duration) {
      seek.value = String((noteClock.elapsed / noteClock.duration) * 1000);
    }
  }

  function onNoteEnded() {
    updateNoteSeekUI();
    saveProgress(true);
    if (autoAdvance) next();
  }

  function startNoteClock() {
    stopNoteClock();
    noteClock.playing = true;
    playBtn.textContent = "⏸";
    const tickMs = 200;
    noteClock.intervalId = setInterval(() => {
      noteClock.elapsed += (tickMs / 1000) * SPEEDS[speedIdx];
      if (noteClock.elapsed >= noteClock.duration) {
        noteClock.elapsed = noteClock.duration;
        stopNoteClock();
        playBtn.textContent = "▶";
        onNoteEnded();
        return;
      }
      updateNoteSeekUI();
      saveProgress(false);
    }, tickMs);
  }

  function pauseNoteClock() {
    stopNoteClock();
    playBtn.textContent = "▶";
    saveProgress(true);
  }

  // --- Playback (shared between reels and notes) ---------------------------

  function loadCurrent(seekTo) {
    clearTimers();
    stopNoteClock();
    const item = current();
    updateMeta();

    if (!item) {
      player.pause();
      player.removeAttribute("src");
      notesPane.classList.add("hidden");
      showStatus("You're all caught up. Import more with the + button.", false);
      return;
    }

    if (item.kind === "notes") {
      player.pause();
      player.removeAttribute("src");
      hideStatus();
      renderNotes(item);
      notesPane.classList.remove("hidden");
      noteClock.duration = notesDuration(item);
      noteClock.elapsed = Math.min(seekTo || 0, noteClock.duration);
      updateNoteSeekUI();
      startNoteClock();
      saveProgress(true);
      return;
    }

    notesPane.classList.add("hidden");

    if (item.status === "ready") {
      hideStatus();
      player.src = `/api/video/${item.shortcode}`;
      player.playbackRate = SPEEDS[speedIdx];
      const onMeta = () => {
        player.currentTime = seekTo || 0;
        player.play().catch(() => {});
        player.removeEventListener("loadedmetadata", onMeta);
      };
      player.addEventListener("loadedmetadata", onMeta);
      return;
    }

    if (item.status === "failed") {
      showStatus(`Skipped: this reel couldn't be fetched (${item.error || "unavailable"}).`, true, item.url);
      if (autoAdvance) {
        autoSkipTimer = setTimeout(() => next(), FAILED_AUTO_SKIP_MS);
      }
      return;
    }

    // pending / fetching
    showStatus("Fetching video…", false);
    pollStatus(item.id);
  }

  async function pollStatus(reelId) {
    try {
      const updated = await api(`/api/reels/${reelId}`);
      const i = timeline.findIndex((t) => t.kind === "reel" && t.id === reelId);
      if (i !== -1) timeline[i] = { ...timeline[i], ...updated };
      const item = current();
      if (item && item.kind === "reel" && item.id === reelId) {
        if (updated.status === "ready" || updated.status === "failed") {
          loadCurrent(0);
          return;
        }
        statusPollTimer = setTimeout(() => pollStatus(reelId), 2000);
      }
    } catch (e) {
      statusPollTimer = setTimeout(() => pollStatus(reelId), 4000);
    }
  }

  function saveProgress(immediate) {
    const item = current();
    if (!item) return;
    const now = Date.now();
    if (!immediate && now - lastSavedAt < 4000) return;
    lastSavedAt = now;
    const position = item.kind === "reel" ? (player.currentTime || 0) : noteClock.elapsed;
    const body = JSON.stringify({ key: item.key, position_seconds: position });
    if (immediate && navigator.sendBeacon) {
      navigator.sendBeacon("/api/progress", new Blob([body], { type: "application/json" }));
    } else {
      fetch("/api/progress", { method: "POST", headers: { "Content-Type": "application/json" }, body }).catch(() => {});
    }
  }

  function goTo(newIndex, seekTo) {
    if (newIndex < 0 || newIndex >= timeline.length) return;
    saveProgress(true);
    index = newIndex;
    loadCurrent(seekTo || 0);
  }

  function next() { goTo(index + 1, 0); }
  function prev() { goTo(index - 1, 0); }

  function togglePlay() {
    const item = current();
    if (!item) return;
    if (item.kind === "reel") {
      if (player.paused) player.play().catch(() => {});
      else player.pause();
    } else {
      if (noteClock.playing) pauseNoteClock();
      else startNoteClock();
    }
  }

  function seekRelative(delta) {
    const item = current();
    if (!item) return;
    if (item.kind === "reel") {
      player.currentTime = Math.max(0, (player.currentTime || 0) + delta);
    } else {
      noteClock.elapsed = Math.max(0, Math.min(noteClock.duration, noteClock.elapsed + delta));
      updateNoteSeekUI();
      saveProgress(true);
    }
  }

  function cycleSpeed() {
    speedIdx = (speedIdx + 1) % SPEEDS.length;
    player.playbackRate = SPEEDS[speedIdx];
    speedBtn.textContent = `${SPEEDS[speedIdx]}x`;
  }

  function toggleAuto() {
    autoAdvance = !autoAdvance;
    autoBtn.textContent = `Auto: ${autoAdvance ? "On" : "Off"}`;
    if (!autoAdvance && autoSkipTimer) {
      clearTimeout(autoSkipTimer);
      autoSkipTimer = null;
    }
    if (autoAdvance && current() && current().kind === "reel" && current().status === "failed" && !autoSkipTimer) {
      autoSkipTimer = setTimeout(() => next(), FAILED_AUTO_SKIP_MS);
    }
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else stage.requestFullscreen().catch(() => {});
  }

  player.addEventListener("play", () => { playBtn.textContent = "⏸"; });
  player.addEventListener("pause", () => { playBtn.textContent = "▶"; saveProgress(true); });
  player.addEventListener("ended", () => {
    saveProgress(true);
    if (autoAdvance) next();
  });
  player.addEventListener("timeupdate", () => {
    if (!isScrubbing && player.duration) {
      seek.value = String((player.currentTime / player.duration) * 1000);
    }
    saveProgress(false);
  });
  player.addEventListener("error", () => {
    if (current() && current().kind === "reel") showStatus("Playback error on this file.", true);
  });

  seek.addEventListener("input", () => {
    isScrubbing = true;
    const item = current();
    if (!item) return;
    if (item.kind === "reel") {
      if (player.duration) player.currentTime = (Number(seek.value) / 1000) * player.duration;
    } else if (noteClock.duration) {
      noteClock.elapsed = (Number(seek.value) / 1000) * noteClock.duration;
    }
  });
  seek.addEventListener("change", () => {
    isScrubbing = false;
    saveProgress(true);
  });

  playBtn.addEventListener("click", togglePlay);
  nextBtn.addEventListener("click", next);
  prevBtn.addEventListener("click", prev);
  back10Btn.addEventListener("click", () => seekRelative(-10));
  fwd10Btn.addEventListener("click", () => seekRelative(10));
  speedBtn.addEventListener("click", cycleSpeed);
  autoBtn.addEventListener("click", toggleAuto);
  fsBtn.addEventListener("click", toggleFullscreen);
  retryBtn.addEventListener("click", async () => {
    const item = current();
    if (!item || item.kind !== "reel") return;
    if (autoSkipTimer) { clearTimeout(autoSkipTimer); autoSkipTimer = null; }
    await api(`/api/reels/${item.id}/retry`, { method: "POST" });
    item.status = "pending";
    loadCurrent(0);
  });

  document.addEventListener("keydown", (e) => {
    if (!importModal.classList.contains("hidden") || !jumpModal.classList.contains("hidden")) return;
    switch (e.key) {
      case " ": e.preventDefault(); togglePlay(); break;
      case "ArrowLeft": seekRelative(-10); break;
      case "ArrowRight": seekRelative(10); break;
      case "ArrowUp": prev(); break;
      case "ArrowDown": next(); break;
      case "f": case "F": toggleFullscreen(); break;
      case "s": case "S": cycleSpeed(); break;
    }
  });

  window.addEventListener("beforeunload", () => saveProgress(true));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") saveProgress(true);
  });

  // --- Import modal ---
  function openImport() { importModal.classList.remove("hidden"); }
  function closeImport() { importModal.classList.add("hidden"); }

  importBtn.addEventListener("click", openImport);
  closeImportBtn.addEventListener("click", closeImport);
  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("drag"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag");
    handleFiles(e.dataTransfer.files);
  });
  fileInput.addEventListener("change", () => handleFiles(fileInput.files));

  async function handleFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const form = new FormData();
    for (const f of fileList) form.append("files", f);
    importResult.textContent = "Importing…";
    try {
      const result = await api("/api/import", { method: "POST", body: form });
      importResult.textContent =
        `Found ${result.reels_found} reel link(s) and ${result.notes_found} message(s): ` +
        `${result.new} new, ${result.duplicate} already known.`;
      await refreshTimeline();
    } catch (e) {
      importResult.textContent = "Import failed. Check the file format and try again.";
    }
  }

  async function refreshTimeline() {
    const currentKey = current() ? current().key : null;
    timeline = await api("/api/timeline");
    if (currentKey != null) {
      const i = timeline.findIndex((t) => t.key === currentKey);
      if (i !== -1) index = i;
    }
    updateMeta();
    const item = current();
    if (item && item.kind === "reel" && item.status !== "ready" && !statusPollTimer) {
      loadCurrent(0);
    } else if (item && item.kind === "notes" && notesPane.classList.contains("hidden")) {
      loadCurrent(0);
    }
  }

  // --- Jump to date ---
  function openJump() {
    jumpResult.textContent = "";
    const item = current();
    if (item && item.sent_at) {
      jumpDate.value = new Date(item.sent_at).toISOString().slice(0, 10);
    }
    jumpModal.classList.remove("hidden");
  }
  function closeJump() { jumpModal.classList.add("hidden"); }

  jumpBtn.addEventListener("click", openJump);
  jumpCancelBtn.addEventListener("click", closeJump);
  jumpGoBtn.addEventListener("click", () => {
    if (!jumpDate.value) return;
    const target = new Date(jumpDate.value + "T00:00:00").getTime();
    let found = timeline.findIndex((t) => t.sent_at != null && t.sent_at >= target);
    if (found === -1) {
      // date is after everything we have - go to the last item instead
      found = timeline.length - 1;
    }
    if (found === -1) {
      jumpResult.textContent = "No dated items to jump to yet.";
      return;
    }
    goTo(found, 0);
    closeJump();
  });

  // --- Init ---
  async function init() {
    autoBtn.textContent = `Auto: ${autoAdvance ? "On" : "Off"}`;
    speedBtn.textContent = `${SPEEDS[speedIdx]}x`;

    const [tl, progress] = await Promise.all([
      api("/api/timeline"),
      api("/api/progress"),
    ]);
    timeline = tl;

    if (!timeline.length) {
      openImport();
      loadCurrent(0);
      return;
    }

    let startIndex = 0;
    let startSeek = 0;
    if (progress && progress.current_key) {
      const i = timeline.findIndex((t) => t.key === progress.current_key);
      if (i !== -1) {
        startIndex = i;
        startSeek = progress.position_seconds || 0;
      }
    }
    index = startIndex;
    loadCurrent(startSeek);
  }

  init();
})();
