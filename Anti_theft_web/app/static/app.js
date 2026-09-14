const $ = (id) => document.getElementById(id);

const videoInput = $('videoInput');
const dropzone = $('dropzone');
const preview = $('preview');
const videoBox = $('videoBox');
const videoName = $('videoName');
const analyzeBtn = $('analyzeBtn');
const threshold = $('threshold');
const thresholdValue = $('thresholdValue');
const progress = $('progress');
const errorBox = $('errorBox');
const canvas = $('timelineCanvas');
const emptyChart = $('emptyChart');

let selectedFile = null;
let previewUrl = null;
let latestData = null;
let activeWindowIndex = -1;
let rowElements = [];

function setFile(file) {
  if (!file) return;
  selectedFile = file;
  latestData = null;
  activeWindowIndex = -1;
  rowElements = [];
  analyzeBtn.disabled = false;
  videoBox.classList.remove('hidden');
  videoName.textContent = file.name;
  $('dropTitle').textContent = 'Đã chọn video';
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  preview.src = previewUrl;
  clearError();
}

videoInput.addEventListener('change', (e) => setFile(e.target.files[0]));
['dragenter', 'dragover'].forEach((event) => {
  dropzone.addEventListener(event, (e) => {
    e.preventDefault();
    dropzone.classList.add('drag');
  });
});
['dragleave', 'drop'].forEach((event) => {
  dropzone.addEventListener(event, (e) => {
    e.preventDefault();
    dropzone.classList.remove('drag');
  });
});
dropzone.addEventListener('drop', (e) => {
  const file = e.dataTransfer.files[0];
  if (file) setFile(file);
});

threshold.addEventListener('input', () => {
  thresholdValue.textContent = `${threshold.value}%`;
  $('usedThreshold').textContent = `${threshold.value}%`;
  if (latestData) {
    renderThresholdState(latestData, Number(threshold.value) / 100);
    drawTimeline(latestData.windows, Number(threshold.value) / 100, preview.currentTime || 0);
  }
});

function clearError() {
  errorBox.textContent = '';
  errorBox.classList.add('hidden');
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove('hidden');
}

function pct(x) {
  return `${(x * 100).toFixed(1)}%`;
}

function nearestWindowIndex(time) {
  if (!latestData?.windows?.length) return -1;
  let bestIndex = 0;
  let bestDistance = Math.abs(latestData.windows[0].time - time);
  for (let i = 1; i < latestData.windows.length; i += 1) {
    const distance = Math.abs(latestData.windows[i].time - time);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = i;
    }
  }
  return bestIndex;
}

