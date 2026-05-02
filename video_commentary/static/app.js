const state = {
  currentProjectId: null,
  currentProject: null,
  projects: [],
  status: {},
};

const views = document.querySelectorAll(".view");
const navButtons = document.querySelectorAll(".steps button");
const toast = document.querySelector("#toast");

navButtons.forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

document.querySelector("#createForm").addEventListener("submit", createProject);
document.querySelector("#analyzeBtn").addEventListener("click", () => runProjectAction("analyze"));
document.querySelector("#generateScriptBtn").addEventListener("click", generateScript);
document.querySelector("#saveScriptBtn").addEventListener("click", saveScript);
document.querySelector("#generateVoiceBtn").addEventListener("click", generateVoice);
document.querySelector("#renderBtn").addEventListener("click", renderVideo);
document.querySelector("#testLlmBtn").addEventListener("click", testLlm);
document.querySelector("#testTtsBtn").addEventListener("click", testTts);
document.querySelector("#narrationRatio").addEventListener("input", updateRatioLabel);
document.querySelector("#cloneVoiceForm")?.addEventListener("submit", cloneVoice);

init();

async function init() {
  updateRatioLabel();
  await loadStatus();
  await loadProjects();
}

async function loadStatus() {
  const response = await fetch("/api/status");
  state.status = await response.json();
}

function showView(id) {
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

async function updateProject(id, payload) {
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
  notify("项目已更新");
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
  document.querySelector("#narrationRatio").value = project.narration_ratio || 0.45;
  document.querySelector("#llmBaseUrl").value = project.llm_base_url || state.status.llm_base_url || "";
  document.querySelector("#llmModel").value = project.llm_model || state.status.llm_model || "";
  document.querySelector("#stylePrompt").value = project.style_prompt || "";
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
  updateRatioLabel();
  renderMeta(project);
  renderTranscript(project.analysis?.transcript || []);
  renderScript(project.script?.lines || []);
  renderVoices(project.script?.lines || []);
  renderExport(project);
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
    ["更新时间", project.updated_label],
  ];
  document.querySelector("#projectMeta").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`).join("");
}

function renderTranscript(segments) {
  const el = document.querySelector("#transcriptList");
  if (!segments.length) {
    el.innerHTML = `<div class="empty">没有字幕。可在创建项目时上传 SRT/VTT/ASS 字幕；如只有硬字幕，需要 OCR 或单独 ASR 服务。</div>`;
    return;
  }
  el.innerHTML = segments.map((seg, index) => `
    <div class="line">
      <span>#${index + 1} · ${formatTime(seg.start)} - ${formatTime(seg.end)}</span>
      <p>${escapeHtml(seg.text)}</p>
    </div>
  `).join("");
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

function renderExport(project) {
  const el = document.querySelector("#exportResult");
  if (project.artifacts?.output) {
    el.innerHTML = `<video controls src="${project.artifacts.output}"></video><a class="download" href="${project.artifacts.output}">下载最终视频</a>`;
  } else {
    el.innerHTML = `<div class="empty">完成配音后点击“生成最终视频”。</div>`;
  }
}

async function runProjectAction(action) {
  if (!state.currentProjectId) return notify("请先选择或创建项目");
  notify("处理中...");
  const response = await fetch(`/api/projects/${state.currentProjectId}/${action}`, { method: "POST" });
  const data = await response.json();
  state.currentProject = data;
  renderProject(data);
  notify(response.ok ? "完成" : (data.error || data.message || "失败"));
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
  notify(response.ok ? "文案已生成" : (data.error || data.message || "生成失败"));
}

async function saveScript() {
  if (!state.currentProjectId) throw new Error("请先选择或创建项目");
  const lines = [...document.querySelectorAll(".script-row")].map((row) => ({
    clip_index: Number(row.dataset.clip),
    text: row.querySelector("textarea").value,
    target_seconds: Number(row.querySelector("input").value),
    voice_file: state.currentProject?.script?.lines?.find((line) => Number(line.clip_index) === Number(row.dataset.clip))?.voice_file || null,
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

async function generateVoice() {
  if (!state.currentProjectId) return notify("请先选择或创建项目");
  const button = document.querySelector("#generateVoiceBtn");
  button.disabled = true;
  button.textContent = "生成中...";
  try {
    await saveScript();
    notify("正在生成配音...");
    const response = await fetch(`/api/projects/${state.currentProjectId}/voice`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(projectOptions()),
    });
    const data = await response.json();
    state.currentProject = data;
    renderProject(data);
    notify(response.ok ? "音频已生成" : (data.error || data.message || "配音失败"));
  } catch (error) {
    notify(error.message || "配音失败");
  } finally {
    button.disabled = false;
    button.textContent = "生成全部音频";
  }
}

async function renderVideo() {
  if (!state.currentProjectId) return notify("请先选择或创建项目");
  notify("正在合成视频...");
  const response = await fetch(`/api/projects/${state.currentProjectId}/render`, { method: "POST" });
  const data = await response.json();
  state.currentProject = data;
  renderProject(data);
  notify(response.ok ? "视频已生成" : (data.error || data.message || "合成失败"));
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
    llm_base_url: document.querySelector("#llmBaseUrl").value,
    llm_model: document.querySelector("#llmModel").value,
    style_prompt: document.querySelector("#stylePrompt").value,
    ...ttsOptions(),
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
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2600);
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
