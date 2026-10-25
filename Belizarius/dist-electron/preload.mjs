"use strict";
const electron = require("electron");
electron.contextBridge.exposeInMainWorld("electronAPI", {
  onWakeWord: (callback) => {
    const listener = (_event, phrase) => {
      callback(phrase);
    };
    electron.ipcRenderer.on("voice:wake-word", listener);
    return () => {
      electron.ipcRenderer.removeListener("voice:wake-word", listener);
    };
  },
  onMainProcessMessage: (callback) => {
    const listener = (_event, message) => {
      callback(message);
    };
    electron.ipcRenderer.on("main-process-message", listener);
    return () => {
      electron.ipcRenderer.removeListener("main-process-message", listener);
    };
  }
});
