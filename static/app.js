const state = {
  localFile: null,
  localUrl: null,
  jobId: null,
  metadata: null,
  transcript: { segments: [], groups: [] },
  highlights: { clips: [] },
  pollTimer: null,
  taskTimer: null,
  renderProgress: {},
  activeClipId: null,
  activeJobId: null,
  trackedTaskIds: new Set(),
  syncedTaskIds: new Set(),
  analyzeTaskId: null,
  openJobIds: [],
  draftTabs: [],
  draftMedia: {},
  activeDraftId: null,
  draftSequence: 0,
  jobMeta: {},
  libraryItems: [],
  taskFilter: "active",
  currentView: "workbench",
  trends: { searchId: null, candidates: [], warnings: [], importTasks: {}, openedJobIds: new Set() },
  modalClipId: null,
  modalTrim: null,
  timelineFrames: [],
  timelineDragging: null,
  trimSavePromise: null,
  uploadPromise: null,
  transcribeControlPending: false,
  providerKind: "llm",
  providers: { llm: [], volcengine: [] },
  providersPackaged: false,
  providerSettingsInitialized: true,
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
  appViews: {
    trends: $("trendsView"),
    workbench: $("workbenchView"),
    providers: $("providersView"),
    "provider-list": $("providerListView"),
    tasks: $("tasksView"),
    storage: $("storageView"),
  },
  navItems: Array.from(document.querySelectorAll("[data-view]")),
  viewTitle: $("viewTitle"),
  viewSubtitle: $("viewSubtitle"),
  workbenchTabs: $("workbenchTabs"),
  activeTaskCount: $("activeTaskCount"),
  trendKeywords: $("trendKeywords"),
  trendSource: $("trendSource"),
  trendDateRange: $("trendDateRange"),
  trendLimit: $("trendLimit"),
  trendStartDate: $("trendStartDate"),
  trendEndDate: $("trendEndDate"),
  trendCustomDates: $("trendCustomDates"),
  trendSearchButton: $("trendSearchButton"),
  trendOpenChromeButton: $("trendOpenChromeButton"),
  trendSearchStatus: $("trendSearchStatus"),
  trendResultSummary: $("trendResultSummary"),
  trendResults: $("trendResults"),
  trendProviderBadge: $("trendProviderBadge"),
  taskFilterActive: $("taskFilterActive"),
  taskFilterCompleted: $("taskFilterCompleted"),
  fileInput: $("fileInput"),
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
  pauseAnalyzeButton: $("pauseAnalyzeButton"),
  stopAnalyzeButton: $("stopAnalyzeButton"),
  renderAllButton: $("renderAllButton"),
  exportButton: $("exportButton"),
  refreshLibraryButton: $("refreshLibraryButton"),
  clearLibraryButton: $("clearLibraryButton"),
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
  workbenchLlmStatus: $("workbenchLlmStatus"),
  workbenchVolcStatus: $("workbenchVolcStatus"),
  manageLlmButton: $("manageLlmButton"),
  manageVolcengineButton: $("manageVolcengineButton"),
  providerEntries: Array.from(document.querySelectorAll("[data-provider-kind]")),
  backToProvidersButton: $("backToProvidersButton"),
  providerList: $("providerList"),
  providerListTitle: $("providerListTitle"),
  providerListSummary: $("providerListSummary"),
  addProviderButton: $("addProviderButton"),
  providerForm: $("providerForm"),
  providerFormTitle: $("providerFormTitle"),
  cancelProviderButton: $("cancelProviderButton"),
  providerId: $("providerId"),
  providerKind: $("providerKind"),
  providerName: $("providerName"),
  providerApiKey: $("providerApiKey"),
  volcProviderName: $("volcProviderName"),
  volcProviderApiKey: $("volcProviderApiKey"),
  llmProviderFields: $("llmProviderFields"),
  volcProviderFields: $("volcProviderFields"),
  providerBaseUrl: $("providerBaseUrl"),
  providerProtocol: $("providerProtocol"),
  providerModel: $("providerModel"),
  providerResourceId: $("providerResourceId"),
  providerTosAccessKey: $("providerTosAccessKey"),
  providerTosSecretKey: $("providerTosSecretKey"),
  providerTosBucket: $("providerTosBucket"),
  providerTosEndpoint: $("providerTosEndpoint"),
  providerTosRegion: $("providerTosRegion"),
  providerAudioUrl: $("providerAudioUrl"),
  providerPollInterval: $("providerPollInterval"),
  providerTosPrefix: $("providerTosPrefix"),
  providerTosUrlExpires: $("providerTosUrlExpires"),
  providerEnabled: $("providerEnabled"),
  clipCount: $("clipCount"),
  minSeconds: $("minSeconds"),
  maxSeconds: $("maxSeconds"),
  clips: $("clips"),
  clipSummary: $("clipSummary"),
  library: $("library"),
  analyzeStatus: $("analyzeStatus"),
  exportDirectory: $("exportDirectory"),
  copyTranscriptButton: $("copyTranscriptButton"),
  openTranscriptFolderButton: $("openTranscriptFolderButton"),
  saveTranscriptAsButton: $("saveTranscriptAsButton"),
  transcriptFileLocation: $("transcriptFileLocation"),
  transcriptModeText: $("transcriptModeText"),
  chooseExportDirectoryButton: $("chooseExportDirectoryButton"),
  sourceTrimPanel: $("sourceTrimPanel"),
  activeClipTitle: $("activeClipTitle"),
  sourceTimeText: $("sourceTimeText"),
  trimStartInput: $("trimStartInput"),
  trimEndInput: $("trimEndInput"),
  trimDurationInput: $("trimDurationInput"),
  trimTimeline: $("trimTimeline"),
  trimFrameStrip: $("trimFrameStrip"),
  trimSelection: $("trimSelection"),
  trimStartHandle: $("trimStartHandle"),
  trimEndHandle: $("trimEndHandle"),
  trimPlayhead: $("trimPlayhead"),
  setStartFromCurrent: $("setStartFromCurrent"),
  setEndFromCurrent: $("setEndFromCurrent"),
  saveTrimButton: $("saveTrimButton"),
  renderActivePreviewButton: $("renderActivePreviewButton"),
  taskSummary: $("taskSummary"),
  taskList: $("taskList"),
  refreshTasksButton: $("refreshTasksButton"),
  clearFinishedTasksButton: $("clearFinishedTasksButton"),
  newTaskButton: $("newTaskButton"),
  resetTranscriptButton: $("resetTranscriptButton"),
  clearTranscriptViewButton: $("clearTranscriptViewButton"),
  resetAnalyzeButton: $("resetAnalyzeButton"),
  clearClipsButton: $("clearClipsButton"),
  clearExportDirectoryButton: $("clearExportDirectoryButton"),
  refreshStorageButton: $("refreshStorageButton"),
  cleanBrowserPreviewButton: $("cleanBrowserPreviewButton"),
  cleanClipPreviewButton: $("cleanClipPreviewButton"),
  cleanAudioCacheButton: $("cleanAudioCacheButton"),
  cleanWorkspaceCacheButton: $("cleanWorkspaceCacheButton"),
  clipPreviewModal: $("clipPreviewModal"),
  closeClipPreviewButton: $("closeClipPreviewButton"),
  clipPreviewIndex: $("clipPreviewIndex"),
  clipPreviewModalTitle: $("clipPreviewModalTitle"),
  modalClipVideo: $("modalClipVideo"),
  modalTrimTimeline: $("modalTrimTimeline"),
  modalTrimFrameStrip: $("modalTrimFrameStrip"),
  modalTrimSelection: $("modalTrimSelection"),
  modalTrimStartHandle: $("modalTrimStartHandle"),
  modalTrimEndHandle: $("modalTrimEndHandle"),
  modalTrimPlayhead: $("modalTrimPlayhead"),
  modalTrimStartInput: $("modalTrimStartInput"),
  modalTrimEndInput: $("modalTrimEndInput"),
  modalTrimDurationInput: $("modalTrimDurationInput"),
  modalSetStartButton: $("modalSetStartButton"),
  modalSetEndButton: $("modalSetEndButton"),
  modalSaveTrimButton: $("modalSaveTrimButton"),
  clipPreviewDetails: $("clipPreviewDetails"),
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
      <div class="small">总 ${formatBytes(item.total_size)} · 重要输出 ${formatBytes(item.output_size)} · 运行数据 ${formatBytes(item.runtime_size)} · 原片 ${formatBytes(item.source_size)} · 兼容预览 ${formatBytes(item.browser_preview_size)} · 候选预览 ${formatBytes(item.clip_preview_size)} · 音频 ${formatBytes(item.audio_size)}</div>
    `;
    el.storageList.appendChild(row);
  });
}

async function cleanupStorage(categories) {
  if (!categories.length) return;
  const names = { browser_preview: "兼容预览", clip_previews: "候选预览", audio: "音频缓存", workspace_cache: "原视频与运行缓存" };
  const label = categories.map((c) => names[c] || c).join("、");
  const warning = categories.includes("workspace_cache")
    ? "这会删除原视频、音频和浏览器预览，只保留转写稿、金句分析和已经导出的视频。之后不能再对这些任务预览或重新裁剪。"
    : "不会删除转写稿、金句分析和已经导出的视频。";
  if (!confirm(`确定清理全部任务的${label}吗？${warning}`)) return;
  await api("/api/storage/cleanup", { method: "POST", body: JSON.stringify({ categories }) });
  await refreshStorage();
  await refreshLibrary();
  if (state.jobId) await loadJob(state.jobId);
  toast(`${label}已清理。`);
}

function taskTypeText(type) {
  return { draft: "\u65b0\u5efa\u4efb\u52a1", workspace: "\u89c6\u9891\u4efb\u52a1", preview: "\u5019\u9009\u9884\u89c8", export: "\u539f\u753b\u8d28\u5bfc\u51fa", transcribe: "\u8bed\u97f3\u8f6c\u5199", analyze: "DeepSeek \u5206\u6790" }[type] || "\u540e\u53f0\u4efb\u52a1";
}

function taskStatusText(status) {
  return { draft: "\u5f85\u5bfc\u5165\u89c6\u9891", waiting: "\u5f85\u8f6c\u5199", queued: "排队中", running: "运行中", paused: "已暂停", done: "已完成", error: "失败", cancelled: "已取消" }[status] || status || "未知";
}

function taskStatusClass(status) {
  if (["done"].includes(status)) return "done";
  if (["error"].includes(status)) return "error";
  if (["cancelled"].includes(status)) return "cancelled";
  if (["draft", "waiting", "queued", "running", "paused"].includes(status)) return "running";
  return "";
}

function taskTitle(task) {
  if (task.title) return task.title;
  if (task.type === "export") return `导出 ${task.clip_ids?.length || 0} 条片段`;
  if (task.type === "transcribe") return "转写文字稿";
  if (task.type === "analyze") return "筛选金句片段";
  const clip = (state.highlights.clips || []).find((item) => item.id === task.clip_id);
  return clip?.title || task.clip_id || task.task_id;
}

function draftTaskEntries() {
  return (state.draftTabs || []).map((jobId) => {
    const meta = state.jobMeta[jobId] || {};
    return {
      task_id: jobId,
      job_id: jobId,
      title: meta.title || "\u672a\u547d\u540d\u4efb\u52a1",
      type: "draft",
      status: "draft",
      message: "\u7b49\u5f85\u9009\u62e9\u89c6\u9891\u6587\u4ef6",
      virtual: true,
    };
  });
}

function waitingWorkspaceEntries(jobs, backgroundTasks) {
  const busyJobIds = new Set((backgroundTasks || [])
    .filter((task) => ["queued", "running", "paused"].includes(task.status))
    .map((task) => task.job_id));
  return (jobs || [])
    .filter((job) => job?.job_id && job.status === "uploaded" && !busyJobIds.has(job.job_id))
    .map((job) => ({
      task_id: `workspace_${job.job_id}`,
      job_id: job.job_id,
      title: job.title || job.job_id,
      type: "workspace",
      status: "waiting",
      message: "\u89c6\u9891\u5df2\u52a0\u5165\u4efb\u52a1\u4e2d\u5fc3\uff0c\u7b49\u5f85\u5f00\u59cb\u8f6c\u5199",
      virtual: true,
    }));
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
    if (task.job_id !== state.jobId) return;
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

async function refreshTasksLegacy() {
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
  const data = await api("/api/tasks/clear-finished", { method: "POST", body: JSON.stringify({ job_id: null }) });
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
  const previewStage = job?.preview_stage || (["previewing", "preview_ready", "preview_error"].includes(job?.stage) ? job.stage : null);
  if (!previewStage) return;
  el.previewStatus.hidden = false;
  const progress = typeof job.preview_progress === "number" ? Math.max(0, Math.min(1, job.preview_progress)) : 0;
  const percent = Math.round(progress * 100);
  el.previewProgressBar.style.width = `${percent}%`;
  el.previewStatusPercent.textContent = previewStage === "preview_error" ? "\u5931\u8d25" : `${percent}%`;
  el.previewStatusText.textContent = job.preview_message || (["previewing", "preview_ready", "preview_error"].includes(job?.stage) ? job.message : "") || "\u6b63\u5728\u751f\u6210\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8 MP4";
  if (previewStage === "preview_ready") {
    el.previewStatusTime.textContent = "\u517c\u5bb9\u9884\u89c8\u5df2\u5b8c\u6210\uff0c\u53ef\u4ee5\u6b63\u5e38\u67e5\u770b\u753b\u9762\u3002";
  } else if (previewStage === "preview_error") {
    el.previewStatusTime.textContent = "\u751f\u6210\u5931\u8d25\uff0c\u53ef\u4ee5\u7ee7\u7eed\u8f6c\u5199\uff1b\u6700\u7ec8\u5bfc\u51fa\u4ecd\u4f1a\u5c1d\u8bd5\u4f7f\u7528\u539f\u89c6\u9891\u3002";
  } else {
    el.previewStatusTime.textContent = `\u5df2\u7528 ${formatShortTime(job.preview_elapsed)}\uff0c\u9884\u8ba1\u5269\u4f59 ${formatShortTime(job.preview_remaining)}`;
  }
}

function timelinePercent(time, duration) {
  return `${Math.max(0, Math.min(100, duration ? (Number(time || 0) / duration) * 100 : 0))}%`;
}

function renderTrimTimeline() {
  const duration = trimVideoDuration();
  const start = parseClock(el.trimStartInput?.value || 0);
  const end = parseClock(el.trimEndInput?.value || duration || 0);
  const current = Number(el.sourceVideo?.currentTime || 0);
  if (el.trimSelection) { el.trimSelection.style.left = timelinePercent(start, duration); el.trimSelection.style.width = `${Math.max(0, (end - start) / Math.max(duration, 0.001) * 100)}%`; }
  if (el.trimStartHandle) el.trimStartHandle.style.left = timelinePercent(start, duration);
  if (el.trimEndHandle) el.trimEndHandle.style.left = timelinePercent(end, duration);
  if (el.trimPlayhead) el.trimPlayhead.style.left = timelinePercent(current, duration);
}

function updateModalTrimReadouts() {
  if (!state.modalTrim) return;
  const { start, end } = state.modalTrim;
  if (el.modalTrimStartInput) el.modalTrimStartInput.value = formatClock(start);
  if (el.modalTrimEndInput) el.modalTrimEndInput.value = formatClock(end);
  if (el.modalTrimDurationInput) el.modalTrimDurationInput.value = `${Math.max(0, end - start).toFixed(2)} 秒`;
}

function renderModalTimeline() {
  if (!state.modalTrim || !el.modalTrimTimeline) return;
  const duration = Number(el.modalClipVideo?.duration || trimVideoDuration() || 1);
  const { start, end, current } = state.modalTrim;
  if (el.modalTrimSelection) { el.modalTrimSelection.style.left = timelinePercent(start, duration); el.modalTrimSelection.style.width = `${Math.max(0, (end - start) / duration * 100)}%`; }
  if (el.modalTrimStartHandle) el.modalTrimStartHandle.style.left = timelinePercent(start, duration);
  if (el.modalTrimEndHandle) el.modalTrimEndHandle.style.left = timelinePercent(end, duration);
  if (el.modalTrimPlayhead) el.modalTrimPlayhead.style.left = timelinePercent(current, duration);
  updateModalTrimReadouts();
}

function timelineTimeFromPointer(event, timeline, duration) {
  const rect = timeline.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)));
  return ratio * duration;
}

function bindTimelineDrag(timeline, which) {
  if (!timeline) return;
  timeline.addEventListener("pointerdown", (event) => {
    const duration = which === "modal" ? Number(el.modalClipVideo?.duration || trimVideoDuration() || 1) : trimVideoDuration();
    if (!duration) return;
    const time = timelineTimeFromPointer(event, timeline, duration);
    if (which === "modal") {
      if (!state.modalTrim) return;
      const distanceStart = Math.abs(time - state.modalTrim.start);
      const distanceEnd = Math.abs(time - state.modalTrim.end);
      state.timelineDragging = distanceStart <= distanceEnd ? "modal-start" : "modal-end";
      if (event.target.closest(".clip-handle.start")) state.timelineDragging = "modal-start";
      else if (event.target.closest(".clip-handle.end")) state.timelineDragging = "modal-end";
      else { state.timelineDragging = "modal-playhead"; state.modalTrim.current = time; if (el.modalClipVideo) el.modalClipVideo.currentTime = time; }
      renderModalTimeline();
    } else {
      const start = parseClock(el.trimStartInput?.value || 0); const end = parseClock(el.trimEndInput?.value || duration);
      const distanceStart = Math.abs(time - start); const distanceEnd = Math.abs(time - end);
      state.timelineDragging = event.target.closest(".clip-handle.start") ? "start" : event.target.closest(".clip-handle.end") ? "end" : "playhead";
      if (state.timelineDragging === "playhead") setSourcePreviewTime(time);
      else setTrimValue(state.timelineDragging, time, true);
      renderTrimTimeline();
    }
    timeline.setPointerCapture?.(event.pointerId);
  });
  timeline.addEventListener("pointermove", (event) => {
    if (!state.timelineDragging) return;
    const duration = state.timelineDragging.startsWith("modal") ? Number(el.modalClipVideo?.duration || trimVideoDuration() || 1) : trimVideoDuration();
    const time = timelineTimeFromPointer(event, timeline, duration);
    if (state.timelineDragging === "modal-start" || state.timelineDragging === "modal-end") {
      const gap = 1 / 30;
      if (state.timelineDragging === "modal-start") state.modalTrim.start = Math.min(time, state.modalTrim.end - gap); else state.modalTrim.end = Math.max(time, state.modalTrim.start + gap);
      state.modalTrim.current = state.timelineDragging === "modal-start" ? state.modalTrim.start : state.modalTrim.end;
      if (el.modalClipVideo) el.modalClipVideo.currentTime = state.modalTrim.current;
      renderModalTimeline();
    } else if (state.timelineDragging === "modal-playhead") {
      state.modalTrim.current = time;
      if (el.modalClipVideo) el.modalClipVideo.currentTime = time;
      renderModalTimeline();
    } else if (state.timelineDragging === "playhead") {
      setSourcePreviewTime(time);
      renderTrimTimeline();
    } else {
      setTrimValue(state.timelineDragging, time, true);
      renderTrimTimeline();
    }
  });
  timeline.addEventListener("pointerup", () => { state.timelineDragging = null; });
  timeline.addEventListener("pointercancel", () => { state.timelineDragging = null; });
}

async function captureTimelineFrames() {
  const source = el.sourceVideo?.currentSrc || state.localUrl;
  const duration = trimVideoDuration();
  if (!source || !duration || !el.trimFrameStrip) return;
  const count = Math.min(56, Math.max(16, Math.ceil(duration / 4)));
  const sampler = document.createElement("video");
  sampler.muted = true; sampler.playsInline = true; sampler.preload = "auto"; sampler.src = source;
  await new Promise((resolve) => { if (sampler.readyState >= 1) resolve(); else { sampler.addEventListener("loadedmetadata", resolve, { once: true }); sampler.addEventListener("error", resolve, { once: true }); } });
  const canvas = document.createElement("canvas"); canvas.width = 240; canvas.height = 135;
  const ctx = canvas.getContext("2d"); const frames = [];
  for (let index = 0; index < count; index += 1) {
    const time = Math.min(duration, duration * index / Math.max(1, count - 1));
    await new Promise((resolve) => { const done = () => { sampler.removeEventListener("seeked", done); resolve(); }; sampler.addEventListener("seeked", done); sampler.currentTime = time; setTimeout(done, 900); });
    try { ctx.drawImage(sampler, 0, 0, canvas.width, canvas.height); frames.push(canvas.toDataURL("image/jpeg", .62)); } catch { frames.push(""); }
  }
  sampler.removeAttribute("src"); sampler.load();
  state.timelineFrames = frames;
  el.trimFrameStrip.innerHTML = frames.map((src) => src ? `<img class="clip-frame" src="${src}" alt="">` : '<span class="clip-frame-placeholder"></span>').join("");
  if (el.modalTrimFrameStrip) el.modalTrimFrameStrip.innerHTML = el.trimFrameStrip.innerHTML;
  renderTrimTimeline();
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
  const raw = await response.text();
  let data = {};
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    const message = response.status === 404
      ? "接口未找到：请确认工作台服务已重启。"
      : `服务返回了非 JSON 响应（HTTP ${response.status}）。`;
    throw new Error(message);
  }
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

function cacheActiveDraftMedia() {
  const draftId = state.activeDraftId;
  if (!draftId || (!state.localFile && !state.localUrl)) return;
  const previous = state.draftMedia[draftId] || {};
  const start = parseClock(el.trimStartInput?.value || previous.trimStart || 0);
  const end = parseClock(el.trimEndInput?.value || previous.trimEnd || 0);
  state.draftMedia[draftId] = {
    ...previous,
    file: state.localFile || previous.file || null,
    url: state.localUrl || previous.url || null,
    trimStart: start,
    trimEnd: end > start ? end : null,
  };
}

function releaseDraftMedia(draftId) {
  if (!draftId) return;
  const draft = state.draftMedia[draftId];
  const urls = new Set([draft?.url]);
  if (state.activeDraftId === draftId) urls.add(state.localUrl);
  urls.forEach((url) => {
    if (url) URL.revokeObjectURL(url);
  });
  delete state.draftMedia[draftId];
  if (state.activeDraftId === draftId) {
    state.localFile = null;
    state.localUrl = null;
  }
}

function restoreDraftMedia(draftId) {
  const draft = state.draftMedia[draftId];
  state.localFile = draft?.file || null;
  state.localUrl = draft?.url || null;
  el.fileInput.value = "";
  if (!state.localUrl || !state.localFile) return false;
  el.sourceVideo.src = state.localUrl;
  el.sourceVideo.load();
  el.transcribeButton.disabled = true;
  setPreviewButtonsDisabled(false);
  el.metadata.textContent = `${state.localFile.name} · ${(state.localFile.size / 1024 / 1024).toFixed(1)} MB · 已在浏览器载入，可先预览。`;
  showManualTrimPanel(draft?.trimStart || 0, draft?.trimEnd || null);
  return true;
}

async function uploadCurrentVideo() {
  if (state.jobId) return state.metadata;
  if (state.uploadPromise) return state.uploadPromise;
  if (!state.localFile) throw new Error("请先选择视频文件。");
  state.uploadPromise = (async () => {
    const form = new FormData();
    form.append("file", state.localFile);
    toast("正在准备视频...");
    const data = await api("/api/video/upload", { method: "POST", body: form });
    const uploadedDraftId = state.activeDraftId;
    const uploadedFileName = state.localFile?.name || "视频";
    state.jobId = data.job_id;
    state.activeJobId = data.job_id;
    ensureJobTab(data.job_id, { title: data.metadata?.title || uploadedFileName });
    updateMetadata(data.metadata);
    el.sourceVideo.src = data.preview_url;
    if (uploadedDraftId) {
      state.draftTabs = (state.draftTabs || []).filter((id) => id !== uploadedDraftId);
      delete state.jobMeta[uploadedDraftId];
      releaseDraftMedia(uploadedDraftId);
      state.activeDraftId = null;
    }
    el.transcribeButton.disabled = data.metadata?.has_audio === false;
    const canMakePreview = needsBrowserPreview(data.metadata);
    setPreviewButtonsDisabled(data.browser_preview_queued || !canMakePreview);
    const selectedStart = parseClock(el.trimStartInput?.value || 0);
    const selectedEnd = parseClock(el.trimEndInput?.value || 0);
    showManualTrimPanel(selectedStart, selectedEnd > selectedStart ? selectedEnd : null);
    await refreshTasks();
    if (data.browser_preview_queued) {
      updatePreviewStatus({ stage: "previewing", message: "正在生成浏览器兼容预览 MP4", preview_progress: 0, preview_elapsed: 0, preview_remaining: null });
      startPolling();
    }
    return data.metadata;
  })();
  try {
    return await state.uploadPromise;
  } finally {
    state.uploadPromise = null;
  }
}

async function requestBrowserPreview() {
  await uploadCurrentVideo();
  updatePreviewStatus({ stage: "previewing", message: "\u6b63\u5728\u751f\u6210\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8 MP4", preview_progress: 0, preview_elapsed: 0, preview_remaining: null });
  setPreviewButtonsDisabled(true);
  await api("/api/video/browser-preview", { method: "POST", body: JSON.stringify({ job_id: state.jobId }) });
  startPolling();
}

function groupTranscriptSegments(segments = []) {
  const groups = [];
  let current = null;
  for (const segment of segments) {
    const text = String(segment?.text || "").trim();
    if (!text) continue;
    if (!current) {
      current = { start: Number(segment.start || 0), end: Number(segment.end || 0), text };
      continue;
    }
    const start = Number(segment.start || 0);
    const end = Number(segment.end || 0);
    const mergedText = `${current.text} ${text}`;
    if (start - current.end > 1.2 || end - current.start > 45 || mergedText.length > 260) {
      groups.push(current);
      current = { start, end, text };
    } else {
      current.end = end;
      current.text = mergedText;
    }
  }
  if (current) groups.push(current);
  return groups;
}

function switchView(view) {
  const next = ["trends", "workbench", "providers", "provider-list", "tasks", "storage"].includes(view) ? view : "workbench";
  state.currentView = next;
  Object.entries(el.appViews || {}).forEach(([key, node]) => { if (node) node.hidden = key !== next; });
  (el.navItems || []).forEach((button) => {
    const active = button.dataset.view === (next === "provider-list" ? "providers" : next);
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  const titles = {
    trends: ["爆款搜索", "按关键词发现近期高热度视频并导入工作台"],
    workbench: ["工作台", "转写、分析、裁剪与导出"],
    providers: ["供应商管理", "管理 LLM 与火山语音转写配置"],
    "provider-list": [providerKindLabel(state.providerKind) + "配置", "查看、编辑并选择当前工作台使用的配置"],
    tasks: ["任务中心", "总览所有视频的后台处理进度"],
    storage: ["存储管理", "按原视频查看本地结果文件"],
  };
  if (el.viewTitle) el.viewTitle.textContent = titles[next][0];
  if (el.viewSubtitle) el.viewSubtitle.textContent = titles[next][1];
  if (next === "tasks") refreshTasks().catch(() => {});
  if (next === "providers" || next === "provider-list") refreshProviders().catch(() => {});
  if (next === "storage") { refreshLibrary().catch(() => {}); refreshStorage().catch(() => {}); }
}

function localDateInputValue(value) {
  const offset = value.getTimezoneOffset() * 60 * 1000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}

function trendDateBounds() {
  const mode = el.trendDateRange?.value || "7";
  if (mode === "all") return { start_at: "", end_at: "" };
  if (mode === "custom") return { start_at: el.trendStartDate?.value || "", end_at: el.trendEndDate?.value || "" };
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - Number(mode || 7));
  return { start_at: localDateInputValue(start), end_at: localDateInputValue(end) };
}

function trendTaskForCandidate(candidateId) {
  return Object.values(state.trends.importTasks || {}).find((task) => task.candidate_id === candidateId) || null;
}

function trendImportLabel(task) {
  if (!task) return "导入工作台";
  if (task.status === "queued") return "等待下载";
  if (task.status === "running") return task.stage === "creating_job" ? "正在进入工作台" : "正在下载";
  if (task.status === "done") return "已进入工作台";
  return "导入失败";
}

function trendImportProgressText(task) {
  if (!task) return "";
  const percent = Math.round(Math.max(0, Math.min(100, Number(task.progress || 0) * 100)));
  if (task.status === "error") return `失败 · ${task.message || "请重试"}`;
  if (task.status === "done") return "100% · 已进入工作台";
  return `${percent}% · ${task.message || "正在处理"}`;
}

function selectedTrendCandidateIds() {
  if (!el.trendResults) return [];
  return Array.from(el.trendResults.querySelectorAll("[data-trend-candidate]:checked")).map((input) => input.value);
}

function renderTrendResults() {
  if (!el.trendResults) return;
  const candidates = state.trends.candidates || [];
  if (!candidates.length) {
    el.trendResults.className = "trend-results trend-results-empty";
    el.trendResults.textContent = state.trends.searchId
      ? (state.trends.warnings?.[0] || "没有找到可显示的候选视频。可以调整关键词或时间范围后重试。")
      : "搜索结果会在这里出现。";
    return;
  }
  el.trendResults.className = "trend-results";
  el.trendResults.innerHTML = `
    <div class="trend-result-head"><span></span><span>视频</span><span>平台</span><span>发布时间</span><span>评分</span><span></span></div>
  `;
  candidates.forEach((candidate) => {
    const task = trendTaskForCandidate(candidate.candidate_id);
    const locked = ["queued", "running", "done"].includes(task?.status);
    const row = document.createElement("div");
    row.className = `trend-result-row ${candidate.selected ? "selected" : ""}`;
    row.innerHTML = `
      <label><input type="checkbox" data-trend-candidate value="${escapeHtml(candidate.candidate_id)}" ${candidate.selected ? "checked" : ""} ${locked ? "disabled" : ""} aria-label="选择视频" /></label>
      <div class="trend-result-main"><strong class="trend-result-title">${escapeHtml(candidate.title)}</strong><span class="trend-result-description">${escapeHtml(candidate.description || "搜索结果未提供简介")}</span><a class="trend-result-link" href="${escapeHtml(candidate.url)}" target="_blank" rel="noopener noreferrer" title="打开原视频网页">${escapeHtml(candidate.url)}</a></div>
      <span class="trend-platform">${escapeHtml(candidate.platform || "网页视频")}</span>
      <span class="trend-published">${escapeHtml(candidate.published_at || "未提供")}</span>
      <span class="trend-score">${Math.round(Number(candidate.heat_score || 0))}</span>
      <span class="trend-result-actions"><button type="button" data-trend-import="${escapeHtml(candidate.candidate_id)}" ${locked ? "disabled" : ""} ${task?.status === "error" && task.message ? `title="${escapeHtml(task.message)}"` : ""}>${trendImportLabel(task)}</button>${task ? `<small class="trend-import-progress">${escapeHtml(trendImportProgressText(task))}</small>` : ""}</span>
    `;
    row.querySelector("[data-trend-candidate]")?.addEventListener("change", (event) => {
      candidate.selected = event.currentTarget.checked;
      row.classList.toggle("selected", candidate.selected);
      updateTrendSelectionSummary();
    });
    row.querySelector("[data-trend-import]")?.addEventListener("click", () => importTrendCandidates([candidate.candidate_id]));
    el.trendResults.appendChild(row);
  });
  const footer = document.createElement("div");
  footer.className = "trend-import-bar";
  footer.innerHTML = `<span id="trendImportSelection">已选择 0 个视频</span><button id="trendImportSelected" class="primary" type="button">导入已选择视频</button>`;
  footer.querySelector("#trendImportSelected")?.addEventListener("click", () => importTrendCandidates(selectedTrendCandidateIds()));
  el.trendResults.appendChild(footer);
  updateTrendSelectionSummary();
}

function updateTrendSelectionSummary() {
  const selection = document.getElementById("trendImportSelection");
  if (selection) selection.textContent = `已选择 ${selectedTrendCandidateIds().length} 个视频`;
}

function clearTrendSearchResults() {
  state.trends.searchToken = (state.trends.searchToken || 0) + 1;
  state.trends.searchId = null;
  state.trends.candidates = [];
  state.trends.warnings = [];
  if (el.trendSearchButton) el.trendSearchButton.disabled = false;
  if (el.trendSearchStatus) el.trendSearchStatus.textContent = "输入关键词后开始搜索。";
  if (el.trendResultSummary) el.trendResultSummary.textContent = "";
  renderTrendResults();
}

async function runTrendSearch() {
  const keywords = (el.trendKeywords?.value || "").trim();
  if (!keywords) {
    toast("请先输入至少一个关键词。");
    el.trendKeywords?.focus();
    return;
  }
  const bounds = trendDateBounds();
  if (bounds.start_at && bounds.end_at && bounds.start_at > bounds.end_at) {
    toast("开始日期不能晚于结束日期。");
    return;
  }
  el.trendSearchButton.disabled = true;
  el.trendSearchStatus.textContent = "正在搜索视频网页并整理候选清单...";
  el.trendResultSummary.textContent = "";
  const searchToken = (state.trends.searchToken || 0) + 1;
  state.trends.searchToken = searchToken;
  try {
    const data = await api("/api/trends/search", {
      method: "POST",
      body: JSON.stringify({ keywords, source: el.trendSource?.value || "web", limit: Number(el.trendLimit?.value || 10), ...bounds }),
    });
    if (searchToken !== state.trends.searchToken) return;
    state.trends.searchId = data.search_id;
    state.trends.candidates = (data.candidates || []).map((candidate) => ({ ...candidate, selected: false }));
    state.trends.warnings = data.warnings || [];
    if (el.trendProviderBadge) el.trendProviderBadge.textContent = data.provider === "bing_rss" ? "Bing 视频搜索" : data.provider || "视频搜索";
    el.trendSearchStatus.textContent = data.candidates?.length ? "已找到候选视频，可打开网页核对后选择导入。" : "没有找到候选视频，请尝试更具体的关键词。";
    el.trendResultSummary.textContent = `${data.candidates?.length || 0} 个候选`;
    renderTrendResults();
    if (data.warnings?.length) toast(data.warnings[0]);
  } catch (err) {
    if (searchToken !== state.trends.searchToken) return;
    state.trends.searchId = null;
    state.trends.candidates = [];
    renderTrendResults();
    el.trendSearchStatus.textContent = `搜索失败：${err.message}`;
    toast(`视频搜索失败：${err.message}`);
  } finally {
    if (searchToken === state.trends.searchToken) el.trendSearchButton.disabled = false;
  }
}

async function openTrendChrome() {
  const keywords = (el.trendKeywords?.value || "").trim();
  if (!keywords) {
    toast("请先输入关键词，再打开 Chrome 搜索页。");
    el.trendKeywords?.focus();
    return;
  }
  if (el.trendOpenChromeButton) el.trendOpenChromeButton.disabled = true;
  try {
    const data = await api("/api/trends/browser/open", {
      method: "POST",
      body: JSON.stringify({ keywords, source: el.trendSource?.value || "web" }),
    });
    if (el.trendSearchStatus) el.trendSearchStatus.textContent = data.message || "已打开浏览器，请完成登录后返回应用。";
    toast(data.message || "已打开浏览器");
  } catch (err) {
    toast(`打开浏览器失败：${err.message}`);
  } finally {
    if (el.trendOpenChromeButton) el.trendOpenChromeButton.disabled = false;
  }
}

async function importTrendCandidates(candidateIds) {
  const ids = [...new Set(candidateIds || [])];
  if (!ids.length) {
    toast("请先选择要导入的视频。");
    return;
  }
  if (!state.trends.searchId) {
    toast("搜索结果已失效，请重新搜索。");
    return;
  }
  try {
    const data = await api("/api/trends/import", { method: "POST", body: JSON.stringify({ search_id: state.trends.searchId, candidate_ids: ids }) });
    (data.tasks || []).forEach((task) => { state.trends.importTasks[task.task_id] = task; });
    ids.forEach((id) => {
      const candidate = state.trends.candidates.find((item) => item.candidate_id === id);
      if (candidate) candidate.selected = false;
    });
    renderTrendResults();
    el.trendSearchStatus.textContent = `已加入 ${data.tasks?.length || 0} 个下载任务，完成后会自动打开工作台。`;
    ensureTrendImportPolling();
  } catch (err) {
    toast(`导入失败：${err.message}`);
  }
}

async function ensureTrendImportPolling() {
  if (state.trends.polling) return;
  state.trends.polling = true;
  try {
    while (true) {
      const pending = Object.values(state.trends.importTasks).filter((task) => ["queued", "running"].includes(task.status));
      if (!pending.length) break;
      await Promise.all(pending.map(async (current) => {
        try {
          const data = await api(`/api/trends/import/status?task_id=${encodeURIComponent(current.task_id)}`);
          const task = data.task;
          state.trends.importTasks[task.task_id] = task;
          if (task.status === "error" && task.message) toast(`导入失败：${task.message}`);
          if (task.status === "done" && task.job_id && !state.trends.openedJobIds.has(task.job_id)) {
            state.trends.openedJobIds.add(task.job_id);
            ensureJobTab(task.job_id, { title: task.metadata?.title || task.title || task.job_id });
            await refreshTasks();
            await refreshLibrary();
            switchView("workbench");
            await loadJob(task.job_id);
            toast(`已导入工作台：${task.metadata?.title || task.title || "视频"}`);
          }
        } catch (err) {
          state.trends.importTasks[current.task_id] = { ...current, status: "error", message: err.message };
        }
      }));
      renderTrendResults();
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
  } finally {
    state.trends.polling = false;
    renderTrendResults();
  }
}

function renderWorkbenchTabs() {
  if (!el.workbenchTabs) return;
  el.workbenchTabs.innerHTML = "";
  const ids = [...(state.openJobIds || []), ...(state.draftTabs || [])];
  if (!ids.length) {
    el.workbenchTabs.classList.remove("has-tabs");
    return;
  }
  el.workbenchTabs.classList.add("has-tabs");
  ids.forEach((jobId) => {
    const meta = state.jobMeta[jobId] || {};
    const tab = document.createElement("button");
    tab.type = "button";
    const isActive = jobId === state.jobId || jobId === state.activeDraftId;
    tab.className = `workbench-tab ${isActive ? "active" : ""}`;
    tab.title = meta.title || jobId;
     tab.innerHTML = `<span class="tab-status ${meta.statusClass || ""}"></span><span class="tab-label">${escapeHtml(meta.title || jobId)}</span><span class="tab-close" aria-label="关闭">×</span>`;
    tab.addEventListener("click", (event) => {
      if (event.target.closest(".tab-close")) {
        closeJobTab(jobId);
        return;
      }
      loadJob(jobId);
    });
    el.workbenchTabs.appendChild(tab);
  });
}

function createDraftTask() {
  if (state.activeDraftId) cacheActiveDraftMedia();
  const draftId = `draft_${Date.now()}_${Math.random().toString(16).slice(2, 6)}`;
  state.draftSequence += 1;
  state.draftTabs.push(draftId);
  state.jobMeta[draftId] = { title: `\u672a\u547d\u540d\u4efb\u52a1 ${state.draftSequence}`, isDraft: true };
  state.activeDraftId = draftId;
  resetCurrentVideoView({ keepTabs: true, keepLocalMedia: true, silent: true });
  renderWorkbenchTabs();
  refreshTasks().catch(() => {});
  setStatus("新建任务已加入任务中心，等待输入视频");
  return draftId;
}

function ensureJobTab(jobId, meta = {}) {
  if (!jobId) return;
  if (!state.openJobIds.includes(jobId)) state.openJobIds.push(jobId);
  state.jobMeta[jobId] = { ...(state.jobMeta[jobId] || {}), ...meta };
  renderWorkbenchTabs();
}

function closeJobTab(jobId) {
  const isDraft = (state.draftTabs || []).includes(jobId);
  if (isDraft) releaseDraftMedia(jobId);
  state.openJobIds = state.openJobIds.filter((id) => id !== jobId);
  state.draftTabs = (state.draftTabs || []).filter((id) => id !== jobId);
  delete state.jobMeta[jobId];
  if (state.jobId === jobId || state.activeDraftId === jobId) {
    const next = [...state.openJobIds, ...(state.draftTabs || [])].slice(-1)[0];
    if (next) loadJob(next);
    else { state.activeDraftId = null; resetCurrentVideoView({ keepTabs: true }); }
  }
  renderWorkbenchTabs();
}

function transcriptText(groups = state.transcript.groups) {
  return (groups || []).map((group) => `[${formatClock(group.start)} - ${formatClock(group.end)}] ${group.text}`).join("\n\n");
}

function updateTranscriptFileLocation(files = null) {
  if (!el.transcriptFileLocation) return;
  const path = files?.markdown;
  el.transcriptFileLocation.textContent = path ? `结果文件夹：${files.folder}` : "完成转写后会在视频结果文件夹中保存 transcript_grouped.md";
}

function updateTranscript(segments, groups = null) {
  const rawSegments = segments || [];
  const groupedSegments = Array.isArray(groups) && groups.length ? groups : groupTranscriptSegments(rawSegments);
  state.transcript = { segments: rawSegments, groups: groupedSegments };
  const count = groupedSegments.length;
  el.transcriptCount.textContent = `${count} 组`;
  if (el.transcriptModeText) el.transcriptModeText.textContent = count ? `按时间分组显示 ${count} 组文字稿` : "按时间分组显示文字稿";
  el.transcript.textContent = transcriptText();
  el.analyzeButton.disabled = !state.jobId || rawSegments.length === 0;
}

function setAnalyzeControls(task = null) {
  const active = task && ["queued", "running", "paused"].includes(task.status);
  if (el.pauseAnalyzeButton) {
    el.pauseAnalyzeButton.disabled = !active;
    el.pauseAnalyzeButton.textContent = task?.status === "paused" ? "继续分析" : "暂停分析";
  }
  if (el.stopAnalyzeButton) el.stopAnalyzeButton.disabled = !active;
}

function transcriptSegmentKey(segment) {
  const id = segment?.id;
  if (id !== undefined && id !== null && String(id).trim()) return `id:${id}`;
  return `time:${Number(segment?.start || 0)}:${Number(segment?.end || 0)}:${String(segment?.text || "")}`;
}

function mergeTranscriptSegments(incomingSegments) {
  if (!Array.isArray(incomingSegments) || incomingSegments.length === 0) return false;

  const mergedByKey = new Map();
  for (const segment of state.transcript.segments || []) {
    if (segment && typeof segment === "object") mergedByKey.set(transcriptSegmentKey(segment), segment);
  }
  for (const segment of incomingSegments) {
    if (segment && typeof segment === "object") mergedByKey.set(transcriptSegmentKey(segment), segment);
  }

  const merged = Array.from(mergedByKey.values()).sort((a, b) => (
    Number(a.start || 0) - Number(b.start || 0)
    || Number(a.end || 0) - Number(b.end || 0)
    || String(a.id || "").localeCompare(String(b.id || ""))
  ));
  const before = (state.transcript.segments || []).map(transcriptSegmentKey).join("\n");
  const after = merged.map(transcriptSegmentKey).join("\n");
  if (before === after) return false;

  updateTranscript(merged);
  return true;
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
function clampTrimTime(value) {
  const duration = trimVideoDuration();
  const numeric = Math.max(0, Number(value) || 0);
  return duration ? Math.min(duration, numeric) : numeric;
}

function setSourcePreviewTime(value) {
  const next = clampTrimTime(value);
  if (Number.isFinite(next)) el.sourceVideo.currentTime = next;
  if (el.sourceTimeText) el.sourceTimeText.textContent = `\u5f53\u524d ${formatClock(next)}`;
  renderTrimTimeline();
}

function updateTrimReadouts(seekTo = null) {
  const start = parseClock(el.trimStartInput.value || 0);
  const end = parseClock(el.trimEndInput.value || 0);
  if (el.trimStartInput) el.trimStartInput.value = formatClock(start);
  if (el.trimEndInput) el.trimEndInput.value = formatClock(end);
  if (el.trimDurationInput) el.trimDurationInput.value = `${Math.max(0, end - start).toFixed(2)} \u79d2`;
  if (seekTo !== null) setSourcePreviewTime(seekTo);
  renderTrimTimeline();
}

function setTrimValue(field, value, seek = true) {
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

function showManualTrimPanel(defaultStart = null, defaultEnd = null) {
  if (!el.sourceTrimPanel) return;
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
  el.activeClipTitle.textContent = "\u8f6c\u5199\u8303\u56f4\uff1a\u5728\u89c6\u9891\u8f68\u9053\u4e0a\u62d6\u52a8\u9009\u62e9\u533a\u95f4";
  el.trimStartInput.value = formatClock(start);
  el.trimEndInput.value = formatClock(end > start ? end : start + 15);
  updateTrimReadouts(start);
}

function syncTrimPanelFromClip() {
  const clip = activeClip();
  if (!clip || !el.sourceTrimPanel) return;
  const index = state.highlights.clips.findIndex((item) => item.id === clip.id);
  el.sourceTrimPanel.hidden = false;
  el.sourceTrimPanel.dataset.clipId = clip.id;
  el.activeClipTitle.textContent = `\u6b63\u5728\u5fae\u8c03\u7b2c ${index >= 0 ? index + 1 : "?"} \u6761\uff1a${clip.title || clip.id}`;
  el.trimStartInput.value = formatClock(clip.start);
  el.trimEndInput.value = formatClock(clip.end);
  updateTrimReadouts(null);
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
  const start = parseClock(el.trimStartInput.value);
  const end = parseClock(el.trimEndInput.value);
  if (!(end > start)) {
    toast("\u7ed3\u675f\u65f6\u95f4\u5fc5\u987b\u665a\u4e8e\u5f00\u59cb\u65f6\u95f4");
    return null;
  }
  if (state.trimSavePromise) return state.trimSavePromise;
  state.trimSavePromise = (async () => {
    await uploadCurrentVideo();
    const data = await api("/api/transcribe/range", { method: "POST", body: JSON.stringify({ job_id: state.jobId, start, end }) });
    state.metadata = data.metadata || state.metadata;
    state.activeClipId = null;
    if (el.sourceTrimPanel) el.sourceTrimPanel.dataset.clipId = "";
    showManualTrimPanel(start, end);
    el.transcribeButton.disabled = state.metadata?.has_audio === false;
    toast(state.metadata?.has_audio === false
      ? "已保存转写范围，但当前视频没有音轨，无法开始转写。"
      : `已保存转写范围 ${formatClock(start)} - ${formatClock(end)}，现在可以开始转写。`);
    return data.range;
  })();
  try {
    return await state.trimSavePromise;
  } finally {
    state.trimSavePromise = null;
  }
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


function clipScore(clip) {
  return Number(clip.selection_score ?? clip.viral_score ?? clip.quote_score ?? 0) || 0;
}

function clipStars(clip) {
  return Math.max(1, Math.min(5, Math.round(clipScore(clip) / 20)));
}

function clipHashtags(clip) {
  const value = clip.hashtags ?? clip.tags ?? [];
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  return String(value || "").split(/[\\s,，#]+/).map((item) => item.trim()).filter(Boolean);
}

function renderAnalysisDetails(clip, index) {
  const duration = Math.max(0, Number(clip.end || 0) - Number(clip.start || 0));
  const stars = "★".repeat(clipStars(clip)) + "☆".repeat(5 - clipStars(clip));
  const tags = clipHashtags(clip);
  const score = clipScore(clip);
  const scoreText = score ? `${score.toFixed(1)} / 100` : "待评分";
  const title = clip.suggested_title || clip.title || clip.id;
  const original = clip.original_copy || clip.quote || "";
  const xhs = clip.xiaohongshu_copy || clip.hook_text || clip.quote || "";
  const comment = clip.comment_prompt || clip.comment_guide || "你最认同这段里的哪个观点？";
  const tagsHtml = tags.map((tag) => `<span>#${escapeHtml(tag.replace(/^#/, ""))}</span>`).join("");
  if (el.clipPreviewDetails) el.clipPreviewDetails.innerHTML = `
    <div class="analysis-overview">
      <div class="analysis-title-row"><div><h3>${escapeHtml(title)}</h3><div class="analysis-meta">[${formatClock(clip.start)} - ${formatClock(clip.end)}] 约 ${duration.toFixed(1)}s · ${escapeHtml(clip.clip_type || "金句片段")}</div></div><span class="analysis-chip">${escapeHtml(clip.recommendation_label || "主推 · 有数字")}</span></div>
      <div class="analysis-meta"><div>候选标题B：${escapeHtml(clip.alternate_title || title)}</div><div class="analysis-stars">${stars} <span class="small">推荐指数 ${escapeHtml(scoreText)}</span></div></div>
      <div class="analysis-section"><h4>推荐理由</h4><p>${escapeHtml(clip.reason || "")}</p></div>
      <div class="analysis-section"><h4>原声文案（已精简口误）</h4><p class="analysis-copy">${escapeHtml(original)}</p></div>
      <div class="analysis-section"><h4>小红书文案</h4><p class="analysis-copy analysis-note">${escapeHtml(xhs)}</p></div>
      <div class="analysis-section"><h4>评论区引导</h4><p class="analysis-copy analysis-comment">${escapeHtml(comment)}</p></div>
      ${clip.editor_note ? `<div class="analysis-section"><h4>剪辑备注</h4><p>${escapeHtml(clip.editor_note)}</p></div>` : ""}
      <div class="analysis-tags">${tagsHtml}</div>
    </div>`;
  if (el.clipPreviewIndex) el.clipPreviewIndex.textContent = String(index + 1).padStart(2, "0");
  if (el.clipPreviewModalTitle) el.clipPreviewModalTitle.textContent = title;
}

