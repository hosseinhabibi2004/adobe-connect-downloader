let currentEventSource = null;
let activeMeetingId = null;
let lastKnownJobState = null;
let activeJobData = null;

document.addEventListener("DOMContentLoaded", () => {
  checkForStaleActiveSession();
  loadHistory();
});

function formatTimestamp(isoString) {
  if (!isoString) return "";
  const toPersianDigits = (str) => {
    const persianDigits = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];
    return str
      .toString()
      .replace(/\d/g, (digit) => persianDigits[parseInt(digit)]);
  };
  const date = new Date(isoString);
  const tempStr = date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
  const parts = tempStr.split(" ");
  let formattedTime = "";
  let suffix = "";
  if (parts.length === 2) {
    formattedTime = toPersianDigits(parts[0]);
    suffix = parts[1] === "AM" ? " ب.ظ" : " ق.ظ";
  } else {
    formattedTime = toPersianDigits(tempStr);
  }
  return `${formattedTime}${suffix}`;
}

function formatStage(stage) {
  const map = {
    download: "دانلود",
    ffmpeg_convert: "تبدیل",
    error: "خطا",
    finalize: "نهایی‌سازی",
    processing: "در حال پردازش",
  };
  return map[stage] || stage?.replace("_", " ") || "";
}

function saveToLocalStorage(meetingId, data) {
  const localHistory = JSON.parse(
    localStorage.getItem("meetingHistory") || "[]",
  );
  const existingIndex = localHistory.findIndex(
    (item) => item.meeting_id === meetingId,
  );

  const newItem = {
    meeting_id: meetingId,
    stage: data.stage,
    progress: data.progress,
    message: data.message,
    timestamp: data.timestamp || new Date().toISOString(),
  };

  if (existingIndex !== -1) {
    localHistory[existingIndex] = newItem;
  } else {
    localHistory.unshift(newItem);
  }

  if (localHistory.length > 20) localHistory.pop();
  localStorage.setItem("meetingHistory", JSON.stringify(localHistory));
}

async function loadHistory() {
  const historyList = document.getElementById("historyList");
  if (!historyList) return;

  try {
    const res = await fetch("/history");
    const backendHistory = await res.json();

    const localHistory = JSON.parse(
      localStorage.getItem("meetingHistory") || "[]",
    );
    const mergedMap = new Map();

    localHistory.forEach((item) =>
      mergedMap.set(item.meeting_id, { ...item, source: "local" }),
    );

    backendHistory.forEach((item) => {
      mergedMap.set(item.meeting_id, { ...item, source: "backend" });
    });

    const allHistory = Array.from(mergedMap.values())
      .filter((item) => item.timestamp)
      .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

    renderHistoryList(allHistory, historyList);
  } catch (err) {
    console.error("Failed to load history", err);
  }
}

function renderHistoryList(allHistory, container) {
  container.innerHTML = "";
  if (allHistory.length === 0) {
    container.innerHTML =
      '<div style="color:#a78bfa; font-size:14px; text-align:center;">سابقه‌ای وجود ندارد.</div>';
    return;
  }

  allHistory.forEach((job) => {
    const isCompleted = job.stage === "finalize" && job.progress >= 1;
    const isError = job.stage === "error";
    const isActive = job.meeting_id === activeMeetingId;

    const div = document.createElement("div");
    div.className = "history-item";

    let statusText = "نامشخص";
    let statusClass = "";

    if (isError) {
      statusText = "خطا";
      statusClass = "error";
    } else if (isCompleted) {
      statusText = "آماده";
      statusClass = "completed";
    } else if (isActive) {
      statusText = "در حال انجام";
      statusClass = "processing";
    } else {
      statusText = job.stage ? formatStage(job.stage) : "در صف";
      if (statusText === "نهایی‌سازی" && job.progress >= 1) {
        statusText = "آماده";
        statusClass = "completed";
      }
    }

    const downloadButtonHtml = isCompleted
      ? `<a href="/download/${job.meeting_id}" class="download" target="_blank">دانلود</a>`
      : "";
    const removeButtonHtml = isActive
      ? ""
      : `<button class="btn-remove-history" data-id="${job.meeting_id}">حذف</button>`;

    div.innerHTML = `
        <div class="history-info">
            <span class="history-id">${job.meeting_id}.mkv</span>
            <span class="history-meta">${formatTimestamp(job.timestamp)}<span class="history-status ${statusClass}">${statusText}</span></span>
        </div>
        <div style="display:flex; align-items:center; gap:10px;">
            ${downloadButtonHtml}
            ${removeButtonHtml}
        </div>
      `;

    const removeBtn = div.querySelector(".btn-remove-history");
    if (removeBtn) {
      removeBtn.addEventListener("click", () => {
        removeFromHistory(job.meeting_id);
      });
    }

    container.appendChild(div);
  });
}

