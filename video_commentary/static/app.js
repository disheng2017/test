const state = {
  currentProjectId: null,
  currentProject: null,
  projects: [],
  status: {},
  pollTimer: null,
  gpuTimer: null,
  progressDisplay: {},
  debugEntries: [],
};

const views = document.querySelectorAll(".view");
const navButtons = document.querySelectorAll(".steps button");
const toast = document.querySelector("#toast");

navButtons.forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

document.querySelector("#createForm").addEventListener("submit", createProject);
document.querySelector("#analyzeBtn").addEventListener("click", analyzeProject);
document.querySelector("#saveTranscriptBtn").addEventListener("click", saveTranscript);
document.querySelector("#generateScriptBtn").addEventListener("click", generateScript);
document.querySelector("#saveScriptBtn").addEventListener("click", saveScript);
document.querySelector("#generateVoiceBtn").addEventListener("click", generateVoice);
document.querySelector("#renderBtn").addEventListener("click", renderVideo);
document.querySelector("#saveCalibrationBtn")?.addEventListener("click", saveCalibration);
document.querySelector("#testLlmBtn").addEventListener("click", testLlm);
document.querySelector("#testTtsBtn").addEventListener("click", testTts);
document.querySelector("#previewVoiceBtn")?.addEventListener("click", previewVoice);
document.querySelector("#ttsVoice")?.addEventListener("change", () => renderVoiceCards(document.querySelector("#ttsVoice").value));
document.querySelector("#narrationRatio").addEventListener("input", updateRatioLabel);
document.querySelector("#llmProvider")?.addEventListener("change", applyLlmPreset);
document.querySelector("#cloneVoiceForm")?.addEventListener("submit", cloneVoice);
document.querySelector("#clearDebugBtn")?.addEventListener("click", clearDebugLog);
document.querySelectorAll("[data-perspective]").forEach((button) => {
  button.addEventListener("click", () => setPerspective(button.dataset.perspective));
});

init();

async function init() {
  updateRatioLabel();
  await loadStatus();
  await loadProjects();
  startGpuPolling();
}

async function loadStatus() {
  const response = await fetch("/api/status");
  state.status = await response.json();
  const el = document.querySelector("#transcribeStatus");
  if (el) {
    const local = state.status.faster_whisper_installed ? "本地 Whisper 可用" : "本地 Whisper 未安装";
    const model = state.status.transcribe_model || state.status.whisper_model || "";
    el.textContent = `字幕识别：${state.status.transcribe_provider || "auto"} · ${model} · ${local}`;
  }
}

function llmPresets() {
  return state.status.llm_presets || [
    {
      id: "minimax-m2-7",
      label: "MiniMax 2.7",
      base_url: "https://api.minimaxi.com/v1",
      model: "MiniMax-M2.7",
    },
    {
      id: "xiaomi-mimo",
      label: "小米 MiMo",
      base_url: "https://token-plan-cn.xiaomimimo.com/v1",
      model: "mimo-v2.5-pro",
    },
    { id: "custom", label: "自定义", base_url: "", model: "" },
  ];
}

function applyLlmPreset() {
  const provider = document.querySelector("#llmProvider")?.value || "custom";
  const preset = llmPresets().find((item) => item.id === provider);
  if (!preset || provider === "custom") return;
  document.querySelector("#llmBaseUrl").value = preset.base_url;
  document.querySelector("#llmModel").value = preset.model;
}

function syncLlmProvider(project) {
  const select = document.querySelector("#llmProvider");
  if (!select) return;
  const baseUrl = project.llm_base_url || state.status.llm_base_url || "";
  const model = project.llm_model || state.status.llm_model || "";
  const matched = llmPresets().find((item) => item.base_url === baseUrl && item.model === model);
  select.value = project.llm_provider || matched?.id || "custom";
}

function setPerspective(value, updateProjectNow = true) {
  const selected = value === "first" ? "first" : "third";
  document.querySelectorAll("[data-perspective]").forEach((button) => {
    button.classList.toggle("active", button.dataset.perspective === selected);
  });
  if (updateProjectNow && state.currentProjectId) {
    updateProject(state.currentProjectId, { narrative_perspective: selected }, true);
  }
}