function openClipPreview(clipId) {
  const clip = findClip(clipId);
  if (!clip || !el.clipPreviewModal) return;
  state.modalClipId = clipId;
  state.modalTrim = { start: Number(clip.start) || 0, end: Number(clip.end) || 0, current: Number(clip.start) || 0 };
  const source = el.sourceVideo.currentSrc || (state.metadata?.original_file ? mediaUrl(state.metadata.original_file) : "");
  if (el.modalClipVideo) { el.modalClipVideo.src = source; el.modalClipVideo.load(); }
  if (el.trimFrameStrip && el.modalTrimFrameStrip) el.modalTrimFrameStrip.innerHTML = el.trimFrameStrip.innerHTML;
  renderAnalysisDetails(clip, state.highlights.clips.findIndex((item) => item.id === clipId));
  el.clipPreviewModal.hidden = false;
  updateModalTrimReadouts();
  requestAnimationFrame(() => { if (el.modalClipVideo) el.modalClipVideo.currentTime = state.modalTrim.current; renderModalTimeline(); });
}

function closeClipPreview() {
  if (!el.clipPreviewModal) return;
  el.clipPreviewModal.hidden = true;
  state.modalClipId = null;
  state.modalTrim = null;
  el.modalClipVideo?.pause();
  el.modalClipVideo?.removeAttribute("src");
  el.modalClipVideo?.load();
}

