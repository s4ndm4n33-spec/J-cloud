import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const TOKEN_KEY = "gauntlet_session_token";

export function getStoredToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setStoredToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* private mode */ }
}

const client = axios.create({
  baseURL: API,
  withCredentials: true,
});

// Attach Bearer fallback for mobile / blocked-3p-cookies scenarios.
client.interceptors.request.use((config) => {
  const t = getStoredToken();
  if (t) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${t}`;
  }
  return config;
});

export async function exchangeSession(session_id) {
  const r = await client.post("/auth/session", { session_id });
  if (r.data?.session_token) setStoredToken(r.data.session_token);
  return r.data;
}
export async function me() {
  const r = await client.get("/auth/me");
  return r.data;
}
export async function logout() {
  try { await client.post("/auth/logout"); } finally { setStoredToken(null); }
}

export async function listProjects() {
  return (await client.get("/projects")).data;
}
export async function createProject(name) {
  return (await client.post("/projects", { name })).data;
}
export async function projectTree(project_id) {
  return (await client.get(`/projects/${project_id}/tree`)).data;
}
export async function readFile(project_id, path) {
  return (await client.get(`/projects/${project_id}/file`, { params: { path } })).data;
}
export async function writeFile(project_id, path, content) {
  return (await client.post(`/projects/${project_id}/file`, { path, content })).data;
}
export async function deleteFile(project_id, path) {
  return (await client.delete(`/projects/${project_id}/file`, { params: { path } })).data;
}

export async function evaluateGauntlet(code, language) {
  return (await client.post("/gauntlet/evaluate", { code, language })).data;
}
export async function scanGovernance(code) {
  return (await client.post("/governance/scan", { code })).data;
}
export async function requestOverride(password, intent) {
  return (await client.post("/governance/override", { password, intent })).data;
}

export async function execCommand(project_id, command, override_token) {
  const r = await client.post(
    "/terminal/exec",
    { project_id, command, override_token },
    { validateStatus: () => true }
  );
  return { status: r.status, ...r.data };
}

export async function gitStatus(project_id) {
  return (await client.get(`/projects/${project_id}/git/status`)).data;
}
export async function gitCommit(project_id, message, paths) {
  return (await client.post(`/projects/${project_id}/git/commit`, { message, paths })).data;
}
export async function gitLog(project_id) {
  return (await client.get(`/projects/${project_id}/git/log`)).data;
}

export async function aiChat(payload) {
  return (await client.post("/ai/chat", payload)).data;
}
export async function aiAgent(payload) {
  return (await client.post("/ai/agent", payload, { timeout: 180000 })).data;
}
export async function aiRefine(payload) {
  return (await client.post("/ai/refine", payload)).data;
}
export async function aiGovernance(payload) {
  return (await client.post("/ai/governance", payload)).data;
}

// ----- GitHub -----
export async function githubStatus() {
  return (await client.get("/github/auth")).data;
}
export async function githubConnectPAT(token) {
  return (await client.post("/github/auth", { token })).data;
}
export async function githubDisconnect() {
  return (await client.delete("/github/auth")).data;
}
export async function githubRepos(page = 1) {
  return (await client.get("/github/repos", { params: { page } })).data;
}
export async function githubClone(payload) {
  return (await client.post("/github/clone", payload)).data;
}
export async function githubCreateRepo(project_id, payload) {
  return (await client.post(`/projects/${project_id}/github/create`, payload)).data;
}
export async function githubLink(project_id, payload) {
  return (await client.post(`/projects/${project_id}/github/link`, payload)).data;
}
export async function githubPush(project_id, branch) {
  return (await client.post(`/projects/${project_id}/github/push`, { branch })).data;
}
export async function githubPull(project_id, branch) {
  return (await client.post(`/projects/${project_id}/github/pull`, { branch })).data;
}
export async function githubPR(project_id, payload) {
  return (await client.post(`/projects/${project_id}/github/pr`, payload)).data;
}

// ----- Audit -----
export async function projectAudit(project_id) {
  return (await client.get(`/projects/${project_id}/audit`)).data;
}

// ----- Migration Log -----
export async function getMigrationLog(project_id) {
  return (await client.get(`/projects/${project_id}/migration_log`)).data;
}
export async function addMigrationEntry(project_id, payload) {
  return (await client.post(`/projects/${project_id}/migration_log`, payload)).data;
}

// ----- Upload / Download -----
export async function uploadFile(project_id, file, path) {
  const fd = new FormData();
  fd.append("file", file);
  return (
    await client.post(`/projects/${project_id}/upload`, fd, {
      params: { path: path || "" },
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 5 * 60 * 1000,
    })
  ).data;
}
export async function uploadZip(project_id, file, { dest = "", strip_root = true } = {}, onProgress) {
  const fd = new FormData();
  fd.append("file", file);
  return (
    await client.post(`/projects/${project_id}/upload_zip`, fd, {
      params: { dest, strip_root },
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 10 * 60 * 1000,
      onUploadProgress: onProgress,
    })
  ).data;
}
export async function uploadFolder(project_id, files, paths, onProgress) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  fd.append("paths", JSON.stringify(paths || []));
  return (
    await client.post(`/projects/${project_id}/upload_folder`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 10 * 60 * 1000,
      onUploadProgress: onProgress,
    })
  ).data;
}
export function downloadUrl(project_id, path) {
  return `${API}/projects/${project_id}/download?path=${encodeURIComponent(path)}`;
}
export function downloadZipUrl(project_id) {
  return `${API}/projects/${project_id}/download_zip`;
}

// ----- Agents -----
export async function listAgents() {
  return (await client.get("/agents")).data;
}
export async function createAgent(payload) {
  return (await client.post("/agents", payload)).data;
}
export async function deleteAgent(agent_id) {
  return (await client.delete(`/agents/${agent_id}`)).data;
}

// ----- Tutorial -----
export async function getTutorialState() {
  return (await client.get("/me/tutorial")).data;
}
export async function setTutorialState(completed) {
  return (await client.post("/me/tutorial", { completed })).data;
}

// ----- Private Mode -----
export async function getPrivateMode() {
  return (await client.get("/me/private-mode")).data;
}
export async function setPrivateMode(enabled) {
  return (await client.post("/me/private-mode", { enabled })).data;
}

// ----- Ollama / local server -----
export async function testOllama(base_url) {
  return (await client.post("/settings/keys/ollama/test", { base_url })).data;
}
export async function saveOllama(base_url, default_model) {
  return (await client.put("/settings/keys", {
    provider: "ollama", base_url, default_model,
  })).data;
}