function showView(id) {
  if (!canOpenView(id)) return;
  views.forEach((view) => view.classList.toggle("active", view.id === id));
  navButtons.forEach((button) => button.classList.toggle("active", button.dataset.view === id));
  if (state.currentProject) renderProject(state.currentProject);
}

async function createProject(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector("#createMessage");
  message.textContent = "正在创建项目...";
  try {
    const response = await fetch("/api/projects", { method: "POST", body: new FormData(form) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || data.message || "创建失败");
    state.currentProjectId = data.id;
    state.currentProject = data;
    message.textContent = "项目已创建";
    await loadProjects();
    showView("material");
  } catch (error) {
    message.textContent = error.message;
  }
}

async function loadProjects() {
  const response = await fetch("/api/projects");
  state.projects = await response.json();
  const list = document.querySelector("#projectList");
  list.innerHTML = "";
  if (!state.projects.length) {
    list.innerHTML = `<div class="empty">暂无项目</div>`;
    return;
  }
  for (const project of state.projects) {
    const item = document.createElement("article");
    item.className = "project-item";
    item.innerHTML = `
      <div class="project-title"><strong>${escapeHtml(project.name)}</strong><span>${escapeHtml(project.stage)} · ${escapeHtml(project.status)}</span></div>
      <div class="project-actions">
        <button class="ghost small" data-action="open">打开</button>
        <button class="ghost small" data-action="rename">重命名</button>
        <button class="ghost small danger" data-action="delete">删除</button>
      </div>
    `;
    item.querySelector('[data-action="open"]').addEventListener("click", async () => {
      state.currentProjectId = project.id;
      await refreshCurrentProject();
      showView("material");
    });
    item.querySelector('[data-action="rename"]').addEventListener("click", async () => {
      const name = prompt("项目名称", project.name);
      if (!name) return;
      await updateProject(project.id, { name });
    });
    item.querySelector('[data-action="delete"]').addEventListener("click", async () => {
      if (!confirm(`删除项目“${project.name}”？该操作会删除项目文件。`)) return;
      await deleteProject(project.id);
    });
    list.appendChild(item);
  }
}

async function updateProject(id, payload, silent = false) {
  const response = await fetch(`/api/projects/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) return notify(data.error || data.message || "更新失败");
  if (state.currentProjectId === id) {
    state.currentProject = data;
    renderProject(data);
  }
  await loadProjects();
  if (!silent) notify("项目已更新");
}

async function deleteProject(id) {
  const response = await fetch(`/api/projects/${id}`, { method: "DELETE" });
  const data = await response.json();
  if (!response.ok) return notify(data.error || data.message || "删除失败");
  if (state.currentProjectId === id) {
    state.currentProjectId = null;
    state.currentProject = null;
  }
  await loadProjects();
  notify("项目已删除");
}

async function refreshCurrentProject() {
  if (!state.currentProjectId) return;
  const response = await fetch(`/api/projects/${state.currentProjectId}`);
  state.currentProject = await response.json();
  renderProject(state.currentProject);
}

function renderProject(project) {
  if (!project) return;
  document.querySelector("#materialTitle").textContent = `素材：${project.name}`;
  document.querySelector("#targetMinutes").value = project.target_minutes || 5;
  document.querySelector("#protagonist").value = project.protagonist || "";
  setPerspective(project.narrative_perspective || "third", false);
  document.querySelector("#narrationRatio").value = project.narration_ratio || 0.45;
  document.querySelector("#llmBaseUrl").value = project.llm_base_url || state.status.llm_base_url || "";
  document.querySelector("#llmModel").value = project.llm_model || state.status.llm_model || "";
  syncLlmProvider(project);
  document.querySelector("#stylePrompt").value = project.style_prompt || "";
  document.querySelector("#transcribeProvider").value = project.transcribe_provider || state.status.transcribe_provider || "auto";
  document.querySelector("#whisperModel").value = project.whisper_model || state.status.whisper_model || "small";
  document.querySelector("#whisperBeamSize").value = project.whisper_beam_size || 5;
  document.querySelector("#whisperInitialPrompt").value = project.whisper_initial_prompt || "这是一段中文影视剧对白，请保留人物称呼、口语语气和剧情相关词汇。";
  document.querySelector("#ttsProvider").value = project.tts_provider || state.status.tts_provider || "minimax-official";
  document.querySelector("#ttsBaseUrl").value = project.tts_base_url || state.status.tts_base_url || "";
  document.querySelector("#ttsModel").value = project.tts_model || state.status.tts_model || "";
  const voice = project.tts_voice || state.status.tts_voice || "male-qn-qingse";
  const voiceSelect = document.querySelector("#ttsVoice");
  if ([...voiceSelect.options].some((option) => option.value === voice)) {
    voiceSelect.value = voice;
    document.querySelector("#customVoiceId").value = "";
  } else {
    document.querySelector("#customVoiceId").value = voice;
  }
  renderVoiceCards(voiceSelect.value);
  updateRatioLabel();
  renderMeta(project);
  renderTranscript(project.analysis?.transcript || []);
  renderScript(project.script?.lines || []);
  renderVoices(project.script?.lines || []);
  renderCalibration(project);
  renderExport(project);
  renderProgress(project);
  renderDebug(project);
  updateWorkflowControls(project);
  if (project.status === "running") startPolling();
}

function renderMeta(project) {
  const video = project.analysis?.video;
  const rows = [
    ["项目", project.name],
    ["阶段", project.stage],
    ["状态", project.status],
    ["消息", project.error || project.message || "-"],
    ["视频", video ? `${video.width}x${video.height} · ${formatTime(video.duration)}` : "未分析"],
    ["字幕", project.analysis ? `${project.analysis.transcript?.length || 0} 段` : "未分析"],
    ["自动字幕", state.status.faster_whisper_installed ? "本地 Whisper 可用" : "可使用 OpenAI 转写，或安装 faster-whisper"],
    ["更新时间", project.updated_label],
  ];
  document.querySelector("#projectMeta").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`).join("");
}

function renderTranscript(segments) {
  const el = document.querySelector("#transcriptList");
  if (!segments.length) {
    el.innerHTML = `<div class="empty">还没有字幕。点击“自动提取字幕”后，系统会优先读取外挂/内嵌字幕；没有字幕文件时会从视频音轨自动识别。</div>`;
    return;
  }
  const subtitleLink = state.currentProject?.artifacts?.subtitle
    ? `<a class="download" href="${state.currentProject.artifacts.subtitle}">下载校准 SRT</a>`
    : "";
  el.innerHTML = `
    <div class="transcript-tools">${subtitleLink}<span>修改字幕后请保存，再重新生成文案。</span></div>
    ${segments.map((seg, index) => `
      <article class="transcript-row" data-index="${index}">
        <div class="script-index">#${index + 1}</div>
        <input class="time-input start" type="number" step="0.01" value="${Number(seg.start || 0).toFixed(2)}">
        <input class="time-input end" type="number" step="0.01" value="${Number(seg.end || 0).toFixed(2)}">
        <input class="role-input" placeholder="角色" value="${escapeHtml(seg.role || "")}">
        <textarea>${escapeHtml(seg.text)}</textarea>
      </article>
    `).join("")}
  `;
}

async function saveTranscript() {
  if (!state.currentProjectId) return notify("请先选择或创建项目");
  const rows = [...document.querySelectorAll(".transcript-row")];
  if (!rows.length) return notify("没有可保存的字幕");
  const transcript = rows.map((row) => ({
    start: Number(row.querySelector(".start").value),
    end: Number(row.querySelector(".end").value),
    role: row.querySelector(".role-input")?.value || "",
    text: row.querySelector("textarea").value,
  }));
  const response = await fetch(`/api/projects/${state.currentProjectId}/transcript`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript }),
  });
  const data = await response.json();
  state.currentProject = data;
  renderProject(data);
  notify(response.ok ? "字幕已保存，请重新生成文案" : (data.error || data.message || "保存失败"));
}

