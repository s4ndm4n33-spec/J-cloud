import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const client = axios.create({
  baseURL: API,
  withCredentials: true,
});

export async function exchangeSession(session_id) {
  const r = await client.post("/auth/session", { session_id });
  return r.data;
}
export async function me() {
  const r = await client.get("/auth/me");
  return r.data;
}
export async function logout() {
  await client.post("/auth/logout");
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
export async function aiRefine(payload) {
  return (await client.post("/ai/refine", payload)).data;
}
export async function aiGovernance(payload) {
  return (await client.post("/ai/governance", payload)).data;
}