function setActiveWindow(index, shouldScroll = false) {
  if (index < 0 || index >= rowElements.length) return;
  if (activeWindowIndex === index) return;

  if (activeWindowIndex >= 0 && rowElements[activeWindowIndex]) {
    rowElements[activeWindowIndex].classList.remove('active');
  }

  activeWindowIndex = index;
  const row = rowElements[index];
  if (row) {
    row.classList.add('active');
    if (shouldScroll) {
      row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }
}

function seekToWindow(index, autoplay = true) {
  if (!latestData?.windows?.[index]) return;
  const target = latestData.windows[index].time;
  preview.currentTime = Math.min(target, Number.isFinite(preview.duration) ? preview.duration : target);
  setActiveWindow(index, true);
  drawTimeline(latestData.windows, Number(threshold.value) / 100, target);
  if (autoplay) {
    preview.play().catch(() => {});
  }
}

function renderThresholdState(data, thresholdValueNum) {
  const alertWindows = data.windows.filter((w) => w.intrusion >= thresholdValueNum).length;
  const intrusion = data.max_intrusion >= thresholdValueNum;

  const statusText = $('statusText');
  statusText.textContent = intrusion ? 'INTRUSION' : 'NORMAL';
  statusText.className = intrusion ? 'status-intrusion' : 'status-normal';

  const badge = $('resultBadge');
  badge.textContent = intrusion ? 'CẢNH BÁO' : 'AN TOÀN';
  badge.className = `badge ${intrusion ? 'intrusion' : 'normal'}`;

  $('alertWindows').textContent = `${alertWindows}`;
  $('usedThreshold').textContent = pct(thresholdValueNum);

  data.windows.forEach((w, index) => {
    const row = rowElements[index];
    if (!row) return;
    const isAlert = w.intrusion >= thresholdValueNum;
    const badgeEl = row.querySelector('.row-badge');
    badgeEl.textContent = isAlert ? 'INTRUSION' : 'NORMAL';
    badgeEl.className = `row-badge ${isAlert ? 'intrusion' : 'normal'}`;
  });
}

function updateResult(data) {
  latestData = data;
  activeWindowIndex = -1;

  $('maxIntrusion').textContent = pct(data.max_intrusion);
  $('avgIntrusion').textContent = pct(data.average_intrusion);
  $('totalWindows').textContent = `${data.total_windows}`;

  const rows = $('resultRows');
  rows.innerHTML = '';
  rowElements = [];

  data.windows.forEach((w, index) => {
    const tr = document.createElement('tr');
    tr.className = 'analysis-row';
    tr.dataset.index = String(index);
    tr.dataset.time = String(w.time);
    tr.title = `Bấm để tua video tới ${w.time.toFixed(2)} giây`;
    tr.innerHTML = `
      <td><button class="time-jump" type="button">${w.time.toFixed(2)}s ▶</button></td>
      <td>${pct(w.normal)}</td>
      <td>${pct(w.intrusion)}</td>
      <td><span class="row-badge normal">NORMAL</span></td>
    `;
    tr.addEventListener('click', () => seekToWindow(index, true));
    rows.appendChild(tr);
    rowElements.push(tr);
  });

  renderThresholdState(data, Number(threshold.value) / 100);
  emptyChart.classList.add('hidden');
  drawTimeline(data.windows, Number(threshold.value) / 100, preview.currentTime || 0);

  const initialIndex = nearestWindowIndex(preview.currentTime || 0);
  if (initialIndex >= 0) setActiveWindow(initialIndex, false);
}

function drawTimeline(windows, thresholdValueNum, playbackTime = null) {
  if (!windows || !windows.length) return;

  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const W = rect.width;
  const H = rect.height;
  const pad = { l: 44, r: 20, t: 20, b: 30 };
  const cw = W - pad.l - pad.r;
  const ch = H - pad.t - pad.b;

  ctx.clearRect(0, 0, W, H);

  ctx.font = '11px system-ui';
  ctx.fillStyle = '#6f819d';
  ctx.strokeStyle = '#1e2d46';
  ctx.lineWidth = 1;

  [0, .25, .5, .75, 1].forEach((v) => {
    const y = pad.t + (1 - v) * ch;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(W - pad.r, y);
    ctx.stroke();
    if (v === 0 || v === .5 || v === 1) ctx.fillText(`${Math.round(v * 100)}%`, 8, y + 4);
  });

  const ty = pad.t + (1 - thresholdValueNum) * ch;
  ctx.save();
  ctx.setLineDash([6, 6]);
  ctx.strokeStyle = '#c4657a';
  ctx.beginPath();
  ctx.moveTo(pad.l, ty);
  ctx.lineTo(W - pad.r, ty);
  ctx.stroke();
  ctx.restore();
  ctx.fillStyle = '#bd8290';
  ctx.fillText(`${Math.round(thresholdValueNum * 100)}% threshold`, Math.max(pad.l, W - 116), ty - 7);

  const maxWindowTime = Math.max(...windows.map((w) => w.time), 1);
  const maxTime = Math.max(maxWindowTime, Number.isFinite(preview.duration) ? preview.duration : 0, 1);
  const xFor = (t) => pad.l + (Math.max(0, Math.min(t, maxTime)) / maxTime) * cw;
  const yFor = (p) => pad.t + (1 - p) * ch;

  const gradient = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
  gradient.addColorStop(0, 'rgba(130,151,255,.28)');
  gradient.addColorStop(1, 'rgba(130,151,255,.01)');

  ctx.beginPath();
  windows.forEach((w, i) => {
    const x = xFor(w.time);
    const y = yFor(w.intrusion);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.lineTo(xFor(windows[windows.length - 1].time), H - pad.b);
  ctx.lineTo(xFor(windows[0].time), H - pad.b);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  ctx.beginPath();
  windows.forEach((w, i) => {
    const x = xFor(w.time);
    const y = yFor(w.intrusion);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#8297ff';
  ctx.lineWidth = 2.2;
  ctx.stroke();

  if (playbackTime !== null && Number.isFinite(playbackTime)) {
    const markerX = xFor(playbackTime);
    const index = latestData ? nearestWindowIndex(playbackTime) : -1;
    const markerProb = index >= 0 ? windows[index].intrusion : null;

    ctx.save();
    ctx.strokeStyle = '#ffd166';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(markerX, pad.t);
    ctx.lineTo(markerX, H - pad.b);
    ctx.stroke();
    ctx.restore();

    if (markerProb !== null) {
      const px = xFor(windows[index].time);
      const py = yFor(markerProb);
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, Math.PI * 2);
      ctx.fillStyle = '#ffd166';
      ctx.fill();
    }
  }

  ctx.fillStyle = '#73849f';
  ctx.fillText('0s', pad.l, H - 9);
  ctx.textAlign = 'right';
  ctx.fillText(`${maxTime.toFixed(1)}s`, W - pad.r, H - 9);
  ctx.textAlign = 'left';
}

preview.addEventListener('timeupdate', () => {
  if (!latestData) return;
  const index = nearestWindowIndex(preview.currentTime);
  if (index >= 0) setActiveWindow(index, !preview.paused);
  drawTimeline(latestData.windows, Number(threshold.value) / 100, preview.currentTime);
});

preview.addEventListener('seeked', () => {
  if (!latestData) return;
  const index = nearestWindowIndex(preview.currentTime);
  if (index >= 0) setActiveWindow(index, true);
  drawTimeline(latestData.windows, Number(threshold.value) / 100, preview.currentTime);
});

canvas.addEventListener('click', (event) => {
  if (!latestData?.windows?.length) return;
  const rect = canvas.getBoundingClientRect();
  const padLeft = 44;
  const padRight = 20;
  const chartWidth = Math.max(1, rect.width - padLeft - padRight);
  const x = Math.max(0, Math.min(chartWidth, event.clientX - rect.left - padLeft));
  const duration = Number.isFinite(preview.duration)
    ? preview.duration
    : Math.max(...latestData.windows.map((w) => w.time), 1);
  const targetTime = (x / chartWidth) * duration;
  preview.currentTime = targetTime;
  const index = nearestWindowIndex(targetTime);
  if (index >= 0) setActiveWindow(index, true);
  preview.play().catch(() => {});
});

window.addEventListener('resize', () => {
  if (latestData) {
    drawTimeline(latestData.windows, Number(threshold.value) / 100, preview.currentTime || 0);
  }
});

analyzeBtn.addEventListener('click', async () => {
  if (!selectedFile) return;
  clearError();
  analyzeBtn.disabled = true;
  progress.classList.remove('hidden');

  const form = new FormData();
  form.append('video', selectedFile);
  form.append('frame_step', $('frameStep').value);
  form.append('window_stride', $('windowStride').value);
  form.append('threshold', Number(threshold.value) / 100);

  try {
    const response = await fetch('/api/analyze', { method: 'POST', body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Phân tích thất bại.');
    updateResult(payload);
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    progress.classList.add('hidden');
    analyzeBtn.disabled = false;
  }
});