function renderScript(lines) {
  const el = document.querySelector("#scriptEditor");
  if (!lines.length) {
    el.innerHTML = `<div class="empty">还没有文案。先完成素材分析，再点击“生成文案”。</div>`;
    return;
  }
  el.innerHTML = lines.map((line) => `
    <article class="script-row" data-clip="${line.clip_index}">
      <div class="script-index">#${line.clip_index}</div>
      <textarea>${escapeHtml(line.text)}</textarea>
      <input type="number" step="0.1" value="${Number(line.target_seconds || 0).toFixed(1)}">
    </article>
  `).join("");
}

function renderVoices(lines) {
  const el = document.querySelector("#voiceList");
  if (!lines.length) {
    el.innerHTML = `<div class="empty">文案生成后会在这里生成音频。</div>`;
    return;
  }
  el.innerHTML = lines.map((line) => `
    <div class="voice-row">
      <div><strong>#${line.clip_index}</strong><p>${escapeHtml(line.text)}</p></div>
      ${line.voice_url ? `<audio controls src="${line.voice_url}"></audio>` : `<span class="pending">未配音</span>`}
    </div>
  `).join("");
}

function renderVoiceCards(selectedVoice) {
  const grid = document.querySelector("#voiceCardGrid");
  const select = document.querySelector("#ttsVoice");
  if (!grid || !select) return;
  const options = [...select.options].filter((option) => option.value);
  grid.innerHTML = options.map((option) => `
    <article class="voice-card ${option.value === selectedVoice ? "active" : ""}" data-voice="${escapeHtml(option.value)}">
      <div><strong>${escapeHtml(option.textContent)}</strong><small>${escapeHtml(option.value)}</small></div>
      <button type="button" class="voice-play" title="试听">▶</button>
    </article>
  `).join("");
  grid.querySelectorAll(".voice-card").forEach((card) => {
    card.addEventListener("click", (event) => {
      select.value = card.dataset.voice;
      document.querySelector("#customVoiceId").value = "";
      renderVoiceCards(select.value);
      if (event.target.closest(".voice-play")) previewVoice();
    });
  });
}

