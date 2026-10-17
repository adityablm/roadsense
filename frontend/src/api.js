// Everything the website needs from the backend goes through this file.
//
// VITE_API_URL is the backend's address. On your laptop it's http://127.0.0.1:8000.
// After deploying, it's your Render address (set in Vercel's settings).
export const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

// Free servers fall asleep when nobody uses them, and take up to a minute to wake.
// If a request is slow, we tell the page so it can show a "waking up" message.
const SLOW_AFTER_MS = 2500;
const slowListeners = new Set();
let slowRequests = 0;

export function onSlowChange(listener) {
  slowListeners.add(listener);
  return () => slowListeners.delete(listener);
}

function setSlow(delta) {
  slowRequests = Math.max(0, slowRequests + delta);
  slowListeners.forEach((fn) => fn(slowRequests > 0));
}

async function request(path, { timeoutMs = 120000, ...options } = {}) {
  let markedSlow = false;
  const controller = new AbortController();
  const giveUp = setTimeout(() => controller.abort(), timeoutMs);
  const timer = setTimeout(() => {
    markedSlow = true;
    setSlow(+1);
  }, SLOW_AFTER_MS);
  try {
    const response = await fetch(API_URL + path, { ...options, signal: controller.signal });
    const isJson = (response.headers.get("content-type") || "").includes("application/json");
    const body = isJson ? await response.json() : null;
    if (!response.ok) {
      const detail = body && body.detail;
      const message = typeof detail === "string" ? detail : `The server answered with error ${response.status}.`;
      throw new Error(message);
    }
    return body;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(`No answer from the server after ${Math.round(timeoutMs / 1000)} seconds. Try again in a minute.`);
    }
    if (error instanceof TypeError) {
      // fetch() itself failed: the server is off or the address is wrong.
      throw new Error(`Can't reach the RoadSense server at ${API_URL}. Is the backend running?`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
    clearTimeout(giveUp);
    if (markedSlow) setSlow(-1);
  }
}

export const imageUrl = (path) => API_URL + path;

export function getHotspots(bounds) {
  const params = new URLSearchParams(bounds);
  return request(`/api/hotspots?${params}`);
}

export const getHotspot = (id) => request(`/api/hotspots/${id}`);
export const getStats = () => request("/api/stats");

export function draftLetter(id, lang, refresh = false) {
  // The server itself gives up on Gemini after about 70 seconds; this is a safety net on top.
  return request(`/api/hotspots/${id}/complaint?lang=${lang}${refresh ? "&refresh=true" : ""}`,
                 { method: "POST", timeoutMs: 90000 });
}

export function sendReport({ file, lat, lng }) {
  const form = new FormData();
  form.append("image", file);
  if (lat != null && lng != null) {
    form.append("lat", String(lat));
    form.append("lng", String(lng));
  }
  form.append("reporter_id", reporterId());
  return request("/api/reports", { method: "POST", body: form });
}

// An anonymous id for this browser, so the server can tell "3 photos from 3 people"
// apart from "3 photos from 1 person". It is random and contains nothing personal.
let memoryId = null;
function reporterId() {
  try {
    let id = localStorage.getItem("roadsense-reporter");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("roadsense-reporter", id);
    }
    return id;
  } catch {
    memoryId = memoryId || Math.random().toString(36).slice(2);
    return memoryId;
  }
}
