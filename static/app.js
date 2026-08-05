const state = {
  localFile: null,
  localUrl: null,
  jobId: null,
  metadata: null,
  transcript: { segments: [] },
  highlights: { clips: [] },
  pollTimer: null,
  taskTimer: null,
  renderProgress: {},
  activeClipId: null,
  activeJobId: null,
  trackedTaskIds: new Set(),
  syncedTaskIds: new Set(),
  trimFocus: "start",
  trimFineBase: 0,
  trimSensitivity: "normal",
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

const el = {
  fileInput: $("fileInput"),
  uploadButton: $("uploadButton"),
  previewButton: $("previewButton"),
  previewTopButton: $("previewTopButton"),
  transcribeButton: $("transcribeButton"),
  transcribeEngine: $("transcribeEngine"),
  cloudTranscribeOptions: $("cloudTranscribeOptions"),
  volcengineApiKey: $("volcengineApiKey"),
  volcengineResourceId: $("volcengineResourceId"),
  volcengineAudioUrl: $("volcengineAudioUrl"),
  volcenginePollInterval: $("volcenginePollInterval"),
  volcengineState: $("volcengineState"),
  tosAccessKey: $("tosAccessKey"),
  tosSecretKey: $("tosSecretKey"),
  tosEndpoint: $("tosEndpoint"),
  tosRegion: $("tosRegion"),
  tosBucket: $("tosBucket"),
  tosPrefix: $("tosPrefix"),
  tosUrlExpires: $("tosUrlExpires"),
  tosState: $("tosState"),
  saveAllCloudButton: $("saveAllCloudButton"),
  clearVolcengineButton: $("clearVolcengineButton"),
  clearTosButton: $("clearTosButton"),
  pauseButton: $("pauseButton"),
  stopButton: $("stopButton"),
  analyzeButton: $("analyzeButton"),
  renderAllButton: $("renderAllButton"),
  exportButton: $("exportButton"),
  refreshLibraryButton: $("refreshLibraryButton"),
  sourceVideo: $("sourceVideo"),
  metadata: $("metadata"),
  previewStatus: $("previewStatus"),
  previewStatusText: $("previewStatusText"),
  previewStatusPercent: $("previewStatusPercent"),
  previewProgressBar: $("previewProgressBar"),
  previewStatusTime: $("previewStatusTime"),
  transcript: $("transcript"),
  transcriptCount: $("transcriptCount"),
  transcriptSearchInput: $("transcriptSearchInput"),
  transcriptSearchButton: $("transcriptSearchButton"),
  transcriptSearchResults: $("transcriptSearchResults"),
  transcriptSearchCount: $("transcriptSearchCount"),
  progressBar: $("progressBar"),
  jobMessage: $("jobMessage"),
  stageStat: $("stageStat"),
  elapsedStat: $("elapsedStat"),
  positionStat: $("positionStat"),
  segmentsStat: $("segmentsStat"),
  globalStatus: $("globalStatus"),
  apiKey: $("apiKey"),
  saveKey: $("saveKey"),
  keyState: $("keyState"),
  saveKeyButton: $("saveKeyButton"),
  clearKeyButton: $("clearKeyButton"),
  clipCount: $("clipCount"),
  minSeconds: $("minSeconds"),
  maxSeconds: $("maxSeconds"),
  clips: $("clips"),
  clipSummary: $("clipSummary"),
  library: $("library"),
  analyzeStatus: $("analyzeStatus"),
  exportDirectory: $("exportDirectory"),
  copyTranscriptButton: $("copyTranscriptButton"),
  transcriptModeText: $("transcriptModeText"),
  chooseExportDirectoryButton: $("chooseExportDirectoryButton"),
  sourceTrimPanel: $("sourceTrimPanel"),
  activeClipTitle: $("activeClipTitle"),
  sourceTimeText: $("sourceTimeText"),
  trimSensitivity: $("trimSensitivity"),
  trimStartInput: $("trimStartInput"),
  trimEndInput: $("trimEndInput"),
  trimDurationInput: $("trimDurationInput"),
  trimStartRange: $("trimStartRange"),
  trimEndRange: $("trimEndRange"),
  trimFineRange: $("trimFineRange"),
  trimFineLabel: $("trimFineLabel"),
  focusTrimStart: $("focusTrimStart"),
  focusTrimEnd: $("focusTrimEnd"),
  setStartFromCurrent: $("setStartFromCurrent"),
  setEndFromCurrent: $("setEndFromCurrent"),
  saveTrimButton: $("saveTrimButton"),
  renderActivePreviewButton: $("renderActivePreviewButton"),
  taskSummary: $("taskSummary"),
  taskList: $("taskList"),
  refreshTasksButton: $("refreshTasksButton"),
  clearFinishedTasksButton: $("clearFinishedTasksButton"),
  resetVideoButton: $("resetVideoButton"),
  resetTranscriptButton: $("resetTranscriptButton"),
  clearTranscriptViewButton: $("clearTranscriptViewButton"),
  resetAnalyzeButton: $("resetAnalyzeButton"),
  clearClipsButton: $("clearClipsButton"),
  clearExportDirectoryButton: $("clearExportDirectoryButton"),
  refreshStorageButton: $("refreshStorageButton"),
  cleanBrowserPreviewButton: $("cleanBrowserPreviewButton"),
  cleanClipPreviewButton: $("cleanClipPreviewButton"),
  cleanAudioCacheButton: $("cleanAudioCacheButton"),
  storageSummary: $("storageSummary"),
  storageList: $("storageList"),
  transcribeStats: $("transcribeStats"),
  refreshHealthButton: $("refreshHealthButton"),
  healthSummary: $("healthSummary"),
  healthList: $("healthList"),
};


function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}


function healthMessage(item) {
  if (item.id === "disk") return `${formatBytes(item.free)} free / ${formatBytes(item.total)} total`;
  const parts = [];
  if (item.version) parts.push(item.version);
  if (item.message) parts.push(item.message);
  if (item.error) parts.push(item.error);
  if (item.python) parts.push(`Python: ${item.python}`);
  if (item.install_command) parts.push(`Install: ${item.install_command}`);
  return parts.join(" ? ") || (item.ok ? "OK" : "Needs attention");
}

async function refreshHealth() {
  if (!el.healthSummary || !el.healthList) return;
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    const checks = data.checks || [];
    const failed = checks.filter((item) => !item.ok);
    el.healthSummary.textContent = data.ok ? `Ready · ${failed.length} warnings` : `Needs attention · ${failed.length} warnings`;
    el.healthList.innerHTML = "";
    checks.forEach((item) => {
      const row = document.createElement("div");
      row.className = `health-item ${item.ok ? "ok" : "warn"}`;
      row.innerHTML = `<strong>${escapeHtml(item.label)}</strong><span>${item.ok ? "OK" : "Check"}</span><div class="small">${escapeHtml(healthMessage(item))}</div>`;
      el.healthList.appendChild(row);
    });
  } catch (err) {
    el.healthSummary.textContent = `Health check failed: ${err.message}`;
  }
}

async function refreshStorage() {
  if (!el.storageSummary || !el.storageList) return;
  const data = await api("/api/storage");
  const encoder = data.encoder?.label || "未检测";
  el.storageSummary.textContent = `总占用 ${formatBytes(data.total_size)} · 预览编码器：${encoder}`;
  el.storageList.innerHTML = "";
  (data.items || []).forEach((item) => {
    const row = document.createElement("div");
    row.className = "storage-item";
    row.innerHTML = `
      <div><strong>${escapeHtml(item.title)}</strong><div class="small">${escapeHtml(item.job_id)} · ${escapeHtml(item.created_at || "")}</div></div>
      <div class="small">总 ${formatBytes(item.total_size)} · 原片 ${formatBytes(item.source_size)} · 兼容预览 ${formatBytes(item.browser_preview_size)} · 候选预览 ${formatBytes(item.clip_preview_size)} · 音频 ${formatBytes(item.audio_size)}</div>
    `;
    el.storageList.appendChild(row);
  });
}

async function cleanupStorage(categories) {
  if (!categories.length) return;
  const names = { browser_preview: "兼容预览", clip_previews: "候选预览", audio: "音频缓存" };
  const label = categories.map((c) => names[c] || c).join("、");
  if (!confirm(`确定清理全部任务的${label}吗？不会删除原视频和文字稿。`)) return;
  await api("/api/storage/cleanup", { method: "POST", body: JSON.stringify({ categories }) });
  await refreshStorage();
  await refreshLibrary();
  if (state.jobId) await loadJob(state.jobId);
  toast(`${label}已清理。`);
}

function taskTypeText(type) {
  return { preview: "\u5019\u9009\u9884\u89c8", export: "\u539f\u753b\u8d28\u5bfc\u51fa", transcribe: "\u8bed\u97f3\u8f6c\u5199", analyze: "DeepSeek \u5206\u6790" }[type] || "\u540e\u53f0\u4efb\u52a1";
}

function taskStatusText(status) {
  return { queued: "排队中", running: "运行中", done: "已完成", error: "失败", cancelled: "已取消" }[status] || status || "未知";
}

function taskStatusClass(status) {
  if (["done"].includes(status)) return "done";
  if (["error"].includes(status)) return "error";
  if (["cancelled"].includes(status)) return "cancelled";
  if (["queued", "running"].includes(status)) return "running";
  return "";
}

function taskTitle(task) {
  if (task.type === "export") return `导出 ${task.clip_ids?.length || 0} 条片段`;
  if (task.type === "transcribe") return "转写文字稿";
  if (task.type === "analyze") return "筛选金句片段";
  const clip = (state.highlights.clips || []).find((item) => item.id === task.clip_id);
  return clip?.title || task.clip_id || task.task_id;
}

function replaceClipById(clipId, nextClip, source = "") {
  if (!clipId || !nextClip) return false;
  if (nextClip.id && nextClip.id !== clipId) {
    toast(`片段回写已拦截：任务返回的是 ${nextClip.id}，当前处理的是 ${clipId}。`);
    console.warn("clip id mismatch", { source, requested: clipId, returned: nextClip.id });
    return false;
  }
  const index = state.highlights.clips.findIndex((clip) => clip.id === clipId);
  if (index < 0) return false;
  state.highlights.clips[index] = { ...state.highlights.clips[index], ...nextClip, id: clipId };
  return true;
}

