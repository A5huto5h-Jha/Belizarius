"use strict";
const electron = require("electron");
electron.contextBridge.exposeInMainWorld("electronAPI", {
  onWakeWord: (callback) => {
    const listener = (_event, phrase) => {
      callback(phrase);
    };
    electron.ipcRenderer.on("voice:wake-word", listener);
    return () => electron.ipcRenderer.removeListener("voice:wake-word", listener);
  },
  onMainProcessMessage: (callback) => {
    const listener = (_event, message) => {
      callback(message);
    };
    electron.ipcRenderer.on("main-process-message", listener);
    return () => electron.ipcRenderer.removeListener("main-process-message", listener);
  },
  onVoiceStatus: (callback) => {
    const listener = (_event, status) => {
      callback(status);
    };
    electron.ipcRenderer.on("voice:status", listener);
    return () => electron.ipcRenderer.removeListener("voice:status", listener);
  },
  onVoiceOutput: (callback) => {
    const listener = (_event, text) => {
      callback(text);
    };
    electron.ipcRenderer.on("voice:output", listener);
    return () => electron.ipcRenderer.removeListener("voice:output", listener);
  },
  onVoiceInput: (callback) => {
    const listener = (_event, text) => {
      callback(text);
    };
    electron.ipcRenderer.on("voice:input", listener);
    return () => electron.ipcRenderer.removeListener("voice:input", listener);
  },
  onActivity: (callback) => {
    const listener = (_event, event) => {
      callback(event);
    };
    electron.ipcRenderer.on("activity:event", listener);
    return () => electron.ipcRenderer.removeListener("activity:event", listener);
  },
  setVisibilityMode: (mode) => electron.ipcRenderer.invoke("ui:set-visibility-mode", mode),
  stopConversation: () => electron.ipcRenderer.invoke("voice:stop-conversation")
});
