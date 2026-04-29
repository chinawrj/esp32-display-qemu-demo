// Framebuffer viewer client.
//
// Connects to ws://<host>:7788, expects alternating text/binary frames:
//   text:   {"type":"fb_init",  ...}
//   text:   {"type":"fb_update", x,y,w,h,format,stride,encoding}
//   binary: <stride*h bytes of pixel data>
//
// Currently supports format=RGB565 little-endian, encoding=raw.

const canvas = document.getElementById('fb');
const ctx = canvas.getContext('2d', { willReadFrequently: false });
const statusEl = document.getElementById('status');
const resolutionEl = document.getElementById('resolution');
const fpsEl = document.getElementById('fps');
const lastUpdateEl = document.getElementById('last-update');
const lastTouchEl = document.getElementById('last-touch');

// Touch / pointer wiring (Phase-3 host slice) -------------------------------
// Translates a CSS-pixel pointer event into device-pixel canvas coordinates
// and sends a JSON message over the active WebSocket. Firmware-side LVGL
// indev integration is a follow-up (cdp-phase3 firmware milestone).
let activeWs = null;

function pointerToCanvas(ev) {
  const rect = canvas.getBoundingClientRect();
  const sx = canvas.width / rect.width;
  const sy = canvas.height / rect.height;
  return {
    x: Math.max(0, Math.min(canvas.width  - 1, Math.round((ev.clientX - rect.left) * sx))),
    y: Math.max(0, Math.min(canvas.height - 1, Math.round((ev.clientY - rect.top)  * sy))),
  };
}

function sendTouch(event, ev) {
  if (!activeWs || activeWs.readyState !== 1) return;
  const { x, y } = pointerToCanvas(ev);
  const msg = { type: 'touch', event, x, y, id: ev.pointerId ?? 0 };
  activeWs.send(JSON.stringify(msg));
  lastTouchEl.textContent = `last touch: ${event} (${x},${y})`;
}

function attachPointerHandlers() {
  let down = false;
  canvas.addEventListener('pointerdown', ev => {
    down = true;
    canvas.setPointerCapture(ev.pointerId);
    sendTouch('down', ev);
  });
  canvas.addEventListener('pointermove', ev => {
    if (down) sendTouch('move', ev);
  });
  const up = ev => {
    if (!down) return;
    down = false;
    sendTouch('up', ev);
  };
  canvas.addEventListener('pointerup', up);
  canvas.addEventListener('pointercancel', up);
  canvas.addEventListener('pointerleave', up);
}
attachPointerHandlers();

// Side-panel wiring (Phase-6 super-sim panel) -------------------------------
// Surfaces optional telemetry/log frames the server may push:
//   {"type":"telemetry","wifi":{...},"sys":{...}}
//   {"type":"log","level":"I","tag":"app","msg":"..."}
// All fields are optional so older servers (which don't emit these) keep
// working unchanged.
const wifiState = document.getElementById('wifi-state');
const wifiSsid  = document.getElementById('wifi-ssid');
const wifiIp    = document.getElementById('wifi-ip');
const wifiRssi  = document.getElementById('wifi-rssi');
const sysHeap   = document.getElementById('sys-heap');
const sysUptime = document.getElementById('sys-uptime');
const sysTasks  = document.getElementById('sys-tasks');
const logsEl    = document.getElementById('logs');

const LOG_MAX = 200;
function appendLog(level, tag, msg) {
  const li = document.createElement('li');
  li.className = `log-${level || 'I'}`;
  const ts = new Date().toLocaleTimeString();
  li.textContent = `[${ts}] ${level || 'I'} ${tag || '?'}: ${msg || ''}`;
  logsEl.appendChild(li);
  while (logsEl.childElementCount > LOG_MAX) logsEl.removeChild(logsEl.firstChild);
  logsEl.scrollTop = logsEl.scrollHeight;
}

function applyTelemetry(msg) {
  if (msg.wifi) {
    if (msg.wifi.state !== undefined) wifiState.textContent = msg.wifi.state;
    if (msg.wifi.ssid  !== undefined) wifiSsid.textContent  = msg.wifi.ssid;
    if (msg.wifi.ip    !== undefined) wifiIp.textContent    = msg.wifi.ip;
    if (msg.wifi.rssi  !== undefined) wifiRssi.textContent  = `${msg.wifi.rssi} dBm`;
  }
  if (msg.sys) {
    if (msg.sys.heap   !== undefined) sysHeap.textContent   = `${msg.sys.heap} B`;
    if (msg.sys.uptime !== undefined) sysUptime.textContent = `${msg.sys.uptime} s`;
    if (msg.sys.tasks  !== undefined) sysTasks.textContent  = `${msg.sys.tasks}`;
  }
}