function syncCompletedTasks(tasks) {
  let changed = false;
  tasks.forEach((task) => {
    if (task.status !== "done") return;
    if (state.syncedTaskIds.has(task.task_id)) return;
    const shouldSync = state.trackedTaskIds.has(task.task_id) || ["analyze", "export", "transcribe"].includes(task.type);
    if (!shouldSync) return;
    if (task.highlights) {
      state.highlights = task.highlights;
      changed = true;
    }
    if (task.clip) {
      changed = replaceClipById(task.clip_id || task.clip.id, task.clip, "task-sync") || changed;
    }
    (task.exported || []).forEach((clip) => {
      changed = replaceClipById(clip.id, clip, "export-sync") || changed;
    });
    state.syncedTaskIds.add(task.task_id);
  });
  if (changed) renderClips();
}

async function refreshTasks() {
  if (!el.taskList || !el.taskSummary) return;
  const suffix = state.jobId ? `?job_id=${encodeURIComponent(state.jobId)}&limit=20` : "?limit=20";
  const data = await api(`/api/tasks${suffix}`);
  const tasks = data.tasks || [];
  const active = tasks.filter((task) => ["queued", "running"].includes(task.status));
  syncCompletedTasks(tasks);
  el.taskSummary.textContent = `${tasks.length} 个任务，${active.length} 个进行中`;
  if (!tasks.length) {
    el.taskList.className = "task-list task-list-empty";
    el.taskList.textContent = "暂无后台任务。";
    return;
  }
  el.taskList.className = "task-list";
  el.taskList.innerHTML = "";
  tasks.forEach((task) => {
    const row = document.createElement("div");
    row.className = `task-item ${taskStatusClass(task.status)}`;
    const percent = task.percent ?? Math.round((task.progress || 0) * 100);
    const elapsed = formatShortTime(task.elapsed || 0);
    const canCancel = ["queued", "running"].includes(task.status);
    const canRetry = ["error", "cancelled"].includes(task.status);
    row.innerHTML = `
      <div class="task-item-top">
        <strong>${escapeHtml(taskTypeText(task.type))} · ${escapeHtml(taskTitle(task))}</strong>
        <span>${escapeHtml(taskStatusText(task.status))} · ${percent}%</span>
      </div>
      <div class="progress-bar"><span style="width:${Math.max(0, Math.min(100, percent))}%"></span></div>
      <div class="task-item-bottom">
        <span>${escapeHtml(task.message || "等待任务状态")} · 已用 ${elapsed}${task.encoder ? ` · ${escapeHtml(task.encoder)}` : ""}</span>
        <span class="task-item-actions">
          ${canRetry ? `<button data-task-id="${encodeURIComponent(task.task_id || "")}" data-action="retry-task" type="button">重试</button>` : ""}
          ${canCancel ? `<button data-task-id="${encodeURIComponent(task.task_id || "")}" data-action="cancel-task" type="button">取消</button>` : ""}
        </span>
      </div>
    `;
    const retry = row.querySelector("[data-action='retry-task']");
    if (retry) retry.addEventListener("click", async () => { await retryTask(decodeURIComponent(retry.dataset.taskId)); });
    const cancel = row.querySelector("[data-action='cancel-task']");
    if (cancel) cancel.addEventListener("click", async () => { await cancelRender(decodeURIComponent(cancel.dataset.taskId)); await refreshTasks(); });
    el.taskList.appendChild(row);
  });
}

async function clearFinishedTasks() {
  if (!el.taskList) return;
  const data = await api("/api/tasks/clear-finished", { method: "POST", body: JSON.stringify({ job_id: state.jobId || null }) });
  toast(`已清理 ${data.removed || 0} 个已完成任务记录。`);
  await refreshTasks();
}