function renderClips() {
  const clips = state.highlights.clips || [];
  el.clipSummary.textContent = `${clips.length} 个候选，${clips.filter((c) => c.confirmed).length} 个已确认`;
  el.renderAllButton.disabled = !clips.length;
  el.exportButton.disabled = !clips.some((c) => c.confirmed);
  if (!clips.length) { el.clips.className = "clips-empty"; el.clips.textContent = "LLM 分析后会在这里出现候选片段总览。"; return; }
  el.clips.className = "clips-list";
  el.clips.innerHTML = "";
  clips.forEach((clip, index) => {
    const card = document.createElement("article");
    card.className = "clip-card";
    const statusClass = clip.status === "confirmed" || clip.status === "exported" ? "confirmed" : clip.status === "error" ? "error" : "";
    const score = clipScore(clip);
    card.innerHTML = `<div class="clip-list-index">${String(index + 1).padStart(2, "0")}</div><div class="clip-list-main"><strong class="clip-title">${escapeHtml(clip.suggested_title || clip.title || clip.id)}</strong><span class="clip-list-reason">${escapeHtml(clip.reason || clip.quote || "暂无推荐理由")}</span><span class="clip-list-meta"><span>${formatClock(clip.start)} - ${formatClock(clip.end)}</span><span>${Math.max(0, Number(clip.end || 0) - Number(clip.start || 0)).toFixed(1)} 秒</span><span class="clip-list-score">推荐指数 ${score.toFixed(1)}</span><span class="clip-badge ${statusClass}">${escapeHtml(clipStatusText(clip))}</span></span></div><div class="clip-list-actions"><button data-action="preview" class="primary">预览</button><button data-action="confirm">${clip.confirmed ? "取消确认" : "确认"}</button><button data-action="export">导出</button><button data-action="delete" class="danger">删除</button></div>`;
    card.querySelector("[data-action='preview']").addEventListener("click", () => openClipPreview(clip.id));
    card.querySelector("[data-action='confirm']").addEventListener("click", () => confirmClip(clip.id, !clip.confirmed));
    card.querySelector("[data-action='export']").addEventListener("click", () => exportSingleClip(clip.id));
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
  state.analyzeTaskId = null;
  if (el.sourceTrimPanel) el.sourceTrimPanel.hidden = true;
  renderClips();
  await refreshLibrary();
  toast("候选片段已清空，可以重新分析生成。");
}

function resetCurrentVideoView(options = {}) {
  if (!options.keepTabs) {
    Object.keys(state.draftMedia || {}).forEach((draftId) => releaseDraftMedia(draftId));
    state.draftMedia = {};
  }
  if (state.localUrl && !options.keepLocalMedia) URL.revokeObjectURL(state.localUrl);
  state.localFile = null;
  state.localUrl = null;
  state.jobId = null;
  state.activeJobId = null;
  state.metadata = null;
  state.transcript = { segments: [] };
  state.highlights = { clips: [] };
  state.renderProgress = {};
  state.activeClipId = null;
  el.sourceVideo.removeAttribute("src");
  el.sourceVideo.load();
  el.fileInput.value = "";
  el.metadata.textContent = "还没有载入视频。";
  setPreviewButtonsDisabled(true);
  el.transcribeButton.disabled = true;
  el.analyzeButton.disabled = true;
  setAnalyzeControls(null);
  el.renderAllButton.disabled = true;
  el.exportButton.disabled = true;
  if (el.sourceTrimPanel) el.sourceTrimPanel.hidden = true;
  updateTranscript([]);
  updateTranscriptFileLocation(null);
  renderClips();
  if (!options.keepTabs) { state.openJobIds = []; state.draftTabs = []; state.jobMeta = {}; renderWorkbenchTabs(); }
  if (!options.silent) toast("当前界面已重置，原始文件和历史任务没有删除。");
}

async function reloadTranscript() {
  if (!state.jobId) return;
  const data = await api(`/api/job/load?job_id=${encodeURIComponent(state.jobId)}`);
  updateTranscript(data.transcript.segments, data.transcript_grouped?.groups);
  updateTranscriptFileLocation(data.transcript_files);
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
  return refreshProviders();
}

async function legacyRefreshSettings() {
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
if (el.apiKey) el.apiKey.addEventListener("blur", async () => {
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
if (el.saveKeyButton) el.saveKeyButton.addEventListener("click", async () => {
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
if (el.clearKeyButton) el.clearKeyButton.addEventListener("click", async () => {
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

function providerKindLabel(kind) {
  return kind === "volcengine" ? "火山" : "LLM";
}

function providerProtocolLabel(protocol) {
  return protocol === "anthropic" ? "Anthropic Messages" : "OpenAI 兼容";
}

function activeProvider(kind) {
  return (state.providers[kind] || []).find((item) => item.enabled);
}

function activeLlmModelLabel() {
  const provider = activeProvider("llm");
  return provider?.model || provider?.name || "LLM";
}

function renderProviderList() {
  const kind = state.providerKind;
  const items = state.providers[kind] || [];
  const packagedEmpty = state.providersPackaged && state.providerSettingsInitialized && !items.length;
  if (el.providerListTitle) el.providerListTitle.textContent = `${providerKindLabel(kind)} 配置`;
  if (el.providerListSummary) el.providerListSummary.textContent = items.length
    ? `已配置 ${items.length} 条，启用的配置将作为工作台默认供应商。`
    : (packagedEmpty ? "当前打包版尚未配置供应商，请新增一条。" : "还没有配置。");
  (el.providerEntries || []).forEach((button) => button.classList.toggle("active", button.dataset.providerKind === kind));
  if (!el.providerList) return;
  if (!items.length) {
    el.providerList.innerHTML = `<div class="provider-empty">${packagedEmpty ? `当前打包版尚未配置${providerKindLabel(kind)}，新增一条即可在工作台使用。` : `暂无${providerKindLabel(kind)}配置，新增一条即可在工作台使用。`}</div>`;
    return;
  }
  const modelLabel = kind === "llm" ? "模型" : "服务";
  el.providerList.innerHTML = `<div class="provider-table"><div class="provider-row provider-head"><span>名称</span><span>状态</span><span>${modelLabel}</span><span>操作</span></div>${items.map((item) => `<div class="provider-row"><span><strong>${escapeHtml(item.name)}</strong><small>${kind === "llm" ? escapeHtml(providerProtocolLabel(item.protocol)) : `Resource ID: ${escapeHtml(item.resource_id || "volc.seedasr.auc")}`}</small></span><span><span class="provider-status ${item.enabled ? "enabled" : "disabled"}">${item.enabled ? "已启用" : "已禁用"}</span></span><span>${escapeHtml(kind === "llm" ? item.model : "火山 BigModel ASR")}</span><span class="provider-actions"><button type="button" data-provider-action="edit" data-provider-id="${escapeHtml(item.id)}">编辑</button><button type="button" data-provider-action="toggle" data-provider-id="${escapeHtml(item.id)}" data-enabled="${item.enabled ? "false" : "true"}">${item.enabled ? "禁用" : "启用"}</button><button class="danger" type="button" data-provider-action="delete" data-provider-id="${escapeHtml(item.id)}">删除</button></span></div>`).join("")}</div>`;
  el.providerList.querySelectorAll("[data-provider-action]").forEach((button) => button.addEventListener("click", async () => {
    const item = items.find((candidate) => candidate.id === button.dataset.providerId);
    if (!item) return;
    const action = button.dataset.providerAction;
    if (action === "edit") {
      showProviderForm(item);
      return;
    }
    if (action === "delete" && !confirm(`删除“${item.name}”配置？`)) return;
    try {
      await api("/api/providers", { method: "POST", body: JSON.stringify({ kind, action, id: item.id, enabled: button.dataset.enabled === "true" }) });
      await refreshProviders();
      toast(action === "delete" ? "配置已删除。" : `配置已${item.enabled ? "禁用" : "启用"}。`);
    } catch (error) {
      toast(`操作失败：${error.message}`);
    }
  }));
}

function showProviderForm(item = null) {
  const kind = state.providerKind;
  if (!el.providerForm) return;
  const isLlm = kind === "llm";
  const nameInput = isLlm ? el.providerName : el.volcProviderName;
  const apiKeyInput = isLlm ? el.providerApiKey : el.volcProviderApiKey;
  el.providerForm.hidden = false;
  el.providerId.value = item?.id || "";
  el.providerKind.value = kind;
  el.providerFormTitle.textContent = item ? `编辑${providerKindLabel(kind)}配置` : `新增${providerKindLabel(kind)}配置`;
  nameInput.value = item?.name || (isLlm ? "" : "火山语音转写");
  apiKeyInput.value = "";
  apiKeyInput.placeholder = item?.has_api_key ? "已保存（留空不修改）" : "API Key";
  apiKeyInput.required = !item;
  el.providerName.required = isLlm;
  el.volcProviderName.required = !isLlm;
  el.llmProviderFields.hidden = !isLlm;
  el.volcProviderFields.hidden = isLlm;
  el.providerBaseUrl.value = item?.base_url || "";
  el.providerProtocol.value = item?.protocol || "openai";
  el.providerModel.value = item?.model || "";
  el.providerResourceId.value = item?.resource_id || "volc.seedasr.auc";
  el.providerTosAccessKey.value = "";
  el.providerTosAccessKey.placeholder = item?.has_tos_access_key ? "已保存（留空不修改）" : "Access Key ID";
  el.providerTosSecretKey.value = "";
  el.providerTosSecretKey.placeholder = item?.has_tos_secret ? "已保存（留空不修改）" : "Secret Access Key";
  el.providerTosBucket.value = item?.tos_bucket || "";
  el.providerTosEndpoint.value = item?.tos_endpoint || "";
  el.providerTosRegion.value = item?.tos_region || "";
  if (el.providerAudioUrl) el.providerAudioUrl.value = "";
  el.providerPollInterval.value = item?.poll_interval || 5;
  el.providerTosPrefix.value = item?.tos_prefix || "mp4-golden-asr";
  el.providerTosUrlExpires.value = item?.tos_url_expires || 86400;
  el.providerEnabled.checked = item ? Boolean(item.enabled) : true;
  nameInput.focus();
}

function hideProviderForm() {
  if (el.providerForm) el.providerForm.hidden = true;
}

async function refreshProviders() {
  const data = await api("/api/providers");
  state.providers = { llm: data.llm || [], volcengine: data.volcengine || [] };
  state.providersPackaged = Boolean(data.packaged);
  state.providerSettingsInitialized = data.settings_initialized !== false;
  const llm = activeProvider("llm");
  const volc = activeProvider("volcengine");
  if (el.workbenchLlmStatus) el.workbenchLlmStatus.textContent = llm ? `当前使用：${llm.name} · ${llm.model}` : "未启用 LLM 配置，请前往供应商管理添加。";
  if (el.workbenchVolcStatus) el.workbenchVolcStatus.textContent = volc ? `当前使用：${volc.name}` : "未启用火山配置，请前往供应商管理添加。";
  if (el.analyzeButton) el.analyzeButton.disabled = !llm;
  renderProviderList();
  return data;
}

el.providerEntries?.forEach((button) => button.addEventListener("click", () => {
  state.providerKind = button.dataset.providerKind;
  hideProviderForm();
  switchView("provider-list");
}));
el.addProviderButton?.addEventListener("click", () => showProviderForm());
el.cancelProviderButton?.addEventListener("click", hideProviderForm);
el.backToProvidersButton?.addEventListener("click", () => { hideProviderForm(); switchView("providers"); });
el.manageLlmButton?.addEventListener("click", () => { state.providerKind = "llm"; switchView("provider-list"); });
el.manageVolcengineButton?.addEventListener("click", () => { state.providerKind = "volcengine"; switchView("provider-list"); });
el.providerForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const kind = el.providerKind.value;
  const payload = {
    kind,
    action: "save",
    id: el.providerId.value,
    name: kind === "llm" ? el.providerName.value.trim() : el.volcProviderName.value.trim(),
    api_key: kind === "llm" ? el.providerApiKey.value.trim() : el.volcProviderApiKey.value.trim(),
    enabled: el.providerEnabled.checked,
    protocol: el.providerProtocol.value,
    base_url: el.providerBaseUrl.value.trim(),
    model: el.providerModel.value.trim(),
    resource_id: el.providerResourceId.value.trim(),
    tos_access_key: el.providerTosAccessKey.value.trim(),
    tos_secret_key: el.providerTosSecretKey.value.trim(),
    tos_bucket: el.providerTosBucket.value.trim(),
    tos_endpoint: el.providerTosEndpoint.value.trim(),
    tos_region: el.providerTosRegion.value.trim(),
    poll_interval: Number(el.providerPollInterval.value || 5),
    tos_prefix: el.providerTosPrefix.value.trim(),
    tos_url_expires: Number(el.providerTosUrlExpires.value || 86400),
  };
  try {
    await api("/api/providers", { method: "POST", body: JSON.stringify(payload) });
    hideProviderForm();
    await refreshProviders();
    toast("供应商配置已保存。");
  } catch (error) {
    toast(`保存失败：${error.message}`);
  }
});

async function refreshLibraryLegacy() {
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
  if ((state.draftTabs || []).includes(jobId)) {
    if (state.activeDraftId && state.activeDraftId !== jobId) cacheActiveDraftMedia();
    state.activeDraftId = jobId;
    resetCurrentVideoView({ keepTabs: true, keepLocalMedia: true, silent: true });
    restoreDraftMedia(jobId);
    renderWorkbenchTabs();
    setStatus("新建任务：等待输入视频");
    return;
  }
  if (state.activeDraftId) {
    cacheActiveDraftMedia();
    state.localFile = null;
    state.localUrl = null;
    state.activeDraftId = null;
  }
  const data = await api(`/api/job/load?job_id=${encodeURIComponent(jobId)}`);
  ensureJobTab(jobId, { title: data.metadata?.title || jobId });
  state.jobId = jobId;
  state.activeDraftId = null;
  state.activeJobId = jobId;
  state.activeClipId = null;
  state.renderProgress = {};
  state.analyzeTaskId = null;
  el.pauseButton.disabled = true;
  el.stopButton.disabled = true;
  el.pauseButton.textContent = "暂停";
  if (el.previewStatus) el.previewStatus.hidden = true;
  renderWorkbenchTabs();
  updateMetadata(data.metadata);
  updateTranscript(data.transcript.segments, data.transcript_grouped?.groups);
  updateTranscriptFileLocation(data.transcript_files);
  state.highlights = data.highlights || { clips: [] };
  el.sourceVideo.src = `/media/${jobId}/${data.metadata.browser_preview_file || data.metadata.original_file || "source.mp4"}`;
  if (data.metadata.browser_preview_file) {
    updatePreviewStatus({ stage: "preview_ready", message: "\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8\u5df2\u751f\u6210", preview_progress: 1, preview_remaining: 0, metadata: data.metadata });
  }
  const savedRange = data.metadata?.transcription_range;
  const hasSavedRange = Number(savedRange?.end || 0) > Number(savedRange?.start || 0);
  el.transcribeButton.disabled = !hasSavedRange || data.metadata?.has_audio === false;
  setPreviewButtonsDisabled(!needsBrowserPreview(data.metadata));
  renderClips();
  if (!state.activeClipId) {
    showManualTrimPanel(hasSavedRange ? savedRange.start : 0, hasSavedRange ? savedRange.end : null);
  }
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
    if (job.analyze_task_id) {
      const taskData = await api(`/api/clips/render-status?task_id=${encodeURIComponent(job.analyze_task_id)}`);
      if (["queued", "running", "paused"].includes(taskData.task?.status)) {
        state.analyzeTaskId = job.analyze_task_id;
        setAnalyzeControls(taskData.task);
      }
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
  updateTranscript(loaded.transcript.segments, loaded.transcript_grouped?.groups);
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
    if (job.browser_preview_url || job.preview_stage === "preview_ready" || job.stage === "preview_ready") {
      applyBrowserPreviewIfReady(job);
      const transcribeRunning = el.transcribeButton.disabled && !el.stopButton.disabled;
      if (!transcribeRunning && state.pollTimer) clearInterval(state.pollTimer);
    }
    if (job.preview_stage === "preview_error" || job.stage === "preview_error") {
      setPreviewButtonsDisabled(false);
      if (job.stage === "preview_error" && state.pollTimer) clearInterval(state.pollTimer);
    }
    if (job.transcript_tail) {
      mergeTranscriptSegments(job.transcript_tail);
    } else if (job.latest_segment) {
      mergeTranscriptSegments([job.latest_segment]);
    }
    await refreshFullTranscriptIfBehind(job);
    if (["transcribed", "stopped", "error"].includes(job.stage)) {
      const loaded = await api(`/api/job/load?job_id=${encodeURIComponent(state.jobId)}`);
      updateTranscript(loaded.transcript.segments, loaded.transcript_grouped?.groups);
      updateTranscriptFileLocation(loaded.transcript_files);
      if (job.stage !== "error") el.analyzeButton.disabled = loaded.transcript.segments.length === 0 || !activeProvider("llm");
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
  // Keep existing task tabs open. A file selected from a task creates a fresh draft tab first.
  if (state.jobId || !state.activeDraftId) createDraftTask();
  else if (state.localFile) {
    releaseDraftMedia(state.activeDraftId);
    resetCurrentVideoView({ keepTabs: true, silent: true });
  }
  if (state.activeDraftId) {
    state.jobMeta[state.activeDraftId] = { ...(state.jobMeta[state.activeDraftId] || {}), title: file.name, isDraft: true };
    renderWorkbenchTabs();
    refreshTasks().catch(() => {});
  }
  state.localFile = file;
  if (state.localUrl) URL.revokeObjectURL(state.localUrl);
  state.localUrl = URL.createObjectURL(file);
  el.sourceVideo.src = state.localUrl;
  el.transcribeButton.disabled = true;
  setPreviewButtonsDisabled(false);
  el.metadata.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB · 已在浏览器载入，可先预览。`;
  showManualTrimPanel(0);
  cacheActiveDraftMedia();
  toast("视频已载入，请先在轨道上选定转写范围并保存。");
});

el.uploadButton?.addEventListener("click", async () => {
  if (!state.localFile) return;
  const form = new FormData();
  form.append("file", state.localFile);
  toast("正在上传到本地服务...");
  const data = await api("/api/video/upload", { method: "POST", body: form });
  const uploadedDraftId = state.activeDraftId;
  const uploadedFileName = state.localFile?.name || "视频";
  state.jobId = data.job_id;
  ensureJobTab(data.job_id, { title: data.metadata?.title || uploadedFileName });
  state.activeJobId = data.job_id;
  await refreshTasks();
  switchView("workbench");
  updateMetadata(data.metadata);
  el.sourceVideo.src = data.preview_url;
  if (uploadedDraftId) {
    state.draftTabs = (state.draftTabs || []).filter((id) => id !== uploadedDraftId);
    delete state.jobMeta[uploadedDraftId];
    releaseDraftMedia(uploadedDraftId);
    state.activeDraftId = null;
  }
  el.transcribeButton.disabled = false;
  const canMakePreview = needsBrowserPreview(data.metadata);
  setPreviewButtonsDisabled(data.browser_preview_queued || !canMakePreview);
  el.uploadButton.disabled = true;
  showManualTrimPanel(0);
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
    await uploadCurrentVideo();
    const payload = { job_id: state.jobId, transcribe_engine: "volcengine_bigmodel" };
    await api("/api/transcribe/start", { method: "POST", body: JSON.stringify(payload) });
    ensureJobTab(state.jobId, { title: state.metadata?.title || state.localFile?.name || state.jobId, statusClass: "done" });
    await refreshLibrary();
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
  if (!state.jobId || state.transcribeControlPending) return;
  const isPause = el.pauseButton.textContent === "暂停";
  state.transcribeControlPending = true;
  el.pauseButton.disabled = true;
  el.stopButton.disabled = true;
  try {
    const data = await api("/api/transcribe/control", { method: "POST", body: JSON.stringify({ job_id: state.jobId, action: isPause ? "pause" : "resume" }) });
    el.pauseButton.textContent = isPause ? "继续" : "暂停";
    toast(data.job?.message || (isPause ? "转写已暂停，后续请求已拦截。" : "转写已继续。"));
    await refreshJobStatus();
  } catch (err) {
    toast(`更新转写状态失败：${err.message}`);
  } finally {
    state.transcribeControlPending = false;
    el.pauseButton.disabled = false;
    el.stopButton.disabled = false;
  }
});

el.stopButton.addEventListener("click", async () => {
  if (!state.jobId || state.transcribeControlPending) return;
  state.transcribeControlPending = true;
  el.pauseButton.disabled = true;
  el.stopButton.disabled = true;
  try {
    const data = await api("/api/transcribe/control", { method: "POST", body: JSON.stringify({ job_id: state.jobId, action: "stop" }) });
    toast(data.job?.message || "转写已结束，正在保存已产生的文字稿。");
    await refreshJobStatus();
  } catch (err) {
    state.transcribeControlPending = false;
    el.pauseButton.disabled = false;
    el.stopButton.disabled = false;
    toast(`结束转写失败：${err.message}`);
  }
});

async function pollAnalyzeTask(taskId) {
  while (true) {
    const data = await api(`/api/clips/render-status?task_id=${encodeURIComponent(taskId)}`);
    const task = data.task;
    state.analyzeTaskId = taskId;
    setAnalyzeControls(task);
    await refreshTasks();
    const percent = task.percent ?? Math.round((task.progress || 0) * 100);
    const elapsed = task.elapsed || 0;
    let message = task.message || `${activeLlmModelLabel()} \u5206\u6790\u4e2d`;
    if (task.status === "running" && elapsed > 330) {
      message = `${message}\uff08\u5904\u7406\u65f6\u95f4\u5df2\u8d85\u8fc7 5 \u5206\u949f\uff0c\u4ecd\u5728\u7b49\u5f85\u6a21\u578b\u8fd4\u56de\uff09`;
    }
    el.analyzeStatus.textContent = `${message} \u00b7 \u8fdb\u5ea6 ${percent}% \u00b7 \u5df2\u7528 ${formatShortTime(elapsed)}`;
    if (task.status === "done") {
      state.highlights = task.highlights || { clips: [] };
      renderClips();
      await refreshSettings();
      const count = (state.highlights.clips || []).length;
      el.analyzeStatus.textContent = `\u5206\u6790\u5b8c\u6210\uff0c\u627e\u5230 ${count} \u4e2a\u5019\u9009\u7247\u6bb5`;
      toast(`\u5206\u6790\u5b8c\u6210\uff0c\u627e\u5230 ${count} \u4e2a\u5019\u9009\u7247\u6bb5\u3002`);
      state.analyzeTaskId = null;
      setAnalyzeControls(null);
      return true;
    }
    if (["error", "cancelled"].includes(task.status)) {
      el.analyzeStatus.textContent = `\u5206\u6790\u5931\u8d25\uff1a${task.message || "\u672a\u77e5\u9519\u8bef"}`;
      toast(`\u5206\u6790\u5931\u8d25\uff1a${task.message || "\u672a\u77e5\u9519\u8bef"}`);
      state.analyzeTaskId = null;
      setAnalyzeControls(null);
      return false;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

el.analyzeButton.addEventListener("click", async () => {
  el.analyzeButton.disabled = true;
  const modelLabel = activeLlmModelLabel();
  el.analyzeStatus.textContent = `\u6b63\u5728\u63d0\u4ea4 ${modelLabel} \u5206\u6790\u4efb\u52a1...`;
  try {
    const data = await api("/api/highlights/analyze", {
      method: "POST",
      body: JSON.stringify({
        job_id: state.jobId,
        target_clip_count: Number(el.clipCount.value),
        min_seconds: Number(el.minSeconds.value),
        max_seconds: Number(el.maxSeconds.value),
      }),
    });
    state.analyzeTaskId = data.task.task_id;
    setAnalyzeControls(data.task);
    await refreshTasks();
    el.analyzeStatus.textContent = `\u5df2\u53d1\u9001\u7ed9 ${modelLabel}\uff0c\u901a\u5e38\u9700\u8981\u7b49\u5f85 4-5 \u5206\u949f\uff0c\u8fdb\u5ea6\u4f1a\u5728\u8fd9\u91cc\u548c\u4efb\u52a1\u4e2d\u5fc3\u540c\u6b65\u663e\u793a\u3002`;
    await pollAnalyzeTask(data.task.task_id);
  } catch (err) {
    el.analyzeStatus.textContent = `\u5206\u6790\u5931\u8d25\uff1a${err.message}`;
    toast(`\u5206\u6790\u5931\u8d25\uff1a${err.message}`);
  } finally {
    el.analyzeButton.disabled = false;
    if (!state.analyzeTaskId) setAnalyzeControls(null);
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

async function pollExportTask(taskId, targetLabel, options = {}) {
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
      if (options.openExportedClip && exported.length === 1 && exported[0]?.id) {
        try {
          const opened = await api("/api/dialog/open-path", { method: "POST", body: JSON.stringify({ job_id: state.jobId, clip_id: exported[0].id }) });
          toast(`\u5df2\u5bfc\u51fa ${exported.length} \u6761\uff0c\u5df2\u81ea\u52a8\u6253\u5f00\u6587\u4ef6\u5939\uff1a${opened.folder}`);
        } catch (err) {
          toast(`\u5df2\u5bfc\u51fa ${exported.length} \u6761\uff0c\u4f46\u6253\u5f00\u6587\u4ef6\u5939\u5931\u8d25\uff1a${err.message}`);
        }
        return true;
      }
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
  const targetLabel = exportDir || "本视频的结果文件夹";
  toast(`已提交原画质导出任务：${targetLabel}`);
  el.exportButton.disabled = true;
  try {
    const data = await api("/api/clips/export", { method: "POST", body: JSON.stringify({ job_id: state.jobId, clip_ids: clipIds || [], export_dir: exportDir }) });
    const task = data.task;
    await refreshTasks();
    el.analyzeStatus.textContent = `导出任务已加入队列 · ${targetLabel}`;
    await pollExportTask(task.task_id, targetLabel, options);
  } finally {
    el.exportButton.disabled = !state.highlights.clips.some((c) => c.confirmed);
  }
}

async function exportSingleClip(clipId) {
  const clip = findClip(clipId);
  if (!clip) return;
  await exportClips([clipId], { openExportedClip: true });
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
    toast(`已复制分组文字稿，共 ${state.transcript.groups.length} 组。`);
  });
}

if (el.openTranscriptFolderButton) {
  el.openTranscriptFolderButton.addEventListener("click", async () => {
    if (!state.jobId) {
      toast("请先上传或载入一个任务。");
      return;
    }
    try {
      const data = await api("/api/dialog/open-path", { method: "POST", body: JSON.stringify({ job_id: state.jobId }) });
      toast(`已打开本视频的结果文件夹：${data.folder}`);
    } catch (err) {
      toast(`打开文字稿位置失败：${err.message}`);
    }
  });
}

if (el.saveTranscriptAsButton) {
  el.saveTranscriptAsButton.addEventListener("click", async () => {
    if (!state.jobId) {
      toast("请先上传或载入一个任务。");
      return;
    }
    try {
      const data = await api("/api/dialog/save-transcript", { method: "POST", body: JSON.stringify({ job_id: state.jobId }) });
      toast(data.saved ? `文字稿已保存：${data.path}` : "已取消另存文字稿。");
    } catch (err) {
      toast(`另存文字稿失败：${err.message}`);
    }
  });
}

async function controlAnalyzeTask(action) {
  if (!state.analyzeTaskId) return;
  const data = await api("/api/tasks/control", { method: "POST", body: JSON.stringify({ task_id: state.analyzeTaskId, action }) });
  setAnalyzeControls(data.task);
  el.analyzeStatus.textContent = data.task.message || "DeepSeek 分析状态已更新";
}

if (el.pauseAnalyzeButton) {
  el.pauseAnalyzeButton.addEventListener("click", async () => {
    try {
      const action = el.pauseAnalyzeButton.textContent === "继续分析" ? "resume" : "pause";
      await controlAnalyzeTask(action);
    } catch (err) {
      toast(`更新分析状态失败：${err.message}`);
    }
  });
}

if (el.stopAnalyzeButton) {
  el.stopAnalyzeButton.addEventListener("click", async () => {
    if (!confirm("结束本次 DeepSeek 分析？正在等待的结果不会被保存。")) return;
    try {
      await controlAnalyzeTask("stop");
      el.stopAnalyzeButton.disabled = true;
    } catch (err) {
      toast(`结束分析失败：${err.message}`);
    }
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
  renderTrimTimeline();
});
el.sourceVideo.addEventListener("loadedmetadata", () => { renderTrimTimeline(); captureTimelineFrames().catch(() => {}); });
el.modalClipVideo?.addEventListener("timeupdate", () => {
  if (!state.modalTrim) return;
  state.modalTrim.current = el.modalClipVideo.currentTime || 0;
  renderModalTimeline();
});
el.modalClipVideo?.addEventListener("loadedmetadata", () => { if (state.modalTrim) { el.modalClipVideo.currentTime = state.modalTrim.current; renderModalTimeline(); } });
bindTimelineDrag(el.trimTimeline, "main");
bindTimelineDrag(el.modalTrimTimeline, "modal");
el.closeClipPreviewButton?.addEventListener("click", closeClipPreview);
el.clipPreviewModal?.addEventListener("click", (event) => { if (event.target === el.clipPreviewModal) closeClipPreview(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !el.clipPreviewModal?.hidden) closeClipPreview(); });
el.modalTrimStartInput?.addEventListener("change", () => { if (!state.modalTrim) return; state.modalTrim.start = Math.max(0, Math.min(parseClock(el.modalTrimStartInput.value), state.modalTrim.end - 1 / 30)); renderModalTimeline(); });
el.modalTrimEndInput?.addEventListener("change", () => { if (!state.modalTrim) return; state.modalTrim.end = Math.max(state.modalTrim.start + 1 / 30, parseClock(el.modalTrimEndInput.value)); renderModalTimeline(); });
el.modalSetStartButton?.addEventListener("click", () => { if (state.modalTrim) { state.modalTrim.start = Math.min(state.modalTrim.current, state.modalTrim.end - 1 / 30); renderModalTimeline(); } });
el.modalSetEndButton?.addEventListener("click", () => { if (state.modalTrim) { state.modalTrim.end = Math.max(state.modalTrim.current, state.modalTrim.start + 1 / 30); renderModalTimeline(); } });
el.modalSaveTrimButton?.addEventListener("click", async () => { if (!state.modalClipId || !state.modalTrim) return; await updateClipTime(state.modalClipId, state.modalTrim.start, state.modalTrim.end); const clip = findClip(state.modalClipId); if (clip) renderAnalysisDetails(clip, state.highlights.clips.findIndex((item) => item.id === clip.id)); toast("片段时间已保存，可继续预览或导出。"); });

if (el.setStartFromCurrent) {
  el.setStartFromCurrent.addEventListener("click", () => setTrimValue("start", el.sourceVideo.currentTime || 0, true));
  el.setEndFromCurrent.addEventListener("click", () => setTrimValue("end", el.sourceVideo.currentTime || 0, true));
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
  el.saveTrimButton.addEventListener("click", async () => {
    if (state.trimSavePromise) return;
    el.saveTrimButton.disabled = true;
    try {
      await saveActiveTrim();
    } catch (err) {
      el.analyzeStatus.textContent = `保存剪切失败：${err.message}`;
      toast(`保存剪切失败：${err.message}`);
    } finally {
      el.saveTrimButton.disabled = false;
    }
  });
  el.renderActivePreviewButton?.addEventListener("click", async () => {
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

if (el.clearLibraryButton) {
  el.clearLibraryButton.addEventListener("click", async () => {
    if (!confirm("\u786e\u5b9a\u6e05\u7a7a\u5168\u90e8\u5386\u53f2\u8bb0\u5f55\u5417\uff1f\u6240\u6709\u4efb\u52a1\u7684\u4e0a\u4f20\u89c6\u9891\u3001\u8f6c\u5199\u7ed3\u679c\u3001\u5019\u9009\u7247\u6bb5\u548c\u5bfc\u51fa\u8bb0\u5f55\u90fd\u4f1a\u88ab\u6c38\u4e45\u5220\u9664\uff01")) return;
    el.clearLibraryButton.disabled = true;
    try {
      const data = await api("/api/library/clear-all", { method: "POST", body: JSON.stringify({}) });
      resetCurrentVideoView();
      await refreshLibrary();
      await refreshTasks();
      await refreshStorage();
      toast(`\u5386\u53f2\u8bb0\u5f55\u5df2\u5168\u90e8\u6e05\u7a7a\uff08\u5220\u9664 ${data.removed || 0} \u4e2a\u4efb\u52a1\uff09\u3002`);
    } catch (err) {
      toast(`\u6e05\u7a7a\u5931\u8d25\uff1a${err.message}`);
    } finally {
      el.clearLibraryButton.disabled = false;
    }
  });
}
el.previewButton.addEventListener("click", requestBrowserPreview);
el.previewTopButton?.addEventListener("click", requestBrowserPreview);
if (el.refreshStorageButton) el.refreshStorageButton.addEventListener("click", refreshStorage);
if (el.refreshTasksButton) el.refreshTasksButton.addEventListener("click", refreshTasks);
if (el.refreshHealthButton) el.refreshHealthButton.addEventListener("click", refreshHealth);
if (el.clearFinishedTasksButton) el.clearFinishedTasksButton.addEventListener("click", clearFinishedTasks);
if (el.cleanBrowserPreviewButton) el.cleanBrowserPreviewButton.addEventListener("click", () => cleanupStorage(["browser_preview"]));
if (el.cleanClipPreviewButton) el.cleanClipPreviewButton.addEventListener("click", () => cleanupStorage(["clip_previews"]));
if (el.cleanAudioCacheButton) el.cleanAudioCacheButton.addEventListener("click", () => cleanupStorage(["audio"]));
if (el.cleanWorkspaceCacheButton) el.cleanWorkspaceCacheButton.addEventListener("click", () => cleanupStorage(["workspace_cache"]));
if (el.newTaskButton) el.newTaskButton.addEventListener("click", createDraftTask);
if (el.resetTranscriptButton) el.resetTranscriptButton.addEventListener("click", reloadTranscript);
if (el.clearTranscriptViewButton) el.clearTranscriptViewButton.addEventListener("click", () => { updateTranscript([]); toast("文字稿显示已清空，可点重新载入恢复。"); });
if (el.clearClipsButton) el.clearClipsButton.addEventListener("click", clearAllClips);
if (el.resetAnalyzeButton) el.resetAnalyzeButton.addEventListener("click", resetAnalyzeControls);
if (el.clearExportDirectoryButton) el.clearExportDirectoryButton.addEventListener("click", () => { el.exportDirectory.value = ""; toast("导出目录已清空，将保存到本视频的结果文件夹。"); });
if (el.trendSearchButton) el.trendSearchButton.addEventListener("click", runTrendSearch);
if (el.trendOpenChromeButton) el.trendOpenChromeButton.addEventListener("click", openTrendChrome);
if (el.trendDateRange) el.trendDateRange.addEventListener("change", () => {
  if (el.trendCustomDates) el.trendCustomDates.hidden = el.trendDateRange.value !== "custom";
});
if (el.trendKeywords) el.trendKeywords.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    runTrendSearch();
  }
});
if (el.trendKeywords) el.trendKeywords.addEventListener("input", () => {
  if (!el.trendKeywords.value.trim()) clearTrendSearchResults();
});

el.sourceVideo.addEventListener("error", async () => {
  if (!state.jobId) return;
  updatePreviewStatus({ stage: "previewing", message: "\u5f53\u524d\u89c6\u9891\u7f16\u7801\u6d4f\u89c8\u5668\u65e0\u6cd5\u76f4\u63a5\u9884\u89c8\uff0c\u6b63\u5728\u751f\u6210\u517c\u5bb9\u9884\u89c8 MP4", preview_progress: 0, preview_elapsed: 0, preview_remaining: null });
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

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

function renderTaskRow(task) {
  const meta = state.jobMeta[task.job_id] || {};
  const isWorkspace = Boolean(task.virtual);
  const percent = task.percent ?? Math.round((task.progress || 0) * 100);
  const elapsed = formatShortTime(task.elapsed || 0);
  const canCancel = ["queued", "running"].includes(task.status);
  const canRetry = ["error", "cancelled"].includes(task.status);
  const row = document.createElement("div");
  row.className = `task-item ${taskStatusClass(task.status)}`;
  row.innerHTML = `
    <div class="task-item-top"><strong>${escapeHtml(task.title || meta.title || task.job_id || "未知视频")} · ${escapeHtml(taskTypeText(task.type))}</strong><span>${escapeHtml(taskStatusText(task.status))}${isWorkspace ? "" : ` · ${percent}%`}</span></div>
    ${isWorkspace ? "" : `<div class="progress-bar"><span style="width:${Math.max(0, Math.min(100, percent))}%"></span></div>`}
    <div class="task-item-bottom"><span>${escapeHtml(task.message || "等待任务状态")}${isWorkspace ? "" : ` · 已用 ${elapsed}`}</span><span class="task-item-actions"><button data-action="open-task" type="button">${task.type === "draft" ? "继续填写" : "查看工作台"}</button>${canRetry ? `<button data-task-id="${encodeURIComponent(task.task_id || "")}" data-action="retry-task" type="button">重试</button>` : ""}${canCancel ? `<button data-task-id="${encodeURIComponent(task.task_id || "")}" data-action="cancel-task" type="button">取消</button>` : ""}</span></div>`;
  row.querySelector("[data-action='open-task']")?.addEventListener("click", () => {
    ensureJobTab(task.job_id, { title: meta.title || task.job_id });
    switchView("workbench");
    loadJob(task.job_id);
  });
  row.querySelector("[data-action='retry-task']")?.addEventListener("click", async (event) => { await retryTask(decodeURIComponent(event.currentTarget.dataset.taskId)); });
  row.querySelector("[data-action='cancel-task']")?.addEventListener("click", async (event) => { await cancelRender(decodeURIComponent(event.currentTarget.dataset.taskId)); await refreshTasks(); });
  return row;
}

async function refreshTasks() {
  if (!el.taskList || !el.taskSummary) return;
  const data = await api("/api/tasks?limit=100");
  const backgroundTasks = data.tasks || [];
  (data.jobs || []).forEach((job) => {
    if (job?.job_id) state.jobMeta[job.job_id] = { ...(state.jobMeta[job.job_id] || {}), title: job.title || job.job_id };
  });
  const tasks = [...draftTaskEntries(), ...waitingWorkspaceEntries(data.jobs, backgroundTasks), ...backgroundTasks];
  const active = tasks.filter((task) => ["draft", "waiting", "queued", "running", "paused"].includes(task.status));
  syncCompletedTasks(backgroundTasks);
  if (el.activeTaskCount) { el.activeTaskCount.textContent = String(active.length); el.activeTaskCount.hidden = active.length === 0; }
  const filtered = state.taskFilter === "completed" ? tasks.filter((task) => ["done", "error", "cancelled"].includes(task.status)) : active;
  el.taskSummary.textContent = `${filtered.length} 个${state.taskFilter === "completed" ? "已完成" : "进行中"}任务 · 共 ${tasks.length} 个`;
  el.taskList.innerHTML = "";
  el.taskList.className = filtered.length ? "task-list" : "task-list task-list-empty";
  if (!filtered.length) { el.taskList.textContent = state.taskFilter === "completed" ? "暂无已完成任务。" : "当前没有进行中的任务。"; return; }
  filtered.forEach((task) => { el.taskList.appendChild(renderTaskRow(task)); });
}

async function refreshLibrary() {
  const data = await api("/api/library");
  state.libraryItems = data.items || [];
  if (!el.library) return state.libraryItems;
  el.library.innerHTML = "";
  if (!state.libraryItems.length) { el.library.textContent = "还没有结果记录。"; return state.libraryItems; }
  state.libraryItems.forEach((item) => {
    state.jobMeta[item.job_id] = { ...(state.jobMeta[item.job_id] || {}), title: item.title, statusClass: item.status === "done" ? "done" : "" };
    const row = document.createElement("div");
    row.className = "library-item storage-result-item";
    row.innerHTML = `<div><strong>${escapeHtml(item.title)}</strong><div class="small">${escapeHtml(item.created_at || "")} · ${formatClock(item.duration || 0)} · 候选 ${item.clip_count} · 已确认 ${item.confirmed_count} · 已导出 ${item.exported_count}</div><div class="small storage-path">结果文件夹：${escapeHtml(item.output_path || `outputs\\${item.output_folder || item.title || item.job_id}`)}</div></div><div class="library-actions"><button data-action="load" type="button">载入工作台</button><button data-action="open" type="button">打开文件夹</button><button data-action="delete" class="danger" type="button">删除存储</button></div>`;
    row.querySelector("[data-action='load']")?.addEventListener("click", () => { ensureJobTab(item.job_id, item); switchView("workbench"); loadJob(item.job_id); });
    row.querySelector("[data-action='open']")?.addEventListener("click", async () => { try { const result = await api("/api/dialog/open-path", { method: "POST", body: JSON.stringify({ job_id: item.job_id }) }); toast(`已打开结果文件夹：${result.folder}`); } catch (err) { toast(`打开文件夹失败：${err.message}`); } });
    row.querySelector("[data-action='delete']")?.addEventListener("click", () => deleteLibraryItem(item));
    el.library.appendChild(row);
  });
  renderWorkbenchTabs();
  return state.libraryItems;
}

async function deleteLibraryItem(item) {
  if (!item?.job_id) return;
  const message = `删除“${item.title}”的项目存储？\n\n这会删除项目内的原视频、文字稿、候选片段和导出文件；你手动选择到其他目录的导出文件不会被删除。`;
  if (!confirm(message)) return;
  try {
    await api("/api/library/delete", { method: "POST", body: JSON.stringify({ job_id: item.job_id }) });
    const wasActive = state.jobId === item.job_id;
    state.openJobIds = state.openJobIds.filter((id) => id !== item.job_id);
    delete state.jobMeta[item.job_id];
    if (wasActive) {
      const next = [...state.openJobIds, ...(state.draftTabs || [])].slice(-1)[0];
      if (next) await loadJob(next);
      else { state.activeDraftId = null; resetCurrentVideoView({ keepTabs: true, silent: true }); }
    }
    renderWorkbenchTabs();
    await refreshTasks();
    await refreshStorage();
    await refreshLibrary();
    toast(`已删除存储：${item.title}`);
  } catch (err) {
    toast(`删除存储失败：${err.message}`);
  }
}

el.navItems?.forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
el.taskFilterActive?.addEventListener("click", () => { state.taskFilter = "active"; el.taskFilterActive.classList.add("active"); el.taskFilterCompleted.classList.remove("active"); refreshTasks(); });
el.taskFilterCompleted?.addEventListener("click", () => { state.taskFilter = "completed"; el.taskFilterCompleted.classList.add("active"); el.taskFilterActive.classList.remove("active"); refreshTasks(); });

async function boot() {
  const today = localDateInputValue(new Date());
  if (el.trendEndDate && !el.trendEndDate.value) el.trendEndDate.value = today;
  if (el.trendStartDate && !el.trendStartDate.value) {
    const start = new Date();
    start.setDate(start.getDate() - 7);
    el.trendStartDate.value = localDateInputValue(start);
  }
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
