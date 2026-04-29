let currentEventSource = null;
let activeMeetingId = null;

document.addEventListener("DOMContentLoaded", () => {
  loadHistory();
  checkForStaleActiveSession();
});

function formatTimestamp(isoString) {
  if (!isoString) return "";

  // Helper to convert English digits to Persian digits
  const toPersianDigits = (str) => {
    const persianDigits = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];
    return str
      .toString()
      .replace(/\d/g, (digit) => persianDigits[parseInt(digit)]);
  };

  const date = new Date(isoString);

  // Format time string "HH:MM" or "H:MM"
  let timeStr = date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  const tempStr = date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });

  // Split by space to separate time and AM/PM
  const parts = tempStr.split(" ");

  let formattedTime = "";
  let suffix = "";

  if (parts.length === 2) {
    const timePart = parts[0];
    const ampmPart = parts[1];

    // Convert time part digits to Persian
    formattedTime = toPersianDigits(timePart);

    // Set suffix
    if (ampmPart === "AM") {
      suffix = " ب.ظ";
    } else {
      suffix = " ق.ظ";
    }
  } else {
    formattedTime = toPersianDigits(tempStr);
  }

  return `${formattedTime}${suffix}`;
}

function formatStage(stage) {
  if (!stage) return "";
  // Basic translation/mapping for UI
  const map = {
    download: "دانلود",
    ffmpeg_convert: "تبدیل",
    error: "خطا",
    finalize: "نهایی‌سازی",
    processing: "در حال پردازش",
  };
  return map[stage] || stage.replace("_", " ");
}

function saveToLocalStorage(meetingId, data) {
  const localHistory = JSON.parse(
    localStorage.getItem("conversionHistory") || "[]",
  );

  const filtered = localHistory.filter((item) => item.meeting_id !== meetingId);

  filtered.unshift({
    meeting_id: meetingId,
    stage: data.stage,
    progress: data.progress,
    message: data.message,
    timestamp: new Date().toISOString(),
  });

  if (filtered.length > 20) filtered.pop();

  localStorage.setItem("conversionHistory", JSON.stringify(filtered));
}

async function loadHistory() {
  const historyList = document.getElementById("historyList");
  historyList.innerHTML = "";

  try {
    const res = await fetch("/history");
    const backendHistory = await res.json();

    const localHistory = JSON.parse(
      localStorage.getItem("conversionHistory") || "[]",
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

    if (allHistory.length === 0) {
      historyList.innerHTML =
        '<div style="color:#a78bfa; font-size:14px; text-align:center;">سابقه‌ای وجود ندارد.</div>';
      return;
    }

    allHistory.forEach((job) => {
      const isCompleted = job.stage === "finalize" && job.progress >= 1;
      const isError = job.stage === "error";
      const isActive = job.meeting_id === activeMeetingId;
      renderHistoryItem(job, historyList, isActive, isCompleted, isError);
    });
  } catch (err) {
    console.error("Failed to load history", err);
  }
}

function renderHistoryItem(
  job,
  container,
  isCurrentlyActive,
  isCompleted,
  isError,
) {
  const div = document.createElement("div");
  div.className = "history-item";

  let statusText = "نامشخص";
  let statusClass = "";

  if (isError) {
    statusText = "خطا";
    statusClass = "error";
  } else if (isCompleted) {
    statusText = "انجام شد";
    statusClass = "completed";
  } else if (isCurrentlyActive) {
    statusText = "در حال انجام";
    statusClass = "processing";
  } else {
    statusText = job.stage ? formatStage(job.stage) : "در صف";
    if (statusText === "نهایی‌سازی" && job.progress >= 1) {
      statusText = "انجام شد";
      statusClass = "completed";
    }
  }

  div.innerHTML = `
    <div class="history-info">
        <span class="history-id">${job.meeting_id}.mkv</span>
        <span class="history-meta">${formatTimestamp(job.timestamp)}</span>
    </div>
    <div style="display:flex; align-items:center; gap:10px;">
        <span class="history-status ${statusClass}">${statusText}</span>
        ${isCompleted ? `<a href="/download/${job.meeting_id}" class="download" style="padding:6px 12px; font-size:12px; margin:0; background:#059669;">دانلود</a>` : ""}
    </div>
  `;
  container.appendChild(div);
}

async function checkForStaleActiveSession() {
  const localHistory = JSON.parse(
    localStorage.getItem("conversionHistory") || "[]",
  );
  const activeLocalJob = localHistory.find(
    (item) =>
      item.stage !== "finalize" &&
      item.stage !== "error" &&
      item.stage !== null,
  );

  if (activeLocalJob) {
    connectToSSE(activeLocalJob.meeting_id);
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
  progressBox.style.display = "none";

  if (currentEventSource) {
    currentEventSource.close();
    currentEventSource = null;
  }

  btn.disabled = true;
  status.innerText = "شروع تبدیل...";
  activeMeetingId = null;

  try {
    const response = await fetch(
      `/convert?meeting_url=${encodeURIComponent(url)}`,
      {
        method: "POST",
      },
    );

    const data = await response.json();

    if (data.status !== "success") {
      status.innerText = "تبدیل شکست خورد.";
      btn.disabled = false;
      return;
    }

    progressBox.style.display = "block";
    activeMeetingId = data.download_url.split("/").pop();

    if (data.existing) {
      status.innerText = "ادامه تبدیل موجود...";
    } else {
      status.innerText = "تبدیل شروع شد...";
    }

    connectToSSE(activeMeetingId, data.sse_url);
  } catch (err) {
    status.innerText = "خطا: " + err;
    btn.disabled = false;
  }
}

function connectToSSE(meetingId, sseEndpoint) {
  if (!sseEndpoint) {
    sseEndpoint = `/sse/${meetingId}`;
  }

  if (currentEventSource && currentEventSource.url === sseEndpoint) {
    return;
  }

  if (currentEventSource) {
    currentEventSource.close();
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
    console.error("SSE Error:", err);
    eventSource.close();
    currentEventSource = null;
    document.getElementById("status").innerText =
      "اتصال قطع شد. برای دیدن وضعیت نهایی رفرش کنید.";
    document.getElementById("btn").disabled = false;
  };
}

function updateUI(data, meetingId) {
  const bar = document.getElementById("progress");
  const percent = document.getElementById("percent");
  const stageName = document.getElementById("stageName");
  const status = document.getElementById("status");
  const result = document.getElementById("result");
  const btn = document.getElementById("btn");
  const progressBox = document.getElementById("progressBox");

  saveToLocalStorage(meetingId, data);

  if (progressBox.style.display === "block") {
    bar.style.width = data.progress * 100 + "%";
    percent.innerText = Math.floor(data.progress * 100) + "%";
    stageName.innerText = formatStage(data.stage);
    status.innerText = data.message;
  }

  if (
    (data.stage === "finalize" && data.progress >= 1) ||
    data.stage === "error"
  ) {
    if (currentEventSource) {
      currentEventSource.close();
      currentEventSource = null;
    }

    activeMeetingId = null;

    if (data.stage === "error") {
      status.innerText = `خطا در تبدیل: ${data.message}`;
      console.error(`Job ${meetingId} failed: ${data.message}`);
    } else {
      status.innerText = "تبدیل با موفقیت انجام شد.";
    }
    btn.disabled = false;

    loadHistory();
  }
}
