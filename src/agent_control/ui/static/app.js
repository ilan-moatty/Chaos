const state = {
  runs: [],
  approvals: [],
  jobs: [],
  selectedRunId: null,
  currentRun: null,
  meta: null,
  apiToken: window.localStorage.getItem("chaos.apiToken") || "",
  pollHandle: null,
  isBusy: false,
  pollInFlight: false,
  lastLoadedAt: null,
  activeTab: "tasks",
};

const el = {
  statRuns: document.getElementById("stat-runs"),
  statRunsSecondary: document.getElementById("stat-runs-secondary"),
  statActive: document.getElementById("stat-active"),
  statActiveSecondary: document.getElementById("stat-active-secondary"),
  statPaused: document.getElementById("stat-paused"),
  statApprovals: document.getElementById("stat-approvals"),
  statApprovalsSecondary: document.getElementById("stat-approvals-secondary"),
  liveStatus: document.getElementById("live-status"),
  authStatus: document.getElementById("auth-status"),
  authAction: document.getElementById("auth-action"),
  onboardingPanel: document.getElementById("onboarding-panel"),
  attentionList: document.getElementById("attention-list"),
  runList: document.getElementById("run-list"),
  runSubtitle: document.getElementById("run-subtitle"),
  noticeBanner: document.getElementById("notice-banner"),
  detailEmpty: document.getElementById("detail-empty"),
  detailContent: document.getElementById("detail-content"),
  detailContentGrid: document.getElementById("detail-content-grid"),
  detailSectionTitle: document.getElementById("detail-section-title"),
  detailProgressLabel: document.getElementById("detail-progress-label"),
  detailProgressBar: document.getElementById("detail-progress-bar"),
  detailCreated: document.getElementById("detail-created"),
  detailNote: document.getElementById("detail-note"),
  detailStatus: document.getElementById("detail-status"),
  detailTasks: document.getElementById("detail-tasks"),
  detailCompleted: document.getElementById("detail-completed"),
  detailApprovals: document.getElementById("detail-approvals"),
  taskBoard: document.getElementById("task-board"),
  approvalList: document.getElementById("approval-list"),
  artifactList: document.getElementById("artifact-list"),
  eventList: document.getElementById("event-list"),
  focusApprovals: document.getElementById("focus-approvals"),
  resumeRun: document.getElementById("resume-run"),
  runCardTemplate: document.getElementById("run-card-template"),
  detailTabs: document.getElementById("detail-tabs"),
};

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (state.apiToken) {
    headers.Authorization = `Bearer ${state.apiToken}`;
  }
  const response = await fetch(path, {
    headers,
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return response.json();
}

function setBusy(isBusy, target = null) {
  state.isBusy = isBusy;
  document.querySelectorAll(".pixel-btn").forEach((button) => {
    if (button !== target) {
      button.disabled = isBusy && !button.dataset.allowWhileBusy;
    }
  });
  if (target) {
    target.disabled = isBusy;
  }
  if (el.runList) {
    el.runList.classList.toggle("loading", isBusy && !state.currentRun);
  }
  if (el.detailContentGrid) {
    el.detailContentGrid.classList.toggle("loading", isBusy && Boolean(state.currentRun));
  }
}

function showNotice(message, tone = "neutral") {
  if (!message) {
    el.noticeBanner.className = "notice-banner hidden";
    el.noticeBanner.textContent = "";
    return;
  }
  el.noticeBanner.textContent = message;
  el.noticeBanner.className = `notice-banner ${tone === "error" ? "is-error" : tone === "success" ? "is-success" : ""}`.trim();
}

function formatStatus(status) {
  const labels = {
    PENDING: "Pending",
    READY: "Ready",
    RUNNING: "Running",
    BLOCKED: "Blocked",
    WAITING_FOR_APPROVAL: "Waiting for approval",
    WAITING_FOR_INPUT: "Waiting for input",
    COMPLETED: "Completed",
    FAILED: "Failed",
    CANCELLED: "Cancelled",
    ACTIVE: "Active",
    PAUSED: "Paused",
    APPROVED: "Approved",
    PENDING_APPROVAL: "Pending approval",
    DENIED: "Denied",
  };
  return labels[status] || status.replaceAll("_", " ").toLowerCase();
}

function statusClass(status) {
  return `status-pill status-${status.toLowerCase()}`;
}

function formatTime(isoString) {
  return new Date(isoString).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRelativeTime(isoString) {
  const diffMs = Date.now() - new Date(isoString).getTime();
  const minutes = Math.round(diffMs / 60000);
  if (minutes <= 0) return "Updated just now";
  if (minutes === 1) return "Updated 1 min ago";
  if (minutes < 60) return `Updated ${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours === 1) return "Updated 1 hr ago";
  return `Updated ${hours} hr ago`;
}

function truncate(text, max = 72) {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function pulse(node) {
  if (!node) return;
  node.classList.remove("flash");
  void node.offsetWidth;
  node.classList.add("flash");
}

function setApiToken(token) {
  state.apiToken = token.trim();
  if (state.apiToken) {
    window.localStorage.setItem("chaos.apiToken", state.apiToken);
  } else {
    window.localStorage.removeItem("chaos.apiToken");
  }
}

function prettyPayload(payload) {
  if (payload == null) return "";
  if (typeof payload === "string") return payload;
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function renderTokenRow(items) {
  return `<div class="token-row">${items
    .map((item) => `<span class="token">${escapeHtml(item)}</span>`)
    .join("")}</div>`;
}

function renderBulletList(items, className = "artifact-summary-list") {
  return `<ul class="${className}">${items
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("")}</ul>`;
}

function documentBlock(lead, content = "") {
  return `
    <div class="artifact-document">
      <p class="artifact-lead">${escapeHtml(lead)}</p>
      ${content}
    </div>
  `;
}

function humanEventType(eventType) {
  const labels = {
    "run.created": "Run created",
    "run.paused": "Run paused",
    "run.resumed": "Run resumed",
    "run.completed": "Run completed",
    "task.created": "Task created",
    "task.ready": "Task ready",
    "task.started": "Task started",
    "task.waiting": "Task waiting",
    "task.blocked": "Task blocked",
    "task.completed": "Task completed",
    "task.failed": "Task failed",
    "agent.assigned": "Agent assigned",
    "artifact.created": "Artifact created",
    "tool.requested": "Tool requested",
    "tool.started": "Tool started",
    "tool.completed": "Tool completed",
    "tool.failed": "Tool failed",
    "approval.requested": "Approval requested",
    "run.summary_updated": "Summary updated",
    "job.started": "Background job started",
    "job.completed": "Background job completed",
    "job.failed": "Background job failed",
  };
  return labels[eventType] || eventType.replaceAll(".", " ");
}

function setActiveTab(tabName) {
  state.activeTab = tabName;
  document.querySelectorAll("[data-tab-target]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tabTarget === tabName);
  });
  document.querySelectorAll("[data-tab-pane]").forEach((pane) => {
    pane.classList.toggle("hidden", pane.dataset.tabPane !== tabName);
  });
  const titles = {
    tasks: "Task Board",
    approvals: "Approvals Queue",
    artifacts: "Artifacts",
    timeline: "Event Timeline",
  };
  el.detailSectionTitle.textContent = titles[tabName] || "Run Detail";
}

function artifactContentHtml(artifact) {
  const content = artifact.content || {};
  if (Array.isArray(content.findings) && content.findings.length) {
    return documentBlock("Key findings from this task are ready to review.", renderBulletList(content.findings));
  }
  if (Array.isArray(content.components) && content.components.length) {
    return documentBlock("This artifact includes the following components.", renderTokenRow(content.components));
  }
  if (Array.isArray(content.checks) && content.checks.length) {
    return documentBlock("The workflow recorded these checks before finishing.", renderBulletList(content.checks));
  }
  if (typeof content.published === "boolean") {
    const items = [];
    if (content.channel) items.push(`Channel: ${content.channel}`);
    if (content.message) items.push(`Message: ${content.message}`);
    items.push(content.published ? "Published successfully" : "Not published");
    return documentBlock("Publication details for this workflow step.", renderBulletList(items));
  }
  return documentBlock("Structured output from the agent is available below.", `<pre>${escapeHtml(truncate(prettyPayload(content), 220))}</pre>`);
}

function eventSummaryHtml(eventItem) {
  const payload = eventItem.payload || {};
  if (eventItem.type === "task.created" || eventItem.type === "task.ready" || eventItem.type === "task.started") {
    return `<div class="timeline-payload">${escapeHtml(payload.title || "A task changed state.")}</div>`;
  }
  if (eventItem.type === "task.completed" || eventItem.type === "task.failed") {
    return `<div class="timeline-payload">${escapeHtml(payload.summary || "The task finished and recorded an update.")}</div>`;
  }
  if (eventItem.type === "task.waiting" || eventItem.type === "task.blocked") {
    const items = [payload.reason, ...(payload.notes || [])].filter(Boolean);
    return items.length ? renderBulletList(items, "timeline-summary-list") : `<div class="timeline-payload">Waiting for the next operator action.</div>`;
  }
  if (eventItem.type === "agent.assigned") {
    const details = [payload.agent_id, payload.capability].filter(Boolean);
    return `<div class="timeline-payload">${escapeHtml(details.length ? `Assigned to ${details.join(" • ")}` : "An agent picked up this task.")}</div>`;
  }
  if (eventItem.type === "job.started" || eventItem.type === "job.completed" || eventItem.type === "job.failed") {
    const pieces = [payload.job_kind, payload.operator_id, payload.error].filter(Boolean);
    return `<div class="timeline-payload">${escapeHtml(pieces.length ? pieces.join(" • ") : "Background execution updated.")}</div>`;
  }
  if (eventItem.type === "tool.requested" || eventItem.type === "tool.completed" || eventItem.type === "approval.requested") {
    const items = [];
    if (payload.tool_name) items.push(`Tool: ${payload.tool_name}`);
    if (payload.tool_request_id) items.push(`Request: ${payload.tool_request_id}`);
    if (payload.result?.channel) items.push(`Channel: ${payload.result.channel}`);
    return items.length ? renderBulletList(items, "timeline-summary-list") : `<div class="timeline-payload">${escapeHtml(truncate(prettyPayload(payload), 220))}</div>`;
  }
  if (eventItem.type === "run.paused" || eventItem.type === "run.completed" || eventItem.type === "run.resumed") {
    return `<div class="timeline-payload">${escapeHtml(payload.reason || payload.run_id || "Run state updated.")}</div>`;
  }
  return `<div class="timeline-payload"><pre>${escapeHtml(truncate(prettyPayload(payload), 240))}</pre></div>`;
}

function onboardingVisible() {
  return state.runs.length === 0;
}

function updateAuthUi() {
  const authRequired = Boolean(state.meta?.auth?.required);
  if (!authRequired) {
    el.authStatus.textContent = "Local mode";
    el.authAction.textContent = state.apiToken ? "Clear Token" : "Set API Token";
    return;
  }
  el.authStatus.textContent = state.apiToken ? "Protected API connected" : "Protected API";
  el.authAction.textContent = state.apiToken ? "Update Token" : "Set API Token";
}

async function loadMeta() {
  state.meta = await api("/api/meta", { headers: {} });
  updateAuthUi();
}

function promptForToken() {
  const nextValue = window.prompt(
    "Enter the Chaos API token. Leave blank to clear it from this browser.",
    state.apiToken
  );
  if (nextValue === null) {
    return false;
  }
  setApiToken(nextValue);
  updateAuthUi();
  return true;
}

function runNextAction(run) {
  const latestJob = latestJobForRun(run.id);
  if (latestJob && (latestJob.status === "PENDING" || latestJob.status === "RUNNING")) {
    return latestJob.status === "PENDING" ? "Queued in background" : "Running in background";
  }
  if (run.pending_approval_count > 0) {
    return `${run.pending_approval_count} approval${run.pending_approval_count > 1 ? "s" : ""} waiting`;
  }
  if (run.status === "PAUSED") {
    return "Ready to resume";
  }
  if (run.status === "ACTIVE") {
    return "Agents are working";
  }
  if (run.status === "COMPLETED") {
    return "Ready for review";
  }
  return "Monitoring";
}

function latestJobForRun(runId) {
  return state.jobs.find((job) => job.run_id === runId) || null;
}

function runProgress(run) {
  if (!run.task_count) return 0;
  return Math.round((run.completed_task_count / run.task_count) * 100);
}

function detailNote(run, pendingApprovals) {
  if (run.status === "PAUSED" && pendingApprovals.length) {
    return `This run is paused and waiting on ${pendingApprovals.length} approval${pendingApprovals.length > 1 ? "s" : ""}. Review the queue below and approve or deny the pending tool request${pendingApprovals.length > 1 ? "s" : ""}.`;
  }
  if (run.status === "PAUSED") {
    return "This run is paused but ready to continue. Use Resume Run to let the agents keep going.";
  }
  if (run.status === "COMPLETED") {
    return "This run is complete. Review the artifacts and event timeline below for the final output and audit trail.";
  }
  if (run.status === "ACTIVE") {
    return "This run is active. The dashboard will keep refreshing while agents continue working.";
  }
  return "Review the task board and approvals queue below to decide the next operator action.";
}

function renderAttentionList() {
  if (!state.approvals.length) {
    const hasRuns = state.runs.length > 0;
    el.attentionList.innerHTML = `
      <div class="empty-state">
        ${
          hasRuns
            ? "Nothing needs action right now. When a workflow pauses for approval, it will surface here first."
            : "No runs yet. Launch the demo or release brief workflow to see how Chaos behaves."
        }
      </div>
    `;
    return;
  }

  el.attentionList.innerHTML = state.approvals
    .map((requestItem) => {
      const run = state.runs.find((item) => item.id === requestItem.run_id);
      return `
        <article class="attention-card">
          <div>
            <strong>${escapeHtml(requestItem.tool_name)} needs approval</strong>
            <div class="attention-meta">
              Run ${escapeHtml(requestItem.run_id.slice(0, 10))} • task ${escapeHtml(requestItem.task_id.slice(0, 10))} • ${escapeHtml(
                run?.objective || "Pending workflow"
              )}
            </div>
            <div class="artifact-summary">${documentBlock("This tool request is paused until you approve or deny it.", `<pre>${escapeHtml(
              truncate(prettyPayload(requestItem.arguments), 220)
            )}</pre>`)}</div>
          </div>
          <div class="attention-actions">
            <button class="pixel-btn tertiary small" data-open-run="${requestItem.run_id}">Open Run</button>
            <button class="pixel-btn cool small" data-approve="${requestItem.id}">Approve</button>
            <button class="pixel-btn danger small" data-deny="${requestItem.id}">Deny</button>
          </div>
        </article>
      `;
    })
    .join("");
}

async function loadDashboard(preferredRunId = state.selectedRunId) {
  if (state.pollInFlight) return;
  if (state.meta?.auth?.required && !state.apiToken) {
    showNotice("This Chaos instance requires an API token. Use Set API Token in the header to connect.", "error");
    el.runList.innerHTML = `<div class="empty-state">This dashboard is protected. Add your API token to load runs and approvals.</div>`;
    el.attentionList.innerHTML = `<div class="empty-state">Approval items will appear here after you authenticate.</div>`;
    showEmptyState();
    return;
  }
  state.pollInFlight = true;
  try {
    const data = await api("/api/dashboard");
    state.runs = data.runs;
    state.approvals = data.approvals;
    state.jobs = data.jobs || [];
    state.lastLoadedAt = new Date().toISOString();

    el.statRuns.textContent = data.stats.run_count;
    el.statRunsSecondary.textContent = data.stats.run_count;
    el.statActive.textContent = data.stats.active_count;
    el.statActiveSecondary.textContent = data.stats.active_count;
    el.statPaused.textContent = data.stats.paused_count;
    el.statApprovals.textContent = data.stats.approval_count;
    el.statApprovalsSecondary.textContent = data.stats.approval_count;
    el.liveStatus.textContent = formatRelativeTime(state.lastLoadedAt);
    el.onboardingPanel.classList.toggle("hidden", !onboardingVisible());

    renderRunList();
    renderAttentionList();

    const nextRunId =
      preferredRunId && state.runs.some((run) => run.id === preferredRunId)
        ? preferredRunId
        : state.runs[0]?.id || null;

    if (nextRunId) {
      await loadRun(nextRunId, false);
    } else {
      state.selectedRunId = null;
      state.currentRun = null;
      showEmptyState();
    }
  } finally {
    state.pollInFlight = false;
  }
}

function renderRunList() {
  el.runList.innerHTML = "";
  if (!state.runs.length) {
    el.runList.innerHTML = `<div class="empty-state">No runs yet. Start with Demo Run for a guided tour, or Release Brief to try a fuller approval workflow.</div>`;
    return;
  }

  state.runs.forEach((run) => {
    const fragment = el.runCardTemplate.content.cloneNode(true);
    const button = fragment.querySelector(".run-card");
    button.dataset.runId = run.id;
    if (state.isBusy && run.id === state.selectedRunId) {
      button.classList.add("is-busy");
    }
    if (run.id === state.selectedRunId) {
      button.classList.add("is-active");
    }
    fragment.querySelector(".run-id").textContent = run.id.slice(0, 10);
    const pill = fragment.querySelector(".status-pill");
    pill.className = statusClass(run.status);
    pill.textContent = formatStatus(run.status);
    fragment.querySelector(".run-objective").textContent = run.objective;
    fragment.querySelector(".run-meta").textContent =
      `${runNextAction(run)} • ${runProgress(run)}% complete • ${run.completed_task_count}/${run.task_count} tasks • ${formatTime(run.created_at)}`;

    button.addEventListener("click", async () => {
      await loadRun(run.id, true);
    });
    el.runList.appendChild(fragment);
  });
}

function showEmptyState() {
  el.detailEmpty.classList.remove("hidden");
  el.detailContent.classList.add("hidden");
  el.detailContentGrid.classList.add("hidden");
  el.runSubtitle.textContent = "Select a run to inspect its state.";
  el.resumeRun.disabled = true;
  el.focusApprovals.disabled = true;
  el.taskBoard.innerHTML = "";
  el.approvalList.innerHTML = "";
  el.artifactList.innerHTML = "";
  el.eventList.innerHTML = "";
  setActiveTab("tasks");
}

async function loadRun(runId, animate = true) {
  state.selectedRunId = runId;
  renderRunList();
  const detail = await api(`/api/runs/${runId}`);
  state.currentRun = detail;
  renderRunDetail(animate);
}

function renderRunDetail(animate = true) {
  const { run, tasks, tool_requests: toolRequests, artifacts, events, jobs = [] } = state.currentRun;
  const pendingApprovals = toolRequests.filter((requestItem) => requestItem.status === "PENDING_APPROVAL");
  const latestJob = jobs[0] || null;

  el.detailEmpty.classList.add("hidden");
  el.detailContent.classList.remove("hidden");
  el.detailContentGrid.classList.remove("hidden");
  el.runSubtitle.textContent = `${run.id} • ${run.objective}`;
  el.detailStatus.textContent = formatStatus(run.status);
  el.detailTasks.textContent = tasks.length;
  el.detailCompleted.textContent = run.completed_task_count;
  el.detailApprovals.textContent = pendingApprovals.length;
  el.detailProgressLabel.textContent = `${runProgress(run)}% complete`;
  el.detailProgressBar.style.width = `${runProgress(run)}%`;
  el.detailCreated.textContent = `Created ${formatTime(run.created_at)}`;
  let nextNote = detailNote(run, pendingApprovals);
  if (latestJob && (latestJob.status === "PENDING" || latestJob.status === "RUNNING")) {
    nextNote = `${latestJob.status === "PENDING" ? "A background job is queued for this run." : "A background job is currently executing for this run."} ${nextNote}`;
  } else if (latestJob?.status === "FAILED" && latestJob.error) {
    nextNote = `The latest background job failed: ${latestJob.error}. ${nextNote}`;
  }
  el.detailNote.textContent = nextNote;
  el.resumeRun.disabled = !(run.status === "PAUSED" && pendingApprovals.length === 0);
  el.focusApprovals.disabled = pendingApprovals.length === 0;
  if (pendingApprovals.length && state.activeTab === "tasks") {
    setActiveTab("approvals");
  } else if (!pendingApprovals.length && state.activeTab === "approvals") {
    setActiveTab("tasks");
  } else {
    setActiveTab(state.activeTab);
  }

  el.taskBoard.innerHTML = tasks.length
    ? tasks
        .map(
          (task) => `
            <article class="task-card">
              <div class="task-top">
                <strong>${escapeHtml(task.title)}</strong>
                <span class="${statusClass(task.status)}">${formatStatus(task.status)}</span>
              </div>
              <div class="task-description">${escapeHtml(task.description)}</div>
              <div class="task-meta">
                <span class="task-capability">${escapeHtml(task.required_capability)}</span>
                • owner ${escapeHtml(task.owner_agent_id || "unassigned")}
                • priority ${escapeHtml(task.priority)}
              </div>
            </article>
          `
        )
        .join("")
    : `<div class="empty-state">No tasks for this run yet.</div>`;

  el.artifactList.innerHTML = artifacts.length
    ? artifacts
        .map(
          (artifact) => `
            <article class="artifact-card">
              <div class="artifact-top">
                <strong>${escapeHtml(artifact.summary)}</strong>
                <span class="artifact-kind">${escapeHtml(artifact.kind)}</span>
              </div>
              <div class="artifact-summary">${artifactContentHtml(artifact)}</div>
              <div class="artifact-meta">task ${escapeHtml(artifact.task_id.slice(0, 10))} • ${escapeHtml(formatTime(artifact.created_at))}</div>
            </article>
          `
        )
        .join("")
    : `<div class="empty-state">Artifacts will appear here as agents complete work.</div>`;

  el.approvalList.innerHTML = pendingApprovals.length
    ? pendingApprovals
        .map(
          (requestItem) => `
            <article class="approval-card" data-request-id="${requestItem.id}">
              <div class="approval-top">
                <strong>${escapeHtml(requestItem.tool_name)}</strong>
                <span class="${statusClass(requestItem.status)}">${formatStatus(requestItem.status)}</span>
              </div>
              <div class="approval-meta">task ${escapeHtml(requestItem.task_id.slice(0, 10))} • requested by ${escapeHtml(requestItem.agent_id)}</div>
              <div class="artifact-summary">${documentBlock("This tool call is waiting for your decision.", `<pre>${escapeHtml(truncate(prettyPayload(requestItem.arguments), 220))}</pre>`)}</div>
              <div class="approval-actions">
                <button class="pixel-btn tertiary small" data-open-run="${requestItem.run_id}">Open Run</button>
                <button class="pixel-btn cool small" data-approve="${requestItem.id}">Approve</button>
                <button class="pixel-btn danger small" data-deny="${requestItem.id}">Deny</button>
              </div>
            </article>
          `
        )
        .join("")
    : `<div class="empty-state">No approvals waiting. Nice and quiet.</div>`;

  const recentEvents = events.slice(-24).reverse();
  el.eventList.innerHTML = recentEvents.length
    ? recentEvents
        .map(
          (eventItem) => `
            <article class="timeline-event">
              <div class="timeline-top">
                <span class="timeline-type">${escapeHtml(humanEventType(eventItem.type))}</span>
                <span class="timeline-meta">${escapeHtml(formatTime(eventItem.created_at))}</span>
              </div>
              ${eventSummaryHtml(eventItem)}
            </article>
          `
        )
        .join("")
    : `<div class="empty-state">No events recorded for this run.</div>`;

  bindApprovalButtons();
  if (animate) {
    pulse(el.detailContent);
    pulse(el.detailContentGrid);
  }
}

function bindApprovalButtons() {
  document.querySelectorAll("[data-open-run]").forEach((button) => {
    button.addEventListener("click", async () => {
      await runAction(button, async () => {
        await loadRun(button.dataset.openRun, true);
        showNotice("Run opened.", "success");
      });
    });
  });

  document.querySelectorAll("[data-approve]").forEach((button) => {
    button.addEventListener("click", async () => {
      await runAction(button, async () => {
        await api(`/api/tool-requests/${button.dataset.approve}/approve`, { method: "POST" });
        showNotice("Tool request approved. Resume the run to continue.", "success");
        await loadDashboard(state.selectedRunId);
      });
    });
  });

  document.querySelectorAll("[data-deny]").forEach((button) => {
    button.addEventListener("click", async () => {
      const reason = window.prompt("Reason for denial:", "Not ready to publish yet.");
      if (reason === null) return;
      await runAction(button, async () => {
        await api(`/api/tool-requests/${button.dataset.deny}/deny`, {
          method: "POST",
          body: JSON.stringify({ reason }),
        });
        showNotice("Tool request denied.", "success");
        await loadDashboard(state.selectedRunId);
      });
    });
  });
}

async function runAction(button, action) {
  try {
    setBusy(true, button);
    await action();
  } catch (error) {
    console.error(error);
    if (String(error.message).includes("Unauthorized")) {
      showNotice("Authentication failed. Update the API token and try again.", "error");
    } else {
    showNotice(error.message || "Something went wrong while performing that action.", "error");
    }
  } finally {
    setBusy(false);
  }
}

async function launchWorkflow(kind) {
  const path = kind === "demo" ? "/api/runs/demo" : "/api/runs/release-brief";
  const detail = await api(path, { method: "POST" });
  state.selectedRunId = detail.run.id;
  await loadDashboard(detail.run.id);
}

async function resumeSelectedRun() {
  if (!state.selectedRunId) return;
  await api(`/api/runs/${state.selectedRunId}/resume`, { method: "POST" });
  await loadDashboard(state.selectedRunId);
}

function bindTopLevelActions() {
  el.authAction.addEventListener("click", async () => {
    const changed = promptForToken();
    if (!changed) return;
    await runAction(el.authAction, async () => {
      await loadMeta();
      await loadDashboard(state.selectedRunId);
      showNotice(state.apiToken ? "API token saved for this browser." : "API token cleared.", "success");
    });
  });
  document.querySelector('[data-action="launch-demo"]').addEventListener("click", async () => {
    await runAction(null, async () => {
      await launchWorkflow("demo");
      showNotice("Demo run queued. The dashboard will refresh as work continues.", "success");
    });
  });
  document.querySelector('[data-action="launch-release"]').addEventListener("click", async () => {
    await runAction(null, async () => {
      await launchWorkflow("release");
      showNotice("Release brief workflow queued. The dashboard will refresh as work continues.", "success");
    });
  });
  document.getElementById("refresh-runs").addEventListener("click", async () => {
    await runAction(null, async () => {
      await loadDashboard(state.selectedRunId);
      showNotice("Dashboard refreshed.", "success");
    });
  });
  el.resumeRun.addEventListener("click", async () => {
    await runAction(el.resumeRun, async () => {
      await resumeSelectedRun();
      showNotice("Resume queued. The background worker will continue the run.", "success");
    });
  });
  el.focusApprovals.addEventListener("click", () => {
    setActiveTab("approvals");
    const approvalSection = document.getElementById("approval-list");
    approvalSection?.closest(".content-card")?.classList.add("is-highlighted");
    approvalSection?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => {
      approvalSection?.closest(".content-card")?.classList.remove("is-highlighted");
    }, 1400);
  });
  el.detailTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-tab-target]");
    if (!button) return;
    setActiveTab(button.dataset.tabTarget);
  });
}

async function boot() {
  bindTopLevelActions();
  await loadMeta();
  await loadDashboard();
  state.pollHandle = window.setInterval(() => {
    loadDashboard(state.selectedRunId).catch((error) => console.error(error));
  }, 5000);
}

boot().catch((error) => {
  console.error(error);
  showNotice(error.message || "Failed to load the dashboard.", "error");
  el.runList.innerHTML = `<div class="empty-state">Failed to load the dashboard. ${error.message}</div>`;
});
