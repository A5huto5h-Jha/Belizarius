import { app, BrowserWindow } from "electron";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
const __dirname$1 = path.dirname(fileURLToPath(import.meta.url));
process.env.APP_ROOT = path.join(__dirname$1, "..");
const VITE_DEV_SERVER_URL = process.env["VITE_DEV_SERVER_URL"];
const MAIN_DIST = path.join(process.env.APP_ROOT, "dist-electron");
const RENDERER_DIST = path.join(process.env.APP_ROOT, "dist");
process.env.VITE_PUBLIC = VITE_DEV_SERVER_URL ? path.join(process.env.APP_ROOT, "public") : RENDERER_DIST;
let win = null;
let voiceProcess = null;
function createWindow() {
  win = new BrowserWindow({
    width: 300,
    height: 300,
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    resizable: false,
    hasShadow: false,
    alwaysOnTop: true,
    icon: path.join(process.env.VITE_PUBLIC, "electron-vite.svg"),
    webPreferences: {
      preload: path.join(__dirname$1, "preload.mjs")
    }
  });
  win.webContents.on("did-finish-load", () => {
    win == null ? void 0 : win.webContents.send("main-process-message", (/* @__PURE__ */ new Date()).toLocaleString());
  });
  if (VITE_DEV_SERVER_URL) {
    win.loadURL(VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(RENDERER_DIST, "index.html"));
  }
  win.on("closed", () => {
    win = null;
  });
}
function startVoiceListener() {
  var _a, _b;
  console.log("[Belizarius] Attempting to start Python...");
  console.log("[Belizarius] App path:", app.getAppPath());
  if (voiceProcess && voiceProcess.exitCode === null && !voiceProcess.killed) {
    return;
  }
  const projectRoot = app.getAppPath();
  const pythonPath = path.join(
    projectRoot,
    "voice_engine",
    ".venv",
    "Scripts",
    "python.exe"
  );
  const listenerPath = path.join(
    projectRoot,
    "voice_engine",
    "wake_sherpa.py"
  );
  console.log("[Belizarius] Python path:", pythonPath);
  console.log("[Belizarius] Listener path:", listenerPath);
  voiceProcess = spawn(pythonPath, ["-u", listenerPath], {
    cwd: projectRoot,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"]
  });
  let stdoutBuffer = "";
  (_a = voiceProcess.stdout) == null ? void 0 : _a.on("data", (data) => {
    stdoutBuffer += data.toString();
    const lines = stdoutBuffer.split(/\r?\n/);
    stdoutBuffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("WAKE_WORD:")) {
        createWindow();
        const phrase = line.slice("WAKE_WORD:".length).trim();
        win == null ? void 0 : win.webContents.send("voice:wake-word", phrase);
      } else if (line.trim()) {
        console.log("[Voice engine]", line);
      }
    }
  });
  (_b = voiceProcess.stderr) == null ? void 0 : _b.on("data", (data) => {
    console.error("[Voice engine]", data.toString());
  });
  voiceProcess.on("error", (error) => {
    console.error("[Voice engine failed to start]", error);
  });
  voiceProcess.on("exit", (code) => {
    console.log("[Belizarius] Python exit code:", code);
    console.log("[Voice engine exited]", code);
    voiceProcess = null;
  });
}
function stopVoiceListener() {
  if (voiceProcess) {
    voiceProcess.kill();
    voiceProcess = null;
  }
}
app.whenReady().then(() => {
  console.log("[Belizarius] Electron main process is running");
  startVoiceListener();
});
app.on("before-quit", stopVoiceListener);
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
export {
  MAIN_DIST,
  RENDERER_DIST,
  VITE_DEV_SERVER_URL
};