async function retryTask(taskId) {
  if (!taskId) return;
  const data = await api("/api/tasks/retry", { method: "POST", body: JSON.stringify({ task_id: taskId }) });
  toast("重试任务已加入队列。");
  await refreshTasks();
  return data.task;
}
function formatClock(total) {
  const value = Math.max(0, Number(total || 0));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = value % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${seconds.toFixed(3).padStart(6, "0")}`;
}

function formatShortTime(total) {
  if (total === null || total === undefined || Number.isNaN(Number(total))) return "\u8ba1\u7b97\u4e2d";
  const value = Math.max(0, Math.round(Number(total)));
  const minutes = Math.floor(value / 60);
  const seconds = value % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function updateTranscribeStats(job = {}) {
  const stageMap = {
    queued: "\u6392\u961f\u4e2d",
    extracting: "\u63d0\u53d6\u97f3\u9891",
    transcribing: "\u8f6c\u5199\u4e2d",
    paused: "\u5df2\u6682\u505c",
    stopped: "\u5df2\u7ed3\u675f",
    transcribed: "\u8f6c\u5199\u5b8c\u6210",
    error: "\u51fa\u9519",
  };
  const duration = state.metadata?.duration || 0;
  const position = job.transcribed_position || job.latest_segment?.end || 0;
  el.stageStat.textContent = stageMap[job.stage] || "\u7b49\u5f85\u4efb\u52a1";
  el.elapsedStat.textContent = `\u5df2\u7528 ${formatShortTime(job.transcribe_elapsed || 0)}`;
  el.positionStat.textContent = `\u5df2\u5904\u7406 ${formatClock(position)} / ${duration ? formatClock(duration) : "--"}`;
  el.segmentsStat.textContent = `${job.segment_count || state.transcript.segments.length || 0} \u6bb5`;
}

function updatePreviewStatus(job) {
  if (!job || !["previewing", "preview_ready", "preview_error"].includes(job.stage)) return;
  el.previewStatus.hidden = false;
  const progress = typeof job.preview_progress === "number" ? Math.max(0, Math.min(1, job.preview_progress)) : 0;
  const percent = Math.round(progress * 100);
  el.previewProgressBar.style.width = `${percent}%`;
  el.previewStatusPercent.textContent = job.stage === "preview_error" ? "\u5931\u8d25" : `${percent}%`;
  el.previewStatusText.textContent = job.message || "\u6b63\u5728\u751f\u6210\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8 MP4";
  if (job.stage === "preview_ready") {
    el.previewStatusTime.textContent = "\u517c\u5bb9\u9884\u89c8\u5df2\u5b8c\u6210\uff0c\u53ef\u4ee5\u6b63\u5e38\u67e5\u770b\u753b\u9762\u3002";
  } else if (job.stage === "preview_error") {
    el.previewStatusTime.textContent = "\u751f\u6210\u5931\u8d25\uff0c\u53ef\u4ee5\u7ee7\u7eed\u8f6c\u5199\uff1b\u6700\u7ec8\u5bfc\u51fa\u4ecd\u4f1a\u5c1d\u8bd5\u4f7f\u7528\u539f\u89c6\u9891\u3002";
  } else {
    el.previewStatusTime.textContent = `\u5df2\u7528 ${formatShortTime(job.preview_elapsed)}\uff0c\u9884\u8ba1\u5269\u4f59 ${formatShortTime(job.preview_remaining)}`;
  }
}

function parseClock(text) {
  const parts = String(text).trim().split(":").map(Number);
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return Number(text);
}

function setStatus(message) {
  el.globalStatus.textContent = message || "等待任务";
}

function toast(message) {
  el.jobMessage.textContent = message;
  setStatus(message);
}

function setPreviewButtonsDisabled(disabled) {
  [el.previewButton, el.previewTopButton].forEach((button) => {
    if (button) button.disabled = !!disabled;
  });
}


async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: options.body instanceof FormData ? options.headers : { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || "请求失败");
  return data;
}

function updateMetadata(meta) {
  state.metadata = meta;
  if (!meta) {
    el.metadata.textContent = "还没有载入视频。";
    return;
  }
  const sizeMb = meta.source_size ? `${(meta.source_size / 1024 / 1024).toFixed(1)} MB` : "未知大小";
  const resolution = meta.width && meta.height ? `${meta.width} x ${meta.height}` : "未知分辨率";
  const duration = meta.duration ? formatClock(meta.duration) : "未知时长";
  const audio = meta.has_audio === false ? "未检测到音轨" : "有音轨";
  el.metadata.innerHTML = `
    <strong>${escapeHtml(meta.title || meta.original_file || "未命名视频")}</strong><br>
    ${sizeMb} · ${duration} · ${resolution} · ${audio}
  `;
}

function applyBrowserPreviewIfReady(job) {
  const meta = job.metadata || state.metadata || {};
  const file = meta.browser_preview_file;
  if (!file || !state.jobId) return false;
  const url = `/media/${state.jobId}/${file}`;
  if (!el.sourceVideo.src.endsWith(url)) {
    const currentTime = el.sourceVideo.currentTime || 0;
    el.sourceVideo.src = url;
    el.sourceVideo.addEventListener("loadedmetadata", () => {
      el.sourceVideo.currentTime = Math.min(currentTime, el.sourceVideo.duration || currentTime);
    }, { once: true });
    toast("\u5df2\u5207\u6362\u5230\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8\u3002\u539f\u59cb\u89c6\u9891\u4ecd\u4f1a\u7528\u4e8e\u8f6c\u5199\u548c\u5bfc\u51fa\u3002");
  }
  state.metadata = meta;
  updateMetadata(meta);
  setPreviewButtonsDisabled(true);
  return true;
}

function needsBrowserPreview(meta) {
  if (!meta) return false;
  return !meta.browser_preview_file;
}

async function requestBrowserPreview() {
  if (!state.jobId) return;
  updatePreviewStatus({ stage: "previewing", message: "\u6b63\u5728\u751f\u6210\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8 MP4", preview_progress: 0, preview_elapsed: 0, preview_remaining: null });
  setPreviewButtonsDisabled(true);
  await api("/api/video/browser-preview", { method: "POST", body: JSON.stringify({ job_id: state.jobId }) });
  startPolling();
}

function transcriptText(segments = state.transcript.segments) {
  return (segments || []).map((s) => `[${formatClock(s.start)} - ${formatClock(s.end)}] ${s.text}`).join("\n");
}

function updateTranscript(segments) {
  state.transcript = { segments: segments || [] };
  const count = state.transcript.segments.length;
  el.transcriptCount.textContent = `${count} 段`;
  if (el.transcriptModeText) el.transcriptModeText.textContent = count ? `完整显示 ${count} 段文字稿` : "完整显示文字稿";
  el.transcript.textContent = transcriptText();
  el.analyzeButton.disabled = !state.jobId || count === 0;
}

function highlightTerms(text, terms) {
  let out = escapeHtml(text);
  terms.forEach((term) => {
    const escaped = escapeHtml(term).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    out = out.replace(new RegExp(escaped, "gi"), (match) => `<mark>${match}</mark>`);
  });
  return out;
}

function searchTranscript() {
  const box = el.transcriptSearchResults;
  if (!box) return;
  const raw = (el.transcriptSearchInput?.value || "").trim();
  const terms = raw.split(/\s+/).filter(Boolean);
  const segments = state.transcript.segments || [];
  if (terms.length === 0) {
    box.innerHTML = `<div class="search-empty">\u8bf7\u8f93\u5165\u5173\u952e\u8bcd\u540e\u70b9\u51fb\u641c\u7d22\u3002</div>`;
    if (el.transcriptSearchCount) el.transcriptSearchCount.textContent = "";
    return;
  }
  const lowerTerms = terms.map((term) => term.toLowerCase());
  const hits = segments.filter((seg) => {
    const text = String(seg.text || "").toLowerCase();
    return lowerTerms.every((term) => text.includes(term));
  });
  if (el.transcriptSearchCount) {
    el.transcriptSearchCount.textContent = hits.length
      ? `\u547d\u4e2d ${hits.length} \u6761`
      : "\u65e0\u7ed3\u679c";
  }
  if (hits.length === 0) {
    box.innerHTML = `<div class="search-empty">\u65e0\u5339\u914d\u7ed3\u679c\uff0c\u8bd5\u8bd5\u5176\u4ed6\u8bcd\u6c47\u3002</div>`;
    return;
  }
  box.innerHTML = hits
    .map((seg) => {
      const time = `[${formatClock(seg.start)} - ${formatClock(seg.end)}]`;
      return `<div class="search-result" data-start="${Number(seg.start) || 0}" data-end="${Number(seg.end) || 0}" title="\u70b9\u51fb\u8df3\u8f6c\u5230\u8be5\u53e5\u8d77\u59cb\u65f6\u523b\uff08\u6682\u505c\uff09">
        <span class="search-time">${time}</span>
        <span class="search-text">${highlightTerms(seg.text, terms)}</span>
      </div>`;
    })
    .join("");
}

function jumpToSearchResult(row) {
  if (!row || !el.sourceVideo) return;
  const start = Number(row.dataset.start) || 0;
  const end = Number(row.dataset.end) || 0;
  el.sourceVideo.pause();
  setSourcePreviewTime(start);
  if (el.sourceTrimPanel) {
    showManualTrimPanel(start, end > start ? end : null);
    toast(`\u5df2\u8df3\u8f6c\u5230 ${formatClock(start)} \u5e76\u6682\u505c\uff0c\u88c1\u5207\u533a\u95f4\u5df2\u540c\u6b65\u4e3a ${formatClock(start)} - ${formatClock(end > start ? end : start + 15)}\u3002`);
  } else {
    toast(`\u5df2\u8df3\u8f6c\u5230 ${formatClock(start)}\uff0c\u5df2\u6682\u505c\u3002`);
  }
}
function showTranscriptPlaceholder(message) {
  if (state.transcript.segments.length > 0) return;
  el.transcript.textContent = message || "\u6b63\u5728\u51c6\u5907\u8f6c\u5199...";
}

function clipStatusText(clip) {
  const map = {
    pending: "待生成",
    ready: "可预览",
    needs_render: "需重切",
    confirmed: "已确认",
    exported: "已导出",
    error: "失败",
  };
  return map[clip.status] || clip.status || "待生成";
}


function findClip(clipId) {
  return (state.highlights.clips || []).find((c) => c.id === clipId);
}

function activeClip() {
  return state.activeClipId ? findClip(state.activeClipId) : null;
}

function trimVideoDuration() {
  return Number(state.metadata?.duration || el.sourceVideo.duration || 0) || 0;
}
function trimSensitivityConfig() {
  const value = el.trimSensitivity?.value || state.trimSensitivity || "normal";
  const configs = {
    coarse: { mainStep: 0.5, fineRange: 8, fineStep: 0.05, label: "\u5feb\u901f\u5b9a\u4f4d" },
    normal: { mainStep: 0.1, fineRange: 3, fineStep: 0.02, label: "\u6807\u51c6" },
    fine: { mainStep: 0.02, fineRange: 1, fineStep: 0.01, label: "\u7cbe\u7ec6" },
    frame: { mainStep: 1 / 30, fineRange: 0.5, fineStep: 1 / 30, label: "\u9010\u5e27" },
  };
  return configs[value] || configs.normal;
}

function syncFineSliderBounds() {
  const config = trimSensitivityConfig();
  if (!el.trimFineRange) return;
  el.trimFineRange.min = String(-config.fineRange);
  el.trimFineRange.max = String(config.fineRange);
  el.trimFineRange.step = String(config.fineStep);
}


function clampTrimTime(value) {
  const duration = trimVideoDuration();
  const numeric = Math.max(0, Number(value) || 0);
  return duration ? Math.min(duration, numeric) : numeric;
}

function setSourcePreviewTime(value) {
  const next = clampTrimTime(value);
  if (Number.isFinite(next)) el.sourceVideo.currentTime = next;
  if (el.sourceTimeText) el.sourceTimeText.textContent = `\u5f53\u524d ${formatClock(next)}`;
}

function syncTrimSliderBounds() {
  const duration = Math.max(1, trimVideoDuration());
  const config = trimSensitivityConfig();
  state.trimSensitivity = el.trimSensitivity?.value || "normal";
  [el.trimStartRange, el.trimEndRange].forEach((range) => {
    if (!range) return;
    range.min = "0";
    range.max = String(duration);
    range.step = String(config.mainStep);
  });
  syncFineSliderBounds();
}

function updateTrimReadouts(seekTo = null) {
  const start = parseClock(el.trimStartInput.value || 0);
  const end = parseClock(el.trimEndInput.value || 0);
  if (el.trimStartInput) el.trimStartInput.value = formatClock(start);
  if (el.trimEndInput) el.trimEndInput.value = formatClock(end);
  if (el.trimDurationInput) el.trimDurationInput.value = `${Math.max(0, end - start).toFixed(2)} \u79d2`;
  if (el.trimStartRange) el.trimStartRange.value = String(start);
  if (el.trimEndRange) el.trimEndRange.value = String(end);
  if (seekTo !== null) setSourcePreviewTime(seekTo);
}

function setTrimValue(field, value, seek = true) {
  syncTrimSliderBounds();
  const duration = trimVideoDuration();
  let start = parseClock(el.trimStartInput.value || 0);
  let end = parseClock(el.trimEndInput.value || 0);
  const minGap = 0.08;
  if (field === "start") {
    start = clampTrimTime(value);
    start = Math.min(start, Math.max(0, end - minGap));
  } else {
    end = clampTrimTime(value);
    end = Math.max(end, start + minGap);
    if (duration) end = Math.min(duration, end);
  }
  el.trimStartInput.value = formatClock(start);
  el.trimEndInput.value = formatClock(end);
  updateTrimReadouts(seek ? (field === "start" ? start : end) : null);
}

function applyManualTrimInput(field) {
  const input = field === "start" ? el.trimStartInput : el.trimEndInput;
  if (!input) return;
  const raw = input.value;
  const value = parseClock(raw);
  const duration = trimVideoDuration();
  const other = parseClock((field === "start" ? el.trimEndInput : el.trimStartInput).value || 0);
  const minGap = 0.08;
  if (!Number.isFinite(value) || value < 0) {
    toast(field === "start" ? "\u5f00\u5934\u65f6\u95f4\u683c\u5f0f\u65e0\u6548\uff0c\u5df2\u6062\u590d\u539f\u503c" : "\u7ed3\u5c3e\u65f6\u95f4\u683c\u5f0f\u65e0\u6548\uff0c\u5df2\u6062\u590d\u539f\u503c");
    updateTrimReadouts(null);
    return;
  }
  let next = clampTrimTime(value);
  if (field === "start") {
    next = Math.min(next, Math.max(0, other - minGap));
  } else {
    next = Math.max(next, other + minGap);
    if (duration) next = Math.min(duration, next);
  }
  setTrimValue(field, next, true);
  toast(`\u5df2\u8bbe\u7f6e${field === "start" ? "\u5f00\u5934" : "\u7ed3\u5c3e"}\u65f6\u95f4\u4e3a ${formatClock(next)}`);
}

function setFineFocus(field, seek = true) {
  state.trimFocus = field;
  state.trimFineBase = parseClock((field === "start" ? el.trimStartInput : el.trimEndInput).value || 0);
  syncFineSliderBounds();
  if (el.trimFineRange) el.trimFineRange.value = "0";
  const config = trimSensitivityConfig();
  const rangeLabel = config.fineRange < 1 ? `${Math.round(config.fineRange * 1000)}ms` : `${config.fineRange}\u79d2`;
  if (el.trimFineLabel) el.trimFineLabel.textContent = `${field === "start" ? "\u7cbe\u8c03\u5f00\u5934" : "\u7cbe\u8c03\u7ed3\u5c3e"} \u00b1${rangeLabel} \u00b7 ${config.label}`;
  el.focusTrimStart?.classList.toggle("active", field === "start");
  el.focusTrimEnd?.classList.toggle("active", field === "end");
  if (seek) setSourcePreviewTime(state.trimFineBase);
}

function showManualTrimPanel(defaultStart = null, defaultEnd = null) {
  if (!el.sourceTrimPanel) return;
  syncTrimSliderBounds();
  const start = defaultStart == null ? Math.max(0, el.sourceVideo.currentTime || 0) : Math.max(0, Number(defaultStart) || 0);
  const duration = trimVideoDuration();
  const fallbackEnd = Math.min(duration || start + 15, start + 15);
  let end = fallbackEnd;
  if (defaultEnd != null && Number(defaultEnd) > start + 0.08) {
    end = Math.min(Number(defaultEnd), duration || Number(defaultEnd));
    if (end < start + 0.08) end = fallbackEnd;
  }
  state.activeClipId = null;
  el.sourceTrimPanel.hidden = false;
  el.sourceTrimPanel.dataset.clipId = "";
  el.activeClipTitle.textContent = "\u624b\u52a8\u88c1\u5207\uff1a\u62d6\u52a8\u62c9\u6761\u9009\u62e9\u539f\u89c6\u9891\u7247\u6bb5";
  el.trimStartInput.value = formatClock(start);
  el.trimEndInput.value = formatClock(end > start ? end : start + 15);
  updateTrimReadouts(start);
  setFineFocus("start", false);
}

function syncTrimPanelFromClip() {
  const clip = activeClip();
  if (!clip || !el.sourceTrimPanel) return;
  syncTrimSliderBounds();
  const index = state.highlights.clips.findIndex((item) => item.id === clip.id);
  el.sourceTrimPanel.hidden = false;
  el.sourceTrimPanel.dataset.clipId = clip.id;
  el.activeClipTitle.textContent = `\u6b63\u5728\u5fae\u8c03\u7b2c ${index >= 0 ? index + 1 : "?"} \u6761\uff1a${clip.title || clip.id}`;
  el.trimStartInput.value = formatClock(clip.start);
  el.trimEndInput.value = formatClock(clip.end);
  updateTrimReadouts(null);
  setFineFocus("start", false);
}

function setActiveClip(clipId, seekToStart = true) {
  const clip = findClip(clipId);
  if (!clip) return;
  state.activeClipId = clipId;
  syncTrimPanelFromClip();
  if (seekToStart) {
    setSourcePreviewTime(Math.max(0, Number(clip.start)));
    el.sourceVideo.play().catch(() => {});
  }
  toast("\u5df2\u56de\u5230\u539f\u89c6\u9891\uff0c\u53ef\u7528\u62c9\u6761\u5fae\u8c03\u5f00\u5934\u548c\u7ed3\u5c3e");
}

async function saveActiveTrim() {
  const clip = activeClip();
  const start = parseClock(el.trimStartInput.value);
  const end = parseClock(el.trimEndInput.value);
  if (!(end > start)) {
    toast("\u7ed3\u675f\u65f6\u95f4\u5fc5\u987b\u665a\u4e8e\u5f00\u59cb\u65f6\u95f4");
    return null;
  }
  if (!clip) {
    return await createManualClip(start, end);
  }
  await updateClipTime(clip.id, start, end);
  setActiveClip(clip.id, false);
  return findClip(clip.id);
}

async function createManualClip(start, end) {
  const title = `\u624b\u52a8\u7247\u6bb5 ${formatClock(start)}-${formatClock(end)}`;
  const data = await api("/api/clips/manual", { method: "POST", body: JSON.stringify({ job_id: state.jobId, start, end, title }) });
  state.highlights = data.highlights || state.highlights;
  renderClips();
  setActiveClip(data.clip.id, false);
  toast("\u5df2\u4ece\u539f\u89c6\u9891\u521b\u5efa\u624b\u52a8\u5019\u9009\u7247\u6bb5");
  return findClip(data.clip.id);
}

function mediaUrl(path) {
  return `/media/${state.jobId}/${path}`;
}


function exportVerificationText(clip) {
  const verification = clip.export_verification;
  if (!clip.export_file && !clip.export_path) return "";
  if (!verification) return "Export verification pending: original stream copy was requested.";
  if (verification.ok) return "Original stream verification passed: no re-encoding detected.";
  const warnings = (verification.warnings || []).join("; ");
  return `Original stream verification needs review${warnings ? `: ${warnings}` : "."}`;
}

function renderClips() {
  const clips = state.highlights.clips || [];
  el.clipSummary.textContent = `${clips.length} 个候选，${clips.filter((c) => c.confirmed).length} 个已确认`;
  el.renderAllButton.disabled = !clips.length;
  el.exportButton.disabled = !clips.some((c) => c.confirmed);
  if (!clips.length) {
    el.clips.className = "clips-empty";
    el.clips.textContent = "DeepSeek 分析后会在这里出现可预览的候选片段。";
    return;
  }

  el.clips.className = "clips-list";
  el.clips.innerHTML = "";
  clips.forEach((clip, index) => {
    const card = document.createElement("article");
    card.className = "clip-card";
    const badgeClass = clip.status === "confirmed" || clip.status === "exported" ? "confirmed" : clip.status === "error" ? "error" : "";
    const progress = state.renderProgress[clip.id];
    const canCancel = progress?.taskId && ["queued", "running"].includes(progress.status);
    const progressHtml = progress ? `<div class="clip-progress"><div class="clip-progress-top"><span>${escapeHtml(progress.label)}</span><strong>${progress.percent}%</strong></div><div class="progress-bar"><span style="width:${progress.percent}%"></span></div>${canCancel ? `<button data-action="cancel-render" data-task-id="${encodeURIComponent(progress.taskId || "")}">\u53d6\u6d88\u751f\u6210</button>` : ""}</div>` : "";
    const exportVerification = exportVerificationText(clip);
    const exportVerificationHtml = exportVerification ? `<div class="small">${escapeHtml(exportVerification)}</div>` : "";
    card.innerHTML = `
      <div class="clip-top">
        <div class="clip-title">${index + 1}. ${escapeHtml(clip.title || clip.id)}</div>
        <span class="clip-badge ${badgeClass}">${escapeHtml(clipStatusText(clip))}</span>
      </div>
      <div class="clip-body">
        <div>${escapeHtml(clip.quote || "")}</div>
        <div>${escapeHtml(clip.reason || "")}</div>
        <div class="small">${escapeHtml(clip.clip_type || "highlight")} · 置信度 ${escapeHtml(clip.confidence ?? "-")} · 时长 ${(Number(clip.end) - Number(clip.start)).toFixed(1)} 秒</div>
        ${exportVerificationHtml}
      </div>
      <video class="clip-video" controls playsinline ${clip.preview_file ? `src="${escapeHtml(mediaUrl(clip.preview_file))}"` : ""}></video>
      ${progressHtml}
      <div class="clip-tools">
        <label>开始时间<input type="text" data-role="start" value="${formatClock(clip.start)}"></label>
        <label>结束时间<input type="text" data-role="end" value="${formatClock(clip.end)}"></label>
      </div>
      <div class="clip-actions">
        <button data-action="trim-source">回原视频微调</button>
        <button data-action="save-time">保存时间</button>
        <button data-action="render" class="primary">生成预览</button>
        <button data-action="confirm">${clip.confirmed ? "取消确认" : "确认片段"}</button>
        <button data-action="export">导出单条</button>
        <button data-action="reset-time">重置时间</button>
        <button data-action="clear-preview">删预览</button>
        <button data-action="clear-export">清导出记录</button>
        <button data-action="delete" class="danger">删除候选</button>
      </div>
    `;

    card.querySelector("[data-action='trim-source']").addEventListener("click", () => setActiveClip(clip.id));
    card.querySelector("[data-action='save-time']").addEventListener("click", async () => {
      await updateClipTime(clip.id, parseClock(card.querySelector("[data-role='start']").value), parseClock(card.querySelector("[data-role='end']").value));
    });
    card.querySelector("[data-action='render']").addEventListener("click", () => renderPreview(clip.id));
    const cancelButton = card.querySelector("[data-action='cancel-render']");
    if (cancelButton) cancelButton.addEventListener("click", () => cancelRender(decodeURIComponent(cancelButton.dataset.taskId)));
    card.querySelector("[data-action='confirm']").addEventListener("click", () => confirmClip(clip.id, !clip.confirmed));
    card.querySelector("[data-action='export']").addEventListener("click", () => exportSingleClip(clip.id));
    card.querySelector("[data-action='reset-time']").addEventListener("click", () => clipAction(clip.id, "reset_time"));
    card.querySelector("[data-action='clear-preview']").addEventListener("click", () => clipAction(clip.id, "clear_preview"));
    card.querySelector("[data-action='clear-export']").addEventListener("click", () => clipAction(clip.id, "clear_export"));
    card.querySelector("[data-action='delete']").addEventListener("click", () => deleteClip(clip.id));
    el.clips.appendChild(card);
  });
}


async function clipAction(clipId, action) {
  const data = await api("/api/clips/action", { method: "POST", body: JSON.stringify({ job_id: state.jobId, clip_id: clipId, action }) });
  if (data.highlights) state.highlights = data.highlights;
  if (data.clip) {
    const index = state.highlights.clips.findIndex((c) => c.id === clipId);
    if (index >= 0) state.highlights.clips[index] = data.clip;
  }
  if (state.activeClipId === clipId) syncTrimPanelFromClip();
  renderClips();
  await refreshLibrary();
  const labels = { reset_time: "已重置到原始时间", clear_preview: "已删除预览引用", clear_export: "已清除导出记录" };
  toast(labels[action] || "片段已更新");
}

async function deleteClip(clipId) {
  const clip = findClip(clipId);
  if (!clip) return;
  if (!confirm(`确定删除候选片段「${escapeHtml(clip.title || clip.id)}」吗？不会删除原视频。`)) return;
  const data = await api("/api/clips/action", { method: "POST", body: JSON.stringify({ job_id: state.jobId, clip_id: clipId, action: "delete" }) });
  state.highlights = data.highlights || { clips: [] };
  delete state.renderProgress[clipId];
  if (state.activeClipId === clipId) {
    state.activeClipId = null;
    if (el.sourceTrimPanel) el.sourceTrimPanel.hidden = true;
  }
  renderClips();
  await refreshLibrary();
  toast("候选片段已删除。");
}

async function clearAllClips() {
  if (!state.jobId) return;
  if (!confirm("确定清空全部候选片段吗？文字稿和原视频不会删除。")) return;
  const data = await api("/api/clips/action", { method: "POST", body: JSON.stringify({ job_id: state.jobId, action: "clear_all" }) });
  state.highlights = data.highlights || { clips: [] };
  state.renderProgress = {};
  state.activeClipId = null;
  if (el.sourceTrimPanel) el.sourceTrimPanel.hidden = true;
  renderClips();
  await refreshLibrary();
  toast("候选片段已清空，可以重新分析生成。");
}

function resetCurrentVideoView() {
  if (state.localUrl) URL.revokeObjectURL(state.localUrl);
  state.localFile = null;
  state.localUrl = null;
  state.jobId = null;
  state.metadata = null;
  state.transcript = { segments: [] };
  state.highlights = { clips: [] };
  state.renderProgress = {};
  state.activeClipId = null;
  el.sourceVideo.removeAttribute("src");
  el.sourceVideo.load();
  el.fileInput.value = "";
  el.metadata.textContent = "还没有载入视频。";
  el.uploadButton.disabled = true;
  setPreviewButtonsDisabled(true);
  el.transcribeButton.disabled = true;
  el.analyzeButton.disabled = true;
  el.renderAllButton.disabled = true;
  el.exportButton.disabled = true;
  if (el.sourceTrimPanel) el.sourceTrimPanel.hidden = true;
  updateTranscript([]);
  renderClips();
  toast("当前界面已重置，原始文件和历史任务没有删除。");
}

async function reloadTranscript() {
  if (!state.jobId) return;
  const data = await api(`/api/job/load?job_id=${encodeURIComponent(state.jobId)}`);
  updateTranscript(data.transcript.segments);
  toast("文字稿已重新载入。");
}

function resetAnalyzeControls() {
  el.clipCount.value = 20;
  el.minSeconds.value = 8;
  el.maxSeconds.value = 45;
  el.analyzeStatus.textContent = "";
  toast("分析参数已重置。");
}
async function refreshSettings() {
  try {
    const data = await api("/api/settings");
    el.keyState.textContent = data.has_key ? `已保存 ${data.masked_key}` : "未保存 Key";
    if (data.has_key && !el.apiKey.value) {
      el.apiKey.value = "";
      el.apiKey.placeholder = "已保存（隐藏）";
    }
    const volc = data.volcengine || {};
    if (el.volcengineState) {
      const hasVolcKey = Boolean(volc.has_api_key || volc.has_token);
      el.volcengineState.textContent = hasVolcKey ? "火山已配置" : "火山未配置";
      el.volcengineState.className = hasVolcKey ? "ready" : "missing";
      el.volcengineResourceId.value = volc.resource_id || "volc.seedasr.auc";
      el.volcengineAudioUrl.value = volc.audio_url || "";
      el.volcenginePollInterval.value = volc.poll_interval || 5;
      if (hasVolcKey && !el.volcengineApiKey.value) el.volcengineApiKey.placeholder = "已保存（隐藏）";
    }
    const tos = data.tos || {};
    if (el.tosState) {
      el.tosState.textContent = tos.bucket ? "TOS已配置" : "TOS未配置";
      el.tosState.className = tos.bucket ? "ready" : "missing";
      el.tosAccessKey.value = tos.access_key || "";
      el.tosEndpoint.value = tos.endpoint || "";
      el.tosRegion.value = tos.region || "";
      el.tosBucket.value = tos.bucket || "";
      el.tosPrefix.value = tos.prefix || "mp4-golden-asr";
      el.tosUrlExpires.value = tos.url_expires || 86400;
      if (tos.has_secret && !el.tosSecretKey.value) el.tosSecretKey.placeholder = "已保存（隐藏）";
    }
  } catch {
    el.keyState.textContent = "Key 状态未知";
    if (el.volcengineState) el.volcengineState.textContent = "火山状态未知";
  }
}

// Auto-save key on input blur — no need to click analyze first
el.apiKey.addEventListener("blur", async () => {
  const key = el.apiKey.value.trim();
  if (!key || !key.startsWith("sk-")) return;
  try {
    const res = await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({ api_key: key }),
    });
    await refreshSettings();
    if (res.ok) toast("Key 已保存。");
  } catch (e) {
    toast("Key 保存失败：" + e.message);
  }
});

// Explicit save button — more reliable than blur
el.saveKeyButton.addEventListener("click", async () => {
  const key = el.apiKey.value.trim();
  if (!key || !key.startsWith("sk-")) {
    toast("请先填写有效的 DeepSeek API Key（以 sk- 开头）");
    return;
  }
  try {
    const res = await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({ api_key: key }),
    });
    await refreshSettings();
    el.saveKeyButton.textContent = "已保存 ✓";
    toast("Key 已保存。");
    setTimeout(() => { el.saveKeyButton.textContent = "保存 Key"; }, 2000);
  } catch (e) {
    toast("保存失败：" + e.message);
  }
});

// Clear key button
el.clearKeyButton.addEventListener("click", async () => {
  try {
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({ action: "clear" }),
    });
    el.apiKey.value = "";
    el.apiKey.placeholder = "sk-...";
    await refreshSettings();
    toast("Key 已清除。");
  } catch (e) {
    toast("清除失败：" + e.message);
  }
});


function syncTranscribeEngineUI() {
  if (el.transcribeEngine) el.transcribeEngine.value = "volcengine_bigmodel";
  if (el.cloudTranscribeOptions) el.cloudTranscribeOptions.hidden = false;
}

function currentVolcenginePayload() {
  return {
    volcengine_api_key: el.volcengineApiKey?.value?.trim() || "",
    volcengine_resource_id: el.volcengineResourceId?.value?.trim() || "volc.seedasr.auc",
    volcengine_audio_url: el.volcengineAudioUrl?.value?.trim() || "",
    volcengine_poll_interval: Number(el.volcenginePollInterval?.value || 5),
  };
}

function currentTosPayload() {
  return {
    tos_access_key: el.tosAccessKey?.value?.trim() || "",
    tos_secret_key: el.tosSecretKey?.value?.trim() || "",
    tos_endpoint: el.tosEndpoint?.value?.trim() || "",
    tos_region: el.tosRegion?.value?.trim() || "",
    tos_bucket: el.tosBucket?.value?.trim() || "",
    tos_prefix: el.tosPrefix?.value?.trim() || "mp4-golden-asr",
    tos_url_expires: Number(el.tosUrlExpires?.value || 86400),
  };
}

async function saveCloudConfig() {
  await api("/api/settings", { method: "POST", body: JSON.stringify({ settings_type: "volcengine", ...currentVolcenginePayload() }) });
  await api("/api/settings", { method: "POST", body: JSON.stringify({ settings_type: "tos", ...currentTosPayload() }) });
}

if (el.transcribeEngine) el.transcribeEngine.addEventListener("change", syncTranscribeEngineUI);
if (el.saveAllCloudButton) {
  el.saveAllCloudButton.addEventListener("click", async () => {
    try {
      el.saveAllCloudButton.disabled = true;
      el.saveAllCloudButton.textContent = "正在保存...";
      await saveCloudConfig();
      await refreshSettings();
      toast("火山/TOS 配置已保存。");
    } catch (e) {
      toast("配置保存失败：" + e.message);
    } finally {
      el.saveAllCloudButton.disabled = false;
      el.saveAllCloudButton.textContent = "保存火山/TOS 配置";
    }
  });
}
if (el.clearVolcengineButton) {
  el.clearVolcengineButton.addEventListener("click", async () => {
    await api("/api/settings", { method: "POST", body: JSON.stringify({ action: "clear_volcengine" }) });
    if (el.volcengineApiKey) el.volcengineApiKey.value = "";
    await refreshSettings();
    toast("火山配置已清除。");
  });
}
if (el.clearTosButton) {
  el.clearTosButton.addEventListener("click", async () => {
    await api("/api/settings", { method: "POST", body: JSON.stringify({ action: "clear_tos" }) });
    [el.tosAccessKey, el.tosSecretKey, el.tosEndpoint, el.tosRegion, el.tosBucket].forEach((input) => { if (input) input.value = ""; });
    await refreshSettings();
    toast("TOS 配置已清除。");
  });
}

async function refreshLibrary() {
  const data = await api("/api/library");
  el.library.innerHTML = "";
  if (!data.items.length) {
    el.library.textContent = "还没有历史记录。";
    return;
  }
  data.items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "library-item";
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(item.title)}</strong>
        <div class="small">${escapeHtml(item.created_at || "")} · ${formatClock(item.duration || 0)} · 候选 ${item.clip_count} · 已确认 ${item.confirmed_count} · 已导出 ${item.exported_count}</div>
      </div>
      <button>载入</button>
    `;
    row.querySelector("button").addEventListener("click", () => loadJob(item.job_id));
    el.library.appendChild(row);
  });
  return data.items;
}