function renderCalibration(project) {
  const el = document.querySelector("#calibrationList");
  if (!el) return;
  const lines = project.script?.lines || [];
  const clips = project.plan?.clips || [];
  if (!lines.length || !clips.length) {
    el.innerHTML = `<div class="empty">生成文案和配音后，可以在这里校准解说插入到原片的时间点。</div>`;
    return;
  }
  const clipByIndex = new Map(clips.map((clip) => [Number(clip.index), clip]));
  el.innerHTML = lines.map((line) => {
    const clip = clipByIndex.get(Number(line.clip_index)) || {};
    const start = Number(line.insert_start ?? clip.source_start ?? 0);
    return `
      <article class="calibration-row" data-clip="${line.clip_index}">
        <div class="script-index">#${line.clip_index}</div>
        <label><span>插入时间</span><input class="insert-start" type="number" step="0.1" min="0" value="${start.toFixed(1)}"></label>
        <div class="calibration-copy">
          <strong>${formatTime(start)} / 原片 ${formatTime(clip.source_start || 0)}-${formatTime(clip.source_end || 0)}</strong>
          <p>${escapeHtml(line.text)}</p>
        </div>
        ${line.voice_url ? `<audio controls src="${line.voice_url}"></audio>` : `<span class="pending">未配音</span>`}
      </article>
    `;
  }).join("");
}

function renderExport(project) {
  const el = document.querySelector("#exportResult");
  if (project.artifacts?.output) {
    el.innerHTML = `<video controls src="${project.artifacts.output}"></video><a class="download" href="${project.artifacts.output}">下载最终视频</a>`;
  } else {
    el.innerHTML = `<div class="empty">完成配音后点击“生成最终视频”。</div>`;
  }
}

