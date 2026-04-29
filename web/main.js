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

  ws.addEventListener('open', () => setStatus('connected', `connected ${wsUrl}`));
  ws.addEventListener('error', () => setStatus('error', 'WebSocket error'));
  ws.addEventListener('close', () => {
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