async function removeFromHistory(id) {
  if (!confirm("آیا از حذف این آیتم اطمینان دارید؟")) return;

  try {
    await fetch(`/history/${id}`, { method: "DELETE" });
  } catch (err) {
    console.error("Failed to remove from backend history", err);
  }

  let history = JSON.parse(localStorage.getItem("meetingHistory") || "[]");
  const updatedHistory = history.filter((item) => item.meeting_id !== id);
  localStorage.setItem("meetingHistory", JSON.stringify(updatedHistory));

  if (id === activeMeetingId) clearActiveUI();
  loadHistory();
}

function clearActiveUI() {
  const progressBox = document.getElementById("progressBox");
  const status = document.getElementById("status");
  const btn = document.getElementById("btn");

  if (progressBox) progressBox.style.display = "none";
  if (status) status.innerText = "لطفا لینک جلسه را وارد کنید.";
  if (btn) btn.disabled = false;

  activeMeetingId = null;
  activeJobData = null;
  lastKnownJobState = null;

  if (currentEventSource) {
    currentEventSource.close();
    currentEventSource = null;
  }
}

async function checkForStaleActiveSession() {
  try {
    const res = await fetch("/history");
    const backendHistory = await res.json();

    const activeBackendJob = backendHistory.find(
      (item) =>
        item.stage !== "finalize" &&
        item.stage !== "error" &&
        item.stage !== null &&
        item.progress < 1,
    );

    if (activeBackendJob) {
      activeMeetingId = activeBackendJob.meeting_id;
      activeJobData = activeBackendJob;
      lastKnownJobState = JSON.stringify(activeBackendJob);

      updateUI(activeBackendJob, activeBackendJob.meeting_id);

      connectToSSE(activeBackendJob.meeting_id);

      saveToLocalStorage(activeBackendJob.meeting_id, activeBackendJob);

      return;
    }

    const localHistory = JSON.parse(
      localStorage.getItem("meetingHistory") || "[]",
    );
    const activeLocalJob = localHistory.find(
      (item) =>
        item.stage !== "finalize" &&
        item.stage !== "error" &&
        item.stage !== null &&
        item.progress < 1,
    );

    if (activeLocalJob) {
      activeMeetingId = activeLocalJob.meeting_id;
      activeJobData = activeLocalJob;
      lastKnownJobState = JSON.stringify(activeLocalJob);
      updateUI(activeLocalJob, activeLocalJob.meeting_id);
      connectToSSE(activeLocalJob.meeting_id);
    }
  } catch (err) {
    console.error("Failed to check for active session:", err);
  }
}