function renderExportStable(project) {
  const el = document.querySelector("#exportResult");
  if (project.artifacts?.output) {
    const src = project.artifacts.output;
    if (el.dataset.src !== src) {
      el.dataset.src = src;
      el.innerHTML = `<video controls src="${src}"></video><a class="download" href="${src}">下载最终视频</a>`;
    }
  } else {
    el.dataset.src = "";
    el.innerHTML = `<div class="empty">完成配音并校准插入时间后，点击“生成最终视频”。</div>`;
  }
}

renderExport = renderExportStable;

async function runProjectAction(action) {
  if (!state.currentProjectId) return notify("请先选择或创建项目");
  notify("任务已开始");
  const response = await fetch(`/api/projects/${state.currentProjectId}/${action}`, { method: "POST" });
  const data = await response.json();
  state.currentProject = data;
  renderProject(data);
  if (!response.ok) notify(data.error || data.message || "失败");
  else startPolling();
}

async function analyzeProject() {
  if (!state.currentProjectId) return notify("请先选择或创建项目");
  await updateProject(state.currentProjectId, transcriptOptions(), true);
  await runProjectAction("analyze");
}

async function generateScript() {
  if (!state.currentProjectId) return notify("请先选择或创建项目");
  notify("正在生成文案...");
  const response = await fetch(`/api/projects/${state.currentProjectId}/script`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(projectOptions()),
  });
  const data = await response.json();
  state.currentProject = data;
  renderProject(data);
  if (!response.ok) notify(data.error || data.message || "生成失败");
  else startPolling();
}

async function saveScript() {
  if (!state.currentProjectId) throw new Error("请先选择或创建项目");
  const lines = [...document.querySelectorAll(".script-row")].map((row) => ({
    clip_index: Number(row.dataset.clip),
    text: row.querySelector("textarea").value,
    target_seconds: Number(row.querySelector("input").value),
    voice_file: state.currentProject?.script?.lines?.find((line) => Number(line.clip_index) === Number(row.dataset.clip))?.voice_file || null,
    insert_start: state.currentProject?.script?.lines?.find((line) => Number(line.clip_index) === Number(row.dataset.clip))?.insert_start ?? null,
  }));
  if (!lines.length) throw new Error("请先生成文案，再生成配音");
  const response = await fetch(`/api/projects/${state.currentProjectId}/script`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lines }),
  });
  const data = await response.json();
  state.currentProject = data;
  renderProject(data);
  if (!response.ok) throw new Error(data.error || data.message || "保存失败");
  notify("文案已保存");
}

async function saveCalibration() {
  if (!state.currentProjectId) return notify("请先选择或创建项目");
  const currentLines = state.currentProject?.script?.lines || [];
  if (!currentLines.length) return notify("请先生成文案和配音");
  const insertByClip = new Map(
    [...document.querySelectorAll(".calibration-row")].map((row) => [
      Number(row.dataset.clip),
      Number(row.querySelector(".insert-start").value),
    ])
  );
  const lines = currentLines.map((line) => ({
    clip_index: Number(line.clip_index),
    text: line.text,
    target_seconds: Number(line.target_seconds || 0),
    voice_file: line.voice_file || null,
    insert_start: insertByClip.has(Number(line.clip_index)) ? insertByClip.get(Number(line.clip_index)) : (line.insert_start ?? null),
  }));
  const response = await fetch(`/api/projects/${state.currentProjectId}/script`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lines }),
  });
  const data = await response.json();
  state.currentProject = data;
  renderProject(data);
  notify(response.ok ? "校准已保存" : (data.error || data.message || "保存失败"));
}

async function generateVoice() {
  if (!state.currentProjectId) return notify("请先选择或创建项目");
  const button = document.querySelector("#generateVoiceBtn");
  button.disabled = true;
  button.textContent = "生成中...";
  try {
    const options = projectOptions();
    await saveScript();
    notify("配音任务已开始");
    const response = await fetch(`/api/projects/${state.currentProjectId}/voice`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
    });
    const data = await response.json();
    state.currentProject = data;
    renderProject(data);
    if (!response.ok) notify(data.error || data.message || "配音失败");
    else startPolling();
  } catch (error) {
    notify(error.message || "配音失败");
  } finally {
    button.disabled = false;
    button.textContent = "生成全部音频";
  }
}