document.getElementById('logs-clear').addEventListener('click', () => {
  while (logsEl.firstChild) logsEl.removeChild(logsEl.firstChild);
});

document.getElementById('btn-screenshot').addEventListener('click', () => {
  canvas.toBlob(blob => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `framebuffer-${Date.now()}.png`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, 'image/png');
});

document.getElementById('btn-reset').addEventListener('click', () => {
  appendLog('W', 'panel', 'reset requested (stub — wire to QEMU later)');
});

// Test hook (CDP/Playwright). Safe to leave in production: read-only handles.
window.__superSim = { applyTelemetry, appendLog };

// FPS counter ---------------------------------------------------------------
let frameCount = 0;
setInterval(() => {
  fpsEl.textContent = `${frameCount} fps`;
  frameCount = 0;
}, 1000);

// Pending fb_update header awaiting its binary payload ----------------------
let pendingHeader = null;

// RGB565 LE → RGBA8888 (bit-replicated; matches tools/decode-fb.py) ---------
function rgb565ToRgba(payload, w, h) {
  const out = new Uint8ClampedArray(w * h * 4);
  const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
  for (let i = 0, o = 0; i < w * h; i++, o += 4) {
    const px = view.getUint16(i * 2, /* littleEndian */ true);
    const r5 = (px >> 11) & 0x1f;
    const g6 = (px >> 5) & 0x3f;
    const b5 = px & 0x1f;
    out[o + 0] = (r5 << 3) | (r5 >> 2);
    out[o + 1] = (g6 << 2) | (g6 >> 4);
    out[o + 2] = (b5 << 3) | (b5 >> 2);
    out[o + 3] = 255;
  }
  return out;
}

function applyUpdate(header, payload) {
  if (header.format !== 'RGB565' || header.encoding !== 'raw') {
    console.warn('Unsupported format/encoding', header);
    return;
  }
  const expected = header.h * header.stride;
  if (payload.byteLength !== expected) {
    console.warn(`payload size mismatch: got ${payload.byteLength} expected ${expected}`);
    return;
  }
  const rgba = rgb565ToRgba(payload, header.w, header.h);
  const imgData = new ImageData(rgba, header.w, header.h);
  ctx.putImageData(imgData, header.x, header.y);
  frameCount++;
  lastUpdateEl.textContent = `last update: x=${header.x} y=${header.y} w=${header.w} h=${header.h}`;
}

function handleInit(msg) {
  canvas.width = msg.width;
  canvas.height = msg.height;
  // Keep the displayed CSS size near 4× without exceeding viewport bounds.
  const targetW = Math.min(msg.width * 4, window.innerWidth - 40);
  const scale = targetW / msg.width;
  canvas.style.width  = `${msg.width  * scale}px`;
  canvas.style.height = `${msg.height * scale}px`;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  resolutionEl.textContent = `${msg.width}×${msg.height} ${msg.format}`;
}

function setStatus(state, text) {
  statusEl.className = `status ${state}`;
  statusEl.textContent = text;
}

function connect() {
  const params = new URLSearchParams(location.search);
  const wsPort = params.get('ws') || '7788';
  const wsHost = params.get('host') || location.hostname || '127.0.0.1';
  const wsUrl = `ws://${wsHost}:${wsPort}`;
  setStatus('connecting', `connecting to ${wsUrl}…`);
  const ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';
  activeWs = ws;

  ws.addEventListener('open', () => setStatus('connected', `connected ${wsUrl}`));
  ws.addEventListener('error', () => setStatus('error', 'WebSocket error'));
  ws.addEventListener('close', () => {
    if (activeWs === ws) activeWs = null;
    setStatus('error', 'disconnected — reconnect in 2 s');
    setTimeout(connect, 2000);
  });

  ws.addEventListener('message', ev => {
    if (typeof ev.data === 'string') {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) {
        console.warn('bad text frame', ev.data); return;
      }
      if (msg.type === 'fb_init') { handleInit(msg); }
      else if (msg.type === 'fb_update') { pendingHeader = msg; }
      else if (msg.type === 'telemetry') { applyTelemetry(msg); }
      else if (msg.type === 'log') { appendLog(msg.level, msg.tag, msg.msg); }
      else { console.warn('unknown msg', msg); }
    } else {
      // Binary
      if (!pendingHeader) {
        console.warn('binary frame without preceding fb_update header');
        return;
      }
      applyUpdate(pendingHeader, new Uint8Array(ev.data));
      pendingHeader = null;
    }
  });
}

connect();
