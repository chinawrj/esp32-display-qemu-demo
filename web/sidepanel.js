// Side-panel wiring for the super-sim view (Wi-Fi, system, logs, controls).
//
// Surfaces optional WebSocket frame types pushed by the server:
//   {"type":"telemetry","wifi":{...},"sys":{...}}
//   {"type":"log","level":"I","tag":"app","msg":"..."}
// Older servers that only emit fb_init/fb_update keep working unchanged.
//
// The Screenshot button captures the supplied canvas as a PNG download.

const LOG_MAX = 200;

export function initSidePanel(canvas) {
  const wifiState = document.getElementById('wifi-state');
  const wifiSsid  = document.getElementById('wifi-ssid');
  const wifiIp    = document.getElementById('wifi-ip');
  const wifiRssi  = document.getElementById('wifi-rssi');
  const sysHeap   = document.getElementById('sys-heap');
  const sysUptime = document.getElementById('sys-uptime');
  const sysTasks  = document.getElementById('sys-tasks');
  const logsEl    = document.getElementById('logs');

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

  return { applyTelemetry, appendLog };
}