async function renderVideo() {
  await saveCalibration();
  if (!state.currentProjectId) return notify("请先选择或创建项目");
  notify("导出任务已开始");
  const response = await fetch(`/api/projects/${state.currentProjectId}/render`, { method: "POST" });
  const data = await response.json();
  state.currentProject = data;
  renderProject(data);
  if (!response.ok) notify(data.error || data.message || "合成失败");
  else startPolling();
}

function startPolling() {
  if (state.pollTimer) return;
  state.pollTimer = setInterval(async () => {
    await refreshCurrentProject();
    if (!state.currentProject || state.currentProject.status !== "running") {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      await loadProjects();
      if (state.currentProject?.status === "failed") notify(state.currentProject.message || "任务失败");
      if (state.currentProject?.progress === 100 && state.currentProject?.status !== "failed") notify(state.currentProject.message || "完成");
    }
  }, 1500);
}

function startGpuPolling() {
  if (state.gpuTimer) return;
  pollGpuStatus();
  state.gpuTimer = setInterval(pollGpuStatus, 3000);
}

async function pollGpuStatus() {
  try {
    const response = await fetch("/api/gpu");
    const gpu = await response.json();
    renderGpuStatus(gpu);
  } catch (error) {
    renderGpuStatus({ ok: false, message: error.message || "GPU 状态读取失败" });
  }
}

function renderGpuStatus(gpu) {
  const head = document.querySelector(".debug-head strong");
  if (!head) return;
  if (!gpu.ok) {
    head.textContent = `调试日志 · GPU 不可用`;
    return;
  }
  const procs = gpu.processes?.length ? ` · CUDA进程 ${gpu.processes.length}` : " · 无CUDA进程";
  head.textContent = `调试日志 · GPU ${gpu.utilization}% · 显存 ${gpu.memory_used_mb}/${gpu.memory_total_mb}MB${procs}`;
  if (state.currentProject?.status === "running" && gpu.processes?.length) {
    const names = gpu.processes.map((item) => `${item.name}(${item.memory_mb}MB)`).join(", ");
    addDebug("gpu", `GPU ${gpu.utilization}% | ${gpu.memory_used_mb}/${gpu.memory_total_mb}MB | ${names}`);
  }
}

function renderProgress(project) {
  const map = {
    materialProgress: "analyze",
    scriptProgress: "script",
    voiceProgress: "voice",
    exportProgress: "render",
  };
  for (const [id, task] of Object.entries(map)) {
    const el = document.querySelector(`#${id}`);
    if (!el) continue;
    const active = project.active_task === task || isTaskDone(project, task);
    if (!active) {
      el.innerHTML = "";
      continue;
    }
    const done = isTaskDone(project, task);
    const running = project.status === "running" && project.active_task === task && !done;
    const value = done ? 100 : smoothProgress(project, task, Number(project.progress || 0), running);
    const message = done && task === "render" ? "成片已生成" : project.message || "";
    el.innerHTML = `
      <div class="progress-title"><span>${escapeHtml(message)}</span><strong>${value}%</strong></div>
      <div class="progress-track ${running ? "running" : ""}"><span style="width:${Math.max(2, value)}%"></span></div>
    `;
  }
}

function smoothProgress(project, task, raw, running) {
  const key = `${project.id}:${task}`;
  if (!running) {
    state.progressDisplay[key] = raw;
    return Math.round(raw);
  }
  if (raw >= 94) {
    state.progressDisplay[key] = raw;
    return Math.round(raw);
  }
  const cap = task === "analyze" ? 94 : 96;
  const previous = Number(state.progressDisplay[key] ?? raw);
  let next = raw > previous ? raw : previous;
  if (raw >= 50 && next < cap) next = Math.min(cap, next + 1);
  state.progressDisplay[key] = next;
  return Math.round(next);
}