async function loadJob(jobId) {
  const data = await api(`/api/job/load?job_id=${encodeURIComponent(jobId)}`);
  state.jobId = jobId;
  updateMetadata(data.metadata);
  updateTranscript(data.transcript.segments);
  state.highlights = data.highlights || { clips: [] };
  el.sourceVideo.src = `/media/${jobId}/${data.metadata.browser_preview_file || data.metadata.original_file || "source.mp4"}`;
  if (data.metadata.browser_preview_file) {
    updatePreviewStatus({ stage: "preview_ready", message: "\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8\u5df2\u751f\u6210", preview_progress: 1, preview_remaining: 0, metadata: data.metadata });
  }
  el.transcribeButton.disabled = false;
  setPreviewButtonsDisabled(!needsBrowserPreview(data.metadata));
  renderClips();
  if (!state.activeClipId) showManualTrimPanel(0);
  try {
    const status = await api(`/api/job/status?job_id=${encodeURIComponent(jobId)}`);
    const job = status.job || {};
    if (["queued", "extracting", "transcribing", "paused"].includes(job.stage)) {
      el.pauseButton.disabled = false;
      el.stopButton.disabled = false;
      el.transcribeButton.disabled = true;
      showTranscriptPlaceholder(job.message || "\u6b63\u5728\u51c6\u5907\u8f6c\u5199...");
      refreshTasks().catch(() => {});
      startPolling();
    }
  } catch {}
  toast("\u4efb\u52a1\u5df2\u8f7d\u5165\u3002");
}

function startPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(refreshJobStatus, 1200);
}

async function refreshFullTranscriptIfBehind(job = {}) {
  if (!state.jobId) return;
  const serverCount = Number(job.segment_count || 0);
  const localCount = state.transcript.segments.length || 0;
  if (!serverCount || serverCount <= localCount) return;
  const loaded = await api(`/api/job/load?job_id=${encodeURIComponent(state.jobId)}`);
  updateTranscript(loaded.transcript.segments);
}
async function refreshJobStatus() {
  if (!state.jobId) return;
  try {
    const data = await api(`/api/job/status?job_id=${encodeURIComponent(state.jobId)}`);
    const job = data.job || {};
    if (job.message) {
      el.jobMessage.textContent = job.message;
      setStatus(job.message);
    }
    updatePreviewStatus(job);
    updateTranscribeStats(job);
    if (["queued", "extracting", "transcribing", "paused"].includes(job.stage)) {
      showTranscriptPlaceholder(job.message || "\u6b63\u5728\u51c6\u5907\u8f6c\u5199...");
      refreshTasks().catch(() => {});
    }
    if (job.stage === "error") {
      showTranscriptPlaceholder(`\u8f6c\u5199\u51fa\u9519\uff1a${job.message || job.error || "\u672a\u77e5\u9519\u8bef"}`);
    }
    if (typeof job.progress === "number") {
      el.progressBar.style.width = `${Math.round(job.progress * 100)}%`;
    }
    if (job.browser_preview_url || job.stage === "preview_ready") {
      applyBrowserPreviewIfReady(job);
      const transcribeRunning = el.transcribeButton.disabled && !el.stopButton.disabled;
      if (!transcribeRunning && state.pollTimer) clearInterval(state.pollTimer);
    }
    if (job.stage === "preview_error") {
      setPreviewButtonsDisabled(false);
      if (state.pollTimer) clearInterval(state.pollTimer);
    }
    if (job.transcript_tail) {
      mergeTranscriptSegments(job.transcript_tail);
    } else if (job.latest_segment) {
      mergeTranscriptSegments([job.latest_segment]);
    }
    await refreshFullTranscriptIfBehind(job);
    if (["transcribed", "stopped", "error"].includes(job.stage)) {
      const loaded = await api(`/api/job/load?job_id=${encodeURIComponent(state.jobId)}`);
      updateTranscript(loaded.transcript.segments);
      if (job.stage !== "error") el.analyzeButton.disabled = loaded.transcript.segments.length === 0;
      el.pauseButton.disabled = true;
      el.stopButton.disabled = true;
      clearInterval(state.pollTimer);
    }
  } catch (err) {
    el.jobMessage.textContent = err.message;
  }
}