async function convertMeeting() {
  const url = document.getElementById("url").value.trim();
  const status = document.getElementById("status");
  const result = document.getElementById("result");
  const btn = document.getElementById("btn");
  const progressBox = document.getElementById("progressBox");

  if (!url) {
    status.innerText = "لطفا لینک جلسه را وارد کنید.";
    return;
  }

  result.innerHTML = "";
  progressBox.style.display = "block";
  btn.disabled = true;
  status.innerText = "در حال شروع تبدیل...";

  if (currentEventSource) {
    currentEventSource.close();
    currentEventSource = null;
  }
  activeMeetingId = null;
  activeJobData = null;
  lastKnownJobState = null;

  try {
    const response = await fetch(
      `/convert?meeting_url=${encodeURIComponent(url)}`,
      { method: "POST" },
    );
    const data = await response.json();

    if (data.status !== "success") {
      status.innerText = "تبدیل شکست خورد.";
      btn.disabled = false;
      progressBox.style.display = "none";
      return;
    }

    activeMeetingId = data.download_url.split("/").pop();

    const initialData = {
      meeting_id: activeMeetingId,
      stage: data.file_ready
        ? "finalize"
        : data.existing
          ? "processing"
          : "processing",
      progress: data.file_ready ? 1 : 0,
      message: data.file_ready
        ? "فایل آماده است."
        : data.existing
          ? "اتصال به جلسه موجود..."
          : "تبدیل شروع شد...",
      timestamp: new Date().toISOString(),
    };

    activeJobData = initialData;
    lastKnownJobState = JSON.stringify(initialData);
    saveToLocalStorage(activeMeetingId, initialData);

    status.innerText = initialData.message;

    if (data.file_ready) {
      finishJob(activeMeetingId, {
        stage: "finalize",
        progress: 1,
        message: "آماده",
        timestamp: new Date().toISOString(),
      });
    } else {
      connectToSSE(activeMeetingId, data.sse_url);
    }

    loadHistory();
  } catch (err) {
    status.innerText = "خطا: " + err;
    btn.disabled = false;
    progressBox.style.display = "none";
    activeMeetingId = null;
  }
}

function connectToSSE(meetingId, sseEndpoint) {
  if (!sseEndpoint) {
    sseEndpoint = `/sse/${meetingId}`;
  }

  if (currentEventSource && currentEventSource.url.includes(meetingId)) {
    return;
  }

  if (currentEventSource) {
    currentEventSource.close();
    currentEventSource = null;
  }

  const eventSource = new EventSource(sseEndpoint);
  currentEventSource = eventSource;

  eventSource.onmessage = function (event) {
    try {
      const data = JSON.parse(event.data);
      updateUI(data, meetingId);
    } catch (e) {
      console.error("Failed to parse SSE data:", e);
    }
  };

  eventSource.onerror = function (err) {
    console.warn("SSE Connection Lost:", err);
  };
}

function finishJob(meetingId, data) {
  activeMeetingId = null;
  activeJobData = null;
  lastKnownJobState = null;

  if (currentEventSource) {
    currentEventSource.close();
    currentEventSource = null;
  }

  saveToLocalStorage(meetingId, data);
  loadHistory();

  const status = document.getElementById("status");
  const btn = document.getElementById("btn");
  const progressBox = document.getElementById("progressBox");
  const result = document.getElementById("result");
  const bar = document.getElementById("progress");

  if (data.stage === "error") {
    if (bar) bar.style.width = "100%";
    status.innerText = `خطا: ${data.message}`;
    progressBox.style.display = "block";
    btn.disabled = false;
  } else {
    status.style.display = "none";
    progressBox.style.display = "none";
    result.innerHTML = "";
    btn.disabled = false;
  }
}

function updateUI(data, meetingId) {
  const bar = document.getElementById("progress");
  const percent = document.getElementById("percent");
  const stageName = document.getElementById("stageName");
  const status = document.getElementById("status");
  const result = document.getElementById("result");
  const btn = document.getElementById("btn");
  const progressBox = document.getElementById("progressBox");

  if (!bar || !percent || !stageName || !status || !btn || !progressBox) return;

  saveToLocalStorage(meetingId, data);
  activeJobData = data;

  const isFinished = data.stage === "finalize" && data.progress >= 1;
  const isError = data.stage === "error";
  const isProcessing = !isFinished && !isError;

  if (isProcessing) {
    activeMeetingId = meetingId;
    progressBox.style.display = "block";

    if (bar.style.width !== `${data.progress * 100}%`) {
      bar.style.width = `${data.progress * 100}%`;
    }
    if (percent.innerText !== `${Math.floor(data.progress * 100)}%`) {
      percent.innerText = `${Math.floor(data.progress * 100)}%`;
    }
    if (stageName.innerText !== formatStage(data.stage)) {
      stageName.innerText = formatStage(data.stage);
    }
    if (status.innerText !== data.message) {
      status.innerText = data.message;
    }

    if (!btn.disabled) btn.disabled = true;

    lastKnownJobState = JSON.stringify(data);
  } else {
    finishJob(meetingId, data);
  }
}