function isTaskDone(project, task) {
  if (task === "analyze") return Boolean(project.analysis);
  if (task === "script") return Boolean(project.script?.lines?.length);
  if (task === "voice") return Boolean(project.script?.lines?.length) && project.script.lines.every((line) => line.voice_url);
  if (task === "render") return Boolean(project.artifacts?.output);
  return false;
}

function canOpenView(id) {
  const project = state.currentProject;
  if (!project || id === "dashboard" || id === "material") return true;
  if (id === "script" && !project.analysis) {
    notify("请先在素材页完成字幕提取");
    return false;
  }
  if (id === "voice" && !project.script?.lines?.length) {
    notify("请先生成并审核文案");
    return false;
  }
  if (id === "export" && (!project.script?.lines?.length || !project.script.lines.every((line) => line.voice_url))) {
    notify("请先生成并试听配音");
    return false;
  }
  return true;
}

function updateWorkflowControls(project) {
  const running = project.status === "running" && !(project.active_task === "render" && project.artifacts?.output);
  const hasAnalysis = Boolean(project.analysis);
  const hasScript = Boolean(project.script?.lines?.length);
  const hasVoices = hasScript && project.script.lines.every((line) => line.voice_url);
  document.querySelector("#analyzeBtn").disabled = running;
  document.querySelector("#generateScriptBtn").disabled = running || !hasAnalysis;
  document.querySelector("#generateVoiceBtn").disabled = running || !hasScript;
  document.querySelector("#renderBtn").disabled = running || !hasVoices;
  navButtons.forEach((button) => {
    const id = button.dataset.view;
    button.disabled =
      running ||
      (id === "script" && !hasAnalysis) ||
      (id === "voice" && !hasScript) ||
      (id === "export" && !hasVoices);
  });
}

async function testLlm() {
  const box = document.querySelector("#llmTestResult");
  box.innerHTML = "正在测试模型...";
  const response = await fetch("/api/test/llm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      base_url: document.querySelector("#llmBaseUrl").value,
      model: document.querySelector("#llmModel").value,
    }),
  });
  const data = await response.json();
  box.className = `test-result ${data.ok ? "ok" : "fail"}`;
  box.innerHTML = data.ok
    ? `模型可用：${escapeHtml(data.model)}<br>${escapeHtml(data.response || "")}`
    : `模型测试失败：${escapeHtml(data.message || "")}`;
}

async function testTts() {
  const box = document.querySelector("#ttsTestResult");
  box.innerHTML = "正在测试配音...";
  const response = await fetch("/api/test/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ttsOptions()),
  });
  const data = await response.json();
  box.className = `test-result ${data.ok ? "ok" : "fail"}`;
  box.innerHTML = data.ok
    ? `配音可用：${escapeHtml(data.provider)} / ${escapeHtml(data.model)} / ${escapeHtml(data.voice)}<br><audio controls src="${data.audio_url}"></audio>`
    : `配音测试失败：${escapeHtml(data.message || "")}`;
}

async function previewVoice() {
  const box = document.querySelector("#voicePreviewResult");
  const button = document.querySelector("#previewVoiceBtn");
  box.className = "test-result";
  box.innerHTML = "正在生成试听...";
  button.disabled = true;
  try {
    const response = await fetch("/api/test/voice-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...ttsOptions(),
        text: "许三多站在原地，没急着解释。他只是把那口气咽下去，然后继续往前走。",
      }),
    });
    const data = await response.json();
    box.className = `test-result ${data.ok ? "ok" : "fail"}`;
    box.innerHTML = data.ok
      ? `${escapeHtml(data.provider)} / ${escapeHtml(data.voice)}<br><audio controls autoplay src="${data.audio_url}"></audio>`
      : `试听失败：${escapeHtml(data.message || "")}`;
  } catch (error) {
    box.className = "test-result fail";
    box.textContent = error.message || "试听失败";
  } finally {
    button.disabled = false;
  }
}