el.fileInput.addEventListener("change", () => {
  const file = el.fileInput.files[0];
  if (!file) return;
  state.localFile = file;
  if (state.localUrl) URL.revokeObjectURL(state.localUrl);
  state.localUrl = URL.createObjectURL(file);
  el.sourceVideo.src = state.localUrl;
  el.uploadButton.disabled = false;
  el.metadata.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB · 已在浏览器载入，可先预览。`;
  showManualTrimPanel(0);
  toast("视频已载入，可先预览。要生成剪切预览，需要先上传到本地服务。");
});

el.uploadButton.addEventListener("click", async () => {
  if (!state.localFile) return;
  const form = new FormData();
  form.append("file", state.localFile);
  toast("正在上传到本地服务...");
  const data = await api("/api/video/upload", { method: "POST", body: form });
  state.jobId = data.job_id;
  updateMetadata(data.metadata);
  el.sourceVideo.src = data.preview_url;
  el.transcribeButton.disabled = false;
  const canMakePreview = needsBrowserPreview(data.metadata);
  setPreviewButtonsDisabled(data.browser_preview_queued || !canMakePreview);
  el.uploadButton.disabled = true;
  showManualTrimPanel(0);
  await refreshLibrary();
  if (data.browser_preview_queued) {
    updatePreviewStatus({ stage: "previewing", message: "\u6b63\u5728\u751f\u6210\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8 MP4", preview_progress: 0, preview_elapsed: 0, preview_remaining: null });
    toast("\u6e90\u89c6\u9891\u5df2\u4fdd\u5b58\uff0c\u6b63\u5728\u751f\u6210\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8 MP4\u3002\u4e5f\u53ef\u4ee5\u5148\u5f00\u59cb\u8f6c\u5199\u3002");
    startPolling();
  } else {
    toast("\u6e90\u89c6\u9891\u5df2\u4fdd\u5b58\uff0c\u53ef\u5f00\u59cb\u8f6c\u5199\u3002\u9700\u8981\u770b\u753b\u9762\u65f6\u53ef\u70b9\u751f\u6210\u517c\u5bb9\u9884\u89c8\u3002");
  }
});

el.transcribeButton.addEventListener("click", async () => {
  try {
    toast("\u6b63\u5728\u542f\u52a8\u8f6c\u5199...");
    const payload = { job_id: state.jobId, transcribe_engine: "volcengine_bigmodel" };
    await saveCloudConfig();
    Object.assign(payload, currentVolcenginePayload(), currentTosPayload());
    await refreshSettings();
    await api("/api/transcribe/start", { method: "POST", body: JSON.stringify(payload) });
    await refreshTasks();
    el.pauseButton.disabled = false;
    el.stopButton.disabled = false;
    el.transcribeButton.disabled = true;
    el.progressBar.style.width = "3%";
    updateTranscribeStats({ stage: "extracting", transcribe_elapsed: 0, segment_count: state.transcript.segments.length });
    showTranscriptPlaceholder("\u6b63\u5728\u63d0\u53d6\u97f3\u9891\u5e76\u542f\u52a8\u8f6c\u5199\u3002\u65b0\u8bc6\u522b\u51fa\u7684\u6587\u5b57\u4f1a\u6301\u7eed\u51fa\u73b0\u5728\u8fd9\u91cc\u3002");
    startPolling();
    toast("\u8f6c\u5199\u5df2\u5f00\u59cb\uff0c\u4e0b\u65b9\u4f1a\u5b9e\u65f6\u8ffd\u52a0\u6587\u5b57\u3002");
  } catch (err) {
    showTranscriptPlaceholder(`\u8f6c\u5199\u542f\u52a8\u5931\u8d25\uff1a${err.message}`);
    toast(`\u8f6c\u5199\u542f\u52a8\u5931\u8d25\uff1a${err.message}`);
    el.transcribeButton.disabled = false;
  }
});

el.pauseButton.addEventListener("click", async () => {
  const isPause = el.pauseButton.textContent === "暂停";
  await api("/api/transcribe/control", { method: "POST", body: JSON.stringify({ job_id: state.jobId, action: isPause ? "pause" : "resume" }) });
  el.pauseButton.textContent = isPause ? "继续" : "暂停";
});

el.stopButton.addEventListener("click", async () => {
  await api("/api/transcribe/control", { method: "POST", body: JSON.stringify({ job_id: state.jobId, action: "stop" }) });
  toast("收到结束请求，会保存已产生文字稿。");
});

async function pollAnalyzeTask(taskId) {
  while (true) {
    const data = await api(`/api/clips/render-status?task_id=${encodeURIComponent(taskId)}`);
    const task = data.task;
    await refreshTasks();
    const percent = task.percent ?? Math.round((task.progress || 0) * 100);
    el.analyzeStatus.textContent = `${task.message || "DeepSeek \u5206\u6790\u4e2d"} \u00b7 \u8fdb\u5ea6 ${percent}% \u00b7 \u5df2\u7528 ${formatShortTime(task.elapsed || 0)}`;
    if (task.status === "done") {
      state.highlights = task.highlights || { clips: [] };
      renderClips();
      await refreshSettings();
      const count = (state.highlights.clips || []).length;
      el.analyzeStatus.textContent = `\u5206\u6790\u5b8c\u6210\uff0c\u627e\u5230 ${count} \u4e2a\u5019\u9009\u7247\u6bb5`;
      toast(`\u5206\u6790\u5b8c\u6210\uff0c\u627e\u5230 ${count} \u4e2a\u5019\u9009\u7247\u6bb5\u3002`);
      return true;
    }
    if (["error", "cancelled"].includes(task.status)) {
      el.analyzeStatus.textContent = `\u5206\u6790\u5931\u8d25\uff1a${task.message || "\u672a\u77e5\u9519\u8bef"}`;
      toast(`\u5206\u6790\u5931\u8d25\uff1a${task.message || "\u672a\u77e5\u9519\u8bef"}`);
      return false;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

el.analyzeButton.addEventListener("click", async () => {
  el.analyzeButton.disabled = true;
  el.analyzeStatus.textContent = "\u6b63\u5728\u63d0\u4ea4 DeepSeek \u5206\u6790\u4efb\u52a1...";
  try {
    const data = await api("/api/highlights/analyze", {
      method: "POST",
      body: JSON.stringify({
        job_id: state.jobId,
        api_key: el.apiKey.value,
        save_key: el.saveKey.checked,
        target_clip_count: Number(el.clipCount.value),
        min_seconds: Number(el.minSeconds.value),
        max_seconds: Number(el.maxSeconds.value),
      }),
    });
    await refreshTasks();
    el.analyzeStatus.textContent = "\u5206\u6790\u4efb\u52a1\u5df2\u52a0\u5165\u961f\u5217\uff0c\u8fdb\u5ea6\u4f1a\u5728\u8fd9\u91cc\u548c\u4efb\u52a1\u4e2d\u5fc3\u540c\u6b65\u663e\u793a\u3002";
    await pollAnalyzeTask(data.task.task_id);
  } catch (err) {
    el.analyzeStatus.textContent = `\u5206\u6790\u5931\u8d25\uff1a${err.message}`;
    toast(`\u5206\u6790\u5931\u8d25\uff1a${err.message}`);
  } finally {
    el.analyzeButton.disabled = false;
  }
});

async function updateClipTime(clipId, start, end) {
  if (!(end > start)) {
    toast("结束时间必须大于开始时间。");
    return;
  }
  const data = await api("/api/clips/update-time", { method: "POST", body: JSON.stringify({ job_id: state.jobId, clip_id: clipId, start, end }) });
  if (!replaceClipById(clipId, data.clip, "update-time")) {
    toast("时间已保存到后端，但前端没有找到对应候选，请刷新任务。");
    return;
  }
  renderClips();
  syncTrimPanelFromClip();
  toast("时间已保存，需要重新生成预览。");
}

function setClipRenderProgress(clipId, percent, label, extra = {}) {
  state.renderProgress[clipId] = {
    percent: Math.max(0, Math.min(100, Math.round(percent))),
    label,
    ...extra,
  };
  renderClips();
}

function clearClipRenderProgress(clipId) {
  delete state.renderProgress[clipId];
  renderClips();
}

function describeRenderTask(task, title, batchMeta = null) {
  const prefix = batchMeta ? `\u6279\u91cf ${batchMeta.done}/${batchMeta.total} \u00b7 ` : "";
  const elapsed = formatShortTime(task.elapsed || 0);
  const remaining = task.remaining == null ? "\u8ba1\u7b97\u4e2d" : formatShortTime(task.remaining || 0);
  const encoder = task.encoder ? ` \u00b7 ${escapeHtml(task.encoder)}` : "";
  if (task.status === "done") return `${prefix}\u9884\u89c8\u5b8c\u6210\uff1a${title}`;
  if (task.status === "error") return `${prefix}\u9884\u89c8\u5931\u8d25\uff1a${task.message || "\u672a\u77e5\u9519\u8bef"}`;
  if (task.status === "cancelled") return `${prefix}\u5df2\u53d6\u6d88\uff1a${title}`;
  return `${prefix}${task.message || "\u6b63\u5728\u751f\u6210\u517c\u5bb9\u9884\u89c8"} \u00b7 \u5df2\u7528 ${elapsed} \u00b7 \u5269\u4f59 ${remaining}${encoder}`;
}

async function pollRenderTask(taskId, clipId, title, batchMeta = null) {
  while (true) {
    const data = await api(`/api/clips/render-status?task_id=${encodeURIComponent(taskId)}`);
    const task = data.task;
    refreshTasks().catch(() => {});
    const percent = task.percent ?? Math.round((task.progress || 0) * 100);
    setClipRenderProgress(clipId, percent, describeRenderTask(task, title, batchMeta), {
      taskId,
      status: task.status,
      elapsed: task.elapsed,
      remaining: task.remaining,
    });
    el.analyzeStatus.textContent = describeRenderTask(task, title, batchMeta);
    if (task.status === "done") {
      if (task.clip) {
        const index = state.highlights.clips.findIndex((c) => c.id === clipId);
        if (index >= 0) state.highlights.clips[index] = task.clip;
      }
      setClipRenderProgress(clipId, 100, "\u9884\u89c8\u751f\u6210\u5b8c\u6210", { status: "done" });
      setTimeout(() => clearClipRenderProgress(clipId), 900);
      return true;
    }
    if (["error", "cancelled"].includes(task.status)) {
      setClipRenderProgress(clipId, 100, task.message || "\u9884\u89c8\u751f\u6210\u5931\u8d25", { status: task.status });
      return false;
    }
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

async function cancelRender(taskId) {
  if (!taskId) return;
  await api("/api/clips/render-cancel", { method: "POST", body: JSON.stringify({ task_id: taskId }) });
  el.analyzeStatus.textContent = "\u6b63\u5728\u53d6\u6d88\u9884\u89c8\u751f\u6210\u4efb\u52a1...";
}

async function renderPreview(clipId, batchMeta = null) {
  const clipIndex = state.highlights.clips.findIndex((c) => c.id === clipId);
  const clip = state.highlights.clips[clipIndex];
  const title = clip?.title || clipId;
  setClipRenderProgress(clipId, 1, "\u6b63\u5728\u63d0\u4ea4\u751f\u6210\u4efb\u52a1");
  try {
    const data = await api("/api/clips/render-preview", { method: "POST", body: JSON.stringify({ job_id: state.jobId, clip_id: clipId }) });
    const task = data.task;
    if (task?.task_id) state.trackedTaskIds.add(task.task_id);
    await refreshTasks();
    setClipRenderProgress(clipId, task.percent || 1, describeRenderTask(task, title, batchMeta), { taskId: task.task_id, status: task.status });
    return await pollRenderTask(task.task_id, clipId, title, batchMeta);
  } catch (err) {
    setClipRenderProgress(clipId, 100, `\u9884\u89c8\u5931\u8d25\uff1a${err.message}`, { status: "error" });
    el.analyzeStatus.textContent = `\u9884\u89c8\u5931\u8d25\uff1a${err.message}`;
    toast(err.message);
    return false;
  }
}
el.renderAllButton.addEventListener("click", async () => {
  el.renderAllButton.disabled = true;
  const pending = state.highlights.clips.filter(c => !c.preview_file);
  if (!pending.length) {
    el.analyzeStatus.textContent = "\u6240\u6709\u7247\u6bb5\u90fd\u5df2\u6709\u9884\u89c8\u3002";
    el.renderAllButton.disabled = false;
    return;
  }
  const total = pending.length;
  const concurrency = Math.min(2, total);
  let cursor = 0;
  let done = 0;
  let okCount = 0;
  const startTime = Date.now();
  async function worker() {
    while (cursor < total) {
      const clip = pending[cursor++];
      const ok = await renderPreview(clip.id, { get done() { return done; }, total });
      done += 1;
      if (ok) okCount += 1;
      const percent = Math.round((done / total) * 100);
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      el.analyzeStatus.textContent = `\u6279\u91cf\u9884\u89c8 ${percent}% \u00b7 \u5df2\u5b8c\u6210 ${done}/${total}\uff0c\u6210\u529f ${okCount}\uff0c\u5df2\u7528 ${formatShortTime(elapsed)}`;
    }
  }
  await Promise.all(Array.from({ length: concurrency }, () => worker()));
  const totalSec = Math.floor((Date.now() - startTime) / 1000);
  el.analyzeStatus.textContent = `\u9884\u89c8\u5b8c\u6210\uff1a${okCount}/${total}\uff0c\u8017\u65f6 ${formatShortTime(totalSec)}`;
  el.renderAllButton.disabled = false;
  toast(`\u9884\u89c8\u5b8c\u6210\uff1a${okCount}/${total} \u4e2a\u7247\u6bb5\u3002`);
});
async function confirmClip(clipId, confirmed) {
  const data = await api("/api/clips/confirm", { method: "POST", body: JSON.stringify({ job_id: state.jobId, clip_id: clipId, confirmed }) });
  const index = state.highlights.clips.findIndex((c) => c.id === clipId);
  state.highlights.clips[index] = data.clip;
  renderClips();
}

async function pollExportTask(taskId, targetLabel) {
  while (true) {
    const data = await api(`/api/clips/render-status?task_id=${encodeURIComponent(taskId)}`);
    const task = data.task;
    refreshTasks().catch(() => {});
    const percent = task.percent ?? Math.round((task.progress || 0) * 100);
    const elapsed = formatShortTime(task.elapsed || 0);
    const exported = task.exported || [];
    const errors = task.errors || [];
    el.analyzeStatus.textContent = `\u5bfc\u51fa ${percent}% \u00b7 ${task.message || "\u6b63\u5728\u5bfc\u51fa\u539f\u753b\u8d28\u7247\u6bb5"} \u00b7 \u6210\u529f ${exported.length}\uff0c\u5931\u8d25 ${errors.length} \u00b7 \u5df2\u7528 ${elapsed}`;
    if (task.status === "done") {
      exported.forEach((clip) => {
        const index = state.highlights.clips.findIndex((c) => c.id === clip.id);
        if (index >= 0) state.highlights.clips[index] = clip;
      });
      renderClips();
      await refreshLibrary();
      await refreshStorage();
      const paths = exported.map((clip) => clip.export_path || clip.export_file).filter(Boolean);
      const firstPath = paths[0] ? ` \u7b2c\u4e00\u6761\uff1a${paths[0]}` : "";
      toast(`\u5df2\u5bfc\u51fa ${exported.length} \u6761\uff0c\u5931\u8d25 ${errors.length} \u6761\u3002\u539f\u753b\u8d28\u65e0\u91cd\u7f16\u7801\u3002${firstPath}`);
      return true;
    }
    if (["error", "cancelled"].includes(task.status)) {
      toast(task.message || "\u5bfc\u51fa\u4efb\u52a1\u5931\u8d25");
      return false;
    }
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

async function pickExportDirectory(initialDir = "") {
  const data = await api("/api/dialog/export-dir", { method: "POST", body: JSON.stringify({ initial_dir: initialDir || "" }) });
  if (!data.selected || !data.path) return "";
  return data.path;
}

async function exportClips(clipIds = null, options = {}) {
  const exportDir = options.exportDir ?? (el.exportDirectory?.value?.trim() || "");
  const targetLabel = exportDir || "任务文件夹 clips/exports";
  toast(`已提交原画质导出任务：${targetLabel}`);
  el.exportButton.disabled = true;
  try {
    const data = await api("/api/clips/export", { method: "POST", body: JSON.stringify({ job_id: state.jobId, clip_ids: clipIds || [], export_dir: exportDir }) });
    const task = data.task;
    await refreshTasks();
    el.analyzeStatus.textContent = `导出任务已加入队列 · ${targetLabel}`;
    await pollExportTask(task.task_id, targetLabel);
  } finally {
    el.exportButton.disabled = !state.highlights.clips.some((c) => c.confirmed);
  }
}

async function exportSingleClip(clipId) {
  const clip = findClip(clipId);
  const initial = el.exportDirectory?.value?.trim() || "";
  toast(`请选择「${clip?.title || clipId}」的导出文件夹...`);
  const exportDir = await pickExportDirectory(initial);
  if (!exportDir) {
    toast("已取消导出单条片段。");
    return;
  }
  if (el.exportDirectory) el.exportDirectory.value = exportDir;
  await exportClips([clipId], { exportDir });
}
el.exportButton.addEventListener("click", () => exportClips());
if (el.copyTranscriptButton) {
  el.copyTranscriptButton.addEventListener("click", async () => {
    const text = transcriptText();
    if (!text) {
      toast("还没有可复制的文字稿。");
      return;
    }
    await navigator.clipboard.writeText(text);
    toast(`已复制完整文字稿，共 ${state.transcript.segments.length} 段。`);
  });
}

if (el.chooseExportDirectoryButton) {
  el.chooseExportDirectoryButton.addEventListener("click", async () => {
    try {
      const path = await pickExportDirectory(el.exportDirectory.value);
      if (path) {
        el.exportDirectory.value = path;
        toast(`已选择导出目录：${path}`);
      } else {
        toast("已取消选择导出目录。");
      }
    } catch (err) {
      toast(err.message);
    }
  });
}

el.sourceVideo.addEventListener("timeupdate", () => {
  if (el.sourceTimeText) el.sourceTimeText.textContent = `\u5f53\u524d ${formatClock(el.sourceVideo.currentTime || 0)}`;
});
el.sourceVideo.addEventListener("loadedmetadata", () => syncTrimSliderBounds());

if (el.setStartFromCurrent) {
  el.setStartFromCurrent.addEventListener("click", () => setTrimValue("start", el.sourceVideo.currentTime || 0, true));
  el.setEndFromCurrent.addEventListener("click", () => setTrimValue("end", el.sourceVideo.currentTime || 0, true));
  el.trimStartRange?.addEventListener("input", () => {
    setFineFocus("start", false);
    setTrimValue("start", el.trimStartRange.value, true);
    state.trimFineBase = parseClock(el.trimStartInput.value);
    if (el.trimFineRange) el.trimFineRange.value = "0";
  });
  el.trimEndRange?.addEventListener("input", () => {
    setFineFocus("end", false);
    setTrimValue("end", el.trimEndRange.value, true);
    state.trimFineBase = parseClock(el.trimEndInput.value);
    if (el.trimFineRange) el.trimFineRange.value = "0";
  });
  el.trimStartInput?.addEventListener("change", () => applyManualTrimInput("start"));
  el.trimStartInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      el.trimStartInput.blur();
    }
  });
  el.trimEndInput?.addEventListener("change", () => applyManualTrimInput("end"));
  el.trimEndInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      el.trimEndInput.blur();
    }
  });
  el.transcriptSearchButton?.addEventListener("click", searchTranscript);
  el.transcriptSearchInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      searchTranscript();
    }
  });
  el.transcriptSearchResults?.addEventListener("click", (e) => {
    const row = e.target.closest(".search-result");
    if (row) jumpToSearchResult(row);
  });
  el.focusTrimStart?.addEventListener("click", () => setFineFocus("start"));
  el.focusTrimEnd?.addEventListener("click", () => setFineFocus("end"));
  el.trimFineRange?.addEventListener("input", () => setTrimValue(state.trimFocus || "start", state.trimFineBase + Number(el.trimFineRange.value || 0), true));
  el.trimSensitivity?.addEventListener("change", () => {
    syncTrimSliderBounds();
    setFineFocus(state.trimFocus || "start", false);
    toast("\u5df2\u5207\u6362\u62d6\u52a8\u7075\u654f\u5ea6");
  });
  el.saveTrimButton.addEventListener("click", async () => {
    if (!state.jobId) {
      toast("请先上传到本地服务，再保存剪切时间。");
      return;
    }
    try {
      await saveActiveTrim();
    } catch (err) {
      el.analyzeStatus.textContent = `保存剪切失败：${err.message}`;
      toast(`保存剪切失败：${err.message}`);
    }
  });
  el.renderActivePreviewButton.addEventListener("click", async () => {
    if (!state.jobId) {
      toast("请先上传到本地服务，再生成剪切预览。");
      return;
    }
    const lockedClipId = state.activeClipId;
    el.renderActivePreviewButton.disabled = true;
    el.analyzeStatus.textContent = lockedClipId ? "正在保存微调时间..." : "正在创建手动剪切候选...";
    try {
      const clip = await saveActiveTrim();
      if (!clip) return;
      if (lockedClipId && clip.id !== lockedClipId) {
        toast("当前微调片段发生变化，已停止生成，避免覆盖其他候选。");
        return;
      }
      await renderPreview(clip.id);
    } catch (err) {
      el.analyzeStatus.textContent = `剪切预览失败：${err.message}`;
      toast(`剪切预览失败：${err.message}`);
    } finally {
      el.renderActivePreviewButton.disabled = false;
      syncTrimPanelFromClip();
    }
  });
}
el.refreshLibraryButton.addEventListener("click", refreshLibrary);
el.previewButton.addEventListener("click", requestBrowserPreview);
el.previewTopButton?.addEventListener("click", requestBrowserPreview);
if (el.refreshStorageButton) el.refreshStorageButton.addEventListener("click", refreshStorage);
if (el.refreshTasksButton) el.refreshTasksButton.addEventListener("click", refreshTasks);
if (el.refreshHealthButton) el.refreshHealthButton.addEventListener("click", refreshHealth);
if (el.clearFinishedTasksButton) el.clearFinishedTasksButton.addEventListener("click", clearFinishedTasks);
if (el.cleanBrowserPreviewButton) el.cleanBrowserPreviewButton.addEventListener("click", () => cleanupStorage(["browser_preview"]));
if (el.cleanClipPreviewButton) el.cleanClipPreviewButton.addEventListener("click", () => cleanupStorage(["clip_previews"]));
if (el.cleanAudioCacheButton) el.cleanAudioCacheButton.addEventListener("click", () => cleanupStorage(["audio"]));
if (el.resetVideoButton) el.resetVideoButton.addEventListener("click", resetCurrentVideoView);
if (el.resetTranscriptButton) el.resetTranscriptButton.addEventListener("click", reloadTranscript);
if (el.clearTranscriptViewButton) el.clearTranscriptViewButton.addEventListener("click", () => { updateTranscript([]); toast("文字稿显示已清空，可点重新载入恢复。"); });
if (el.clearClipsButton) el.clearClipsButton.addEventListener("click", clearAllClips);
if (el.resetAnalyzeButton) el.resetAnalyzeButton.addEventListener("click", resetAnalyzeControls);
if (el.clearExportDirectoryButton) el.clearExportDirectoryButton.addEventListener("click", () => { el.exportDirectory.value = ""; toast("导出目录已清空，将使用任务默认 exports 文件夹。"); });

el.sourceVideo.addEventListener("error", async () => {
  if (!state.jobId) return;
  updatePreviewStatus({ stage: "previewing", message: "\u5f53\u524d\u89c6\u9891\u7f16\u7801\u6d4f\u89c8\u5668\u65e0\u6cd5\u76f4\u63a5\u9884\u89c8\uff0c\u6b63\u5728\u751f\u6210\u517c\u5bb9\u9884\u89c8 MP4", preview_progress: 0, preview_elapsed: 0, preview_remaining: null });
  toast("\u5f53\u524d\u89c6\u9891\u7f16\u7801\u6d4f\u89c8\u5668\u65e0\u6cd5\u76f4\u63a5\u9884\u89c8\uff0c\u6b63\u5728\u751f\u6210\u517c\u5bb9\u9884\u89c8 MP4...");
  try {
    await api("/api/video/browser-preview", { method: "POST", body: JSON.stringify({ job_id: state.jobId }) });
    startPolling();
  } catch (err) {
    toast(err.message);
  }
});

function startSafetyPolling() {
  const safetyTimer = setInterval(async () => {
    if (!state.jobId) return;
    try {
      const status = await api(`/api/job/status?job_id=${encodeURIComponent(state.jobId)}`);
      const job = status.job || {};
      // Only poll during active stages; stop for completed/stable ones
      const activeStages = ["queued", "extracting", "transcribing", "paused"];
      if (!activeStages.includes(job.stage)) return;
      if (job.message) {
        el.jobMessage.textContent = job.message;
        setStatus(job.message);
      }
      updateTranscribeStats(job);
      if (typeof job.progress === "number") {
        el.progressBar.style.width = `${Math.round(job.progress * 100)}%`;
      }
      if (job.transcript_tail) {
        mergeTranscriptSegments(job.transcript_tail);
      } else if (job.latest_segment) {
        mergeTranscriptSegments([job.latest_segment]);
      }
      await refreshFullTranscriptIfBehind(job);
    } catch (err) { /* Keep UI stable */ }
  }, 2000);
}

async function boot() {
  startSafetyPolling();
  await refreshTasks();
  state.taskTimer = setInterval(() => refreshTasks().catch(() => {}), 2500);
  await refreshSettings();
  syncTranscribeEngineUI();
  await refreshStorage();
  const items = await refreshLibrary();
  if (!state.jobId && items && items.length) {
    await loadJob(items[0].job_id);
    toast("\u5df2\u81ea\u52a8\u8f7d\u5165\u6700\u8fd1\u4efb\u52a1\u3002\u5237\u65b0\u9875\u9762\u4e0d\u4f1a\u5220\u9664\u517c\u5bb9\u9884\u89c8\u6216\u8f6c\u5199\u7ed3\u679c\u3002");
  }
}

boot();
