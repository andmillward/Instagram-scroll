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
  const senderName = document.getElementById("senderName");
  const sentDate = document.getElementById("sentDate");
  const counter = document.getElementById("counter");
  const statusOverlay = document.getElementById("statusOverlay");
  const statusText = document.getElementById("statusText");
  const retryBtn = document.getElementById("retryBtn");
  const stage = document.getElementById("stage");

  const importModal = document.getElementById("importModal");
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const importResult = document.getElementById("importResult");
  const closeImportBtn = document.getElementById("closeImportBtn");

  const SPEEDS = [1, 1.25, 1.5, 2];

  let reels = [];
  let index = 0;
  let speedIdx = 0;
  let autoAdvance = true;
  let isScrubbing = false;
  let statusPollTimer = null;
  let autoSkipTimer = null;
  let lastSavedAt = 0;

  function fmtDate(ms) {
    if (!ms) return "";
    const d = new Date(ms);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : null;
  }

  function current() {
    return reels[index];
  }

  function clearTimers() {
    if (statusPollTimer) { clearTimeout(statusPollTimer); statusPollTimer = null; }
    if (autoSkipTimer) { clearTimeout(autoSkipTimer); autoSkipTimer = null; }
  }

  function updateMeta() {
    const reel = current();
    if (!reel) return;
    senderName.textContent = reel.sender ? `From ${reel.sender}` : "";
    sentDate.textContent = fmtDate(reel.sent_at);
    counter.textContent = `${index + 1} / ${reels.length}`;
  }

  function showStatus(text, showRetry) {
    statusText.textContent = text;
    retryBtn.classList.toggle("hidden", !showRetry);
    statusOverlay.classList.remove("hidden");
  }

  function hideStatus() {
    statusOverlay.classList.add("hidden");
  }

  function loadCurrent(seekTo) {
    clearTimers();
    const reel = current();
    updateMeta();

    if (!reel) {
      showStatus("You're all caught up. Import more reels with the + button.", false);
      player.removeAttribute("src");
      return;
    }

    if (reel.status === "ready") {
      hideStatus();
      player.src = `/api/video/${reel.shortcode}`;
      player.playbackRate = SPEEDS[speedIdx];
      const onMeta = () => {
        player.currentTime = seekTo || 0;
        player.play().catch(() => {});
        player.removeEventListener("loadedmetadata", onMeta);
      };
      player.addEventListener("loadedmetadata", onMeta);
      return;
    }

    if (reel.status === "failed") {
      showStatus(`Skipped: this reel couldn't be fetched (${reel.error || "unavailable"}).`, true);
      if (autoAdvance) {
        autoSkipTimer = setTimeout(() => next(), 3000);
      }
      return;
    }

    // pending / fetching
    showStatus("Fetching video…", false);
    pollStatus(reel.id);
  }

  async function pollStatus(reelId) {
    try {
      const updated = await api(`/api/reels/${reelId}`);
      const i = reels.findIndex((r) => r.id === reelId);
      if (i !== -1) reels[i] = updated;
      if (current() && current().id === reelId) {
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
    const reel = current();
    if (!reel) return;
    const now = Date.now();
    if (!immediate && now - lastSavedAt < 4000) return;
    lastSavedAt = now;
    const body = JSON.stringify({ reel_id: reel.id, position_seconds: player.currentTime || 0 });
    if (immediate && navigator.sendBeacon) {
      navigator.sendBeacon("/api/progress", new Blob([body], { type: "application/json" }));
    } else {
      fetch("/api/progress", { method: "POST", headers: { "Content-Type": "application/json" }, body }).catch(() => {});
    }
  }

  function goTo(newIndex, seekTo) {
    if (newIndex < 0 || newIndex >= reels.length) return;
    saveProgress(true);
    index = newIndex;
    loadCurrent(seekTo || 0);
  }

  function next() { goTo(index + 1, 0); }
  function prev() { goTo(index - 1, 0); }

  function togglePlay() {
    if (player.paused) player.play().catch(() => {});
    else player.pause();
  }

  function cycleSpeed() {
    speedIdx = (speedIdx + 1) % SPEEDS.length;
    player.playbackRate = SPEEDS[speedIdx];
    speedBtn.textContent = `${SPEEDS[speedIdx]}x`;
  }

  function toggleAuto() {
    autoAdvance = !autoAdvance;
    autoBtn.textContent = `Auto: ${autoAdvance ? "On" : "Off"}`;
    if (autoAdvance && current() && current().status === "failed" && !autoSkipTimer) {
      autoSkipTimer = setTimeout(() => next(), 1500);
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
    showStatus("Playback error on this file.", true);
  });

  seek.addEventListener("input", () => {
    isScrubbing = true;
    if (player.duration) player.currentTime = (Number(seek.value) / 1000) * player.duration;
  });
  seek.addEventListener("change", () => {
    isScrubbing = false;
    saveProgress(true);
  });

  playBtn.addEventListener("click", togglePlay);
  nextBtn.addEventListener("click", next);
  prevBtn.addEventListener("click", prev);
  back10Btn.addEventListener("click", () => { player.currentTime = Math.max(0, player.currentTime - 10); });
  fwd10Btn.addEventListener("click", () => { player.currentTime = (player.currentTime || 0) + 10; });
  speedBtn.addEventListener("click", cycleSpeed);
  autoBtn.addEventListener("click", toggleAuto);
  fsBtn.addEventListener("click", toggleFullscreen);
  retryBtn.addEventListener("click", async () => {
    const reel = current();
    if (!reel) return;
    if (autoSkipTimer) { clearTimeout(autoSkipTimer); autoSkipTimer = null; }
    await api(`/api/reels/${reel.id}/retry`, { method: "POST" });
    reel.status = "pending";
    loadCurrent(0);
  });

  document.addEventListener("keydown", (e) => {
    if (!importModal.classList.contains("hidden")) return;
    switch (e.key) {
      case " ": e.preventDefault(); togglePlay(); break;
      case "ArrowLeft": player.currentTime = Math.max(0, player.currentTime - 10); break;
      case "ArrowRight": player.currentTime = (player.currentTime || 0) + 10; break;
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
      importResult.textContent = `Found ${result.found} reel link(s): ${result.new} new, ${result.duplicate} already known.`;
      await refreshReels();
    } catch (e) {
      importResult.textContent = "Import failed. Check the file format and try again.";
    }
  }

  async function refreshReels() {
    const currentId = current() ? current().id : null;
    reels = await api("/api/reels");
    if (currentId != null) {
      const i = reels.findIndex((r) => r.id === currentId);
      if (i !== -1) index = i;
    }
    updateMeta();
    if (current() && current().status !== "ready" && !statusPollTimer) {
      loadCurrent(0);
    }
  }

  async function init() {
    autoBtn.textContent = `Auto: ${autoAdvance ? "On" : "Off"}`;
    speedBtn.textContent = `${SPEEDS[speedIdx]}x`;

    const [reelList, progress] = await Promise.all([
      api("/api/reels"),
      api("/api/progress"),
    ]);
    reels = reelList;

    if (!reels.length) {
      openImport();
      loadCurrent(0);
      return;
    }

    let startIndex = 0;
    if (progress && progress.current_reel_id != null) {
      const i = reels.findIndex((r) => r.id === progress.current_reel_id);
      if (i !== -1) startIndex = i;
    }
    index = startIndex;
    loadCurrent(progress ? progress.position_seconds : 0);
  }

  init();
})();