async function cloneVoice(event) {
  event.preventDefault();
  const box = document.querySelector("#cloneVoiceResult");
  const form = new FormData();
  const file = document.querySelector("#cloneVoiceAudio").files[0];
  const voiceId = document.querySelector("#cloneVoiceId").value.trim();
  if (!file) {
    box.className = "test-result fail";
    box.textContent = "请先选择一段音频样本";
    return;
  }
  form.append("audio", file);
  form.append("voice_id", voiceId);
  box.className = "test-result";
  box.textContent = "正在创建自定义音色...";
  const response = await fetch("/api/voices/clone", { method: "POST", body: form });
  const data = await response.json();
  box.className = `test-result ${data.ok ? "ok" : "fail"}`;
  box.textContent = data.ok ? `已创建：${data.voice_id}` : data.message || "创建失败";
  if (data.ok) document.querySelector("#customVoiceId").value = data.voice_id;
}

function projectOptions() {
  return {
    target_minutes: Number(document.querySelector("#targetMinutes").value),
    narration_ratio: Number(document.querySelector("#narrationRatio").value),
    protagonist: document.querySelector("#protagonist").value,
    narrative_perspective: document.querySelector("[data-perspective].active")?.dataset.perspective || "third",
    llm_provider: document.querySelector("#llmProvider").value,
    llm_base_url: document.querySelector("#llmBaseUrl").value,
    llm_model: document.querySelector("#llmModel").value,
    style_prompt: document.querySelector("#stylePrompt").value,
    ...ttsOptions(),
  };
}

function transcriptOptions() {
  return {
    transcribe_provider: document.querySelector("#transcribeProvider").value,
    whisper_model: document.querySelector("#whisperModel").value,
    whisper_beam_size: Number(document.querySelector("#whisperBeamSize").value),
    whisper_initial_prompt: document.querySelector("#whisperInitialPrompt").value,
  };
}

function ttsOptions() {
  return {
    provider: document.querySelector("#ttsProvider").value,
    base_url: document.querySelector("#ttsBaseUrl").value,
    model: document.querySelector("#ttsModel").value,
    voice: document.querySelector("#customVoiceId").value.trim() || document.querySelector("#ttsVoice").value,
    tts_provider: document.querySelector("#ttsProvider").value,
    tts_base_url: document.querySelector("#ttsBaseUrl").value,
    tts_model: document.querySelector("#ttsModel").value,
    tts_voice: document.querySelector("#customVoiceId").value.trim() || document.querySelector("#ttsVoice").value,
  };
}

function updateRatioLabel() {
  const ratio = Number(document.querySelector("#narrationRatio").value);
  document.querySelector("#ratioLabel").textContent = `${Math.round(ratio * 100)}%`;
}

function notify(message) {
  addDebug("ui", message);
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2600);
}

function renderDebug(project) {
  if (!project) return;
  const remote = (project.debug_events || []).map((item) => ({
    time: item.time || "",
    level: item.level || "info",
    message: item.message || "",
  }));
  state.debugEntries = mergeDebugEntries([...state.debugEntries, ...remote]);
  paintDebugLog();
}

function addDebug(level, message) {
  if (!message) return;
  state.debugEntries = mergeDebugEntries([
    ...state.debugEntries,
    {
      time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
      level,
      message,
    },
  ]);
  paintDebugLog();
}

function mergeDebugEntries(entries) {
  const seen = new Set();
  const merged = [];
  for (const entry of entries) {
    const key = `${entry.time}|${entry.level}|${entry.message}`;
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(entry);
  }
  return merged.slice(-160);
}

function paintDebugLog() {
  const el = document.querySelector("#debugLog");
  if (!el) return;
  if (!state.debugEntries.length) {
    el.innerHTML = `<div class="debug-line">等待任务日志...</div>`;
    return;
  }
  el.innerHTML = state.debugEntries.map((entry) => `
    <div class="debug-line ${escapeHtml(entry.level)}">[${escapeHtml(entry.time)}] ${escapeHtml(entry.level)}: ${escapeHtml(entry.message)}</div>
  `).join("");
  el.scrollTop = el.scrollHeight;
}

function clearDebugLog() {
  state.debugEntries = [];
  paintDebugLog();
}

function formatTime(seconds) {
  const value = Number(seconds || 0);
  const m = Math.floor(value / 60);
  const s = Math.floor(value % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
