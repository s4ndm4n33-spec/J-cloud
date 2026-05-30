// Client-side LLM caller for user's local / OpenAI-compatible endpoints.
// Browser → user's localhost works because CORS is local-machine-permissive
// (Ollama, LM Studio, vLLM all accept it by default).

import axios from "axios";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

/**
 * Call an OpenAI-compatible /v1/chat/completions endpoint from the browser.
 * Works with Ollama, LM Studio, vLLM, llama.cpp server, OpenAI itself, etc.
 */
export async function callLocalChat({ url, model, apiKey, system, user, timeout = 120000 }) {
  const t0 = performance.now();
  const headers = { "Content-Type": "application/json" };
  if (apiKey) headers["Authorization"] = `Bearer ${apiKey}`;
  const messages = [];
  if (system) messages.push({ role: "system", content: system });
  messages.push({ role: "user", content: user });
  const r = await axios.post(
    `${url.replace(/\/$/, "")}/chat/completions`,
    { model, messages, stream: false, temperature: 0.7 },
    { headers, timeout }
  );
  const choice = r.data?.choices?.[0]?.message?.content || "";
  return { content: choice, ms: Math.round(performance.now() - t0), raw: r.data };
}

export async function listLocalEndpoints() {
  return (await axios.get(`${API}/settings/local_endpoints`, { withCredentials: true })).data.endpoints;
}
export async function createLocalEndpoint(payload) {
  return (await axios.post(`${API}/settings/local_endpoints`, payload, { withCredentials: true })).data;
}
export async function deleteLocalEndpoint(id) {
  return (await axios.delete(`${API}/settings/local_endpoints/${id}`, { withCredentials: true })).data;
}
export async function getLocalEndpointKey(id) {
  return (await axios.get(`${API}/settings/local_endpoints/${id}/key`, { withCredentials: true })).data.api_key;
}

/** Find the first endpoint matching role + task. */
export async function pickEndpoint(role, task) {
  const list = await listLocalEndpoints();
  return list.find((e) => e.role === role && (e.tasks || []).includes(task)) || null;
}

/** Try local endpoint (if configured) with given role+task. Returns null if none. */
export async function tryLocal({ role, task, system, user }) {
  const ep = await pickEndpoint(role, task);
  if (!ep) return null;
  let apiKey = "";
  if (ep.has_api_key) {
    try { apiKey = await getLocalEndpointKey(ep.endpoint_id); } catch {/* noop */}
  }
  try {
    const r = await callLocalChat({ url: ep.url, model: ep.model, apiKey, system, user });
    return {
      content: r.content,
      ms: r.ms,
      step_used: { source: "local", provider: ep.nickname, model: ep.model },
    };
  } catch (e) {
    return { error: e?.response?.data?.error?.message || e.message, endpoint: ep };
  }
}

// Server-side agent tool relay used when running the loop client-side
export async function execTool(projectId, name, args) {
  return (
    await axios.post(
      `${API}/projects/${projectId}/tools/execute`,
      { name, args },
      { withCredentials: true, timeout: 60000 }
    )
  ).data;
}

export async function getAgentSpec() {
  return (await axios.get(`${API}/agent/spec`, { withCredentials: true })).data;
}

/**
 * Run the agent loop entirely client-side against a local LLM endpoint.
 * - LLM call goes browser → user's localhost (cloud backend never sees the model).
 * - Each tool call is dispatched to backend `/tools/execute` (server runs the side-effect on the workspace).
 */
export async function runLocalAgentLoop({ projectId, message, role = "primary", task = "agent",
                                          maxSteps = 6, onStep }) {
  const ep = await pickEndpoint(role, task);
  if (!ep) return { error: "no_local_endpoint", steps: [] };
  let apiKey = "";
  if (ep.has_api_key) {
    try { apiKey = await getLocalEndpointKey(ep.endpoint_id); } catch {/* noop */}
  }
  const { system_prompt } = await getAgentSpec();

  const steps = [];
  let transcript = `[USER]\n${message}\n\n[J]\n`;

  const toolCallRe = /<tool_call>\s*(\{[\s\S]*?\})\s*<\/tool_call>/g;

  for (let i = 0; i < maxSteps; i++) {
    let llm;
    try {
      llm = await callLocalChat({ url: ep.url, model: ep.model, apiKey,
                                  system: system_prompt, user: transcript });
    } catch (e) {
      const errStep = { type: "assistant", text: `// local endpoint error: ${e?.response?.data?.error?.message || e.message}` };
      steps.push(errStep); onStep?.(errStep);
      return { steps, final: errStep.text, done_reason: "local_error",
               step_used: { source: "local", provider: ep.nickname, model: ep.model } };
    }
    const reply = llm.content || "";
    const prose = reply.replace(toolCallRe, "").trim();
    const calls = [];
    let m;
    toolCallRe.lastIndex = 0;
    while ((m = toolCallRe.exec(reply)) !== null) {
      try {
        const obj = JSON.parse(m[1]);
        if (obj && obj.name) calls.push({ name: obj.name, args: obj.args || {} });
      } catch {/* skip malformed */}
    }

    const aStep = { type: "assistant", text: prose, raw: reply,
                    meta: { step_used: { source: "local", provider: ep.nickname, model: ep.model } } };
    steps.push(aStep); onStep?.(aStep);
    transcript += reply + "\n";

    if (!calls.length) {
      return { steps, final: prose, done_reason: "no_tool_calls",
               step_used: { source: "local", provider: ep.nickname, model: ep.model } };
    }

    let isDone = false;
    let askUserQ = null;
    for (const c of calls) {
      const r = await execTool(projectId, c.name, c.args);
      const tStep = { type: "tool", name: c.name, args: c.args, result: r.result };
      steps.push(tStep); onStep?.(tStep);
      transcript += `[TOOL RESULT — ${c.name}]\n${JSON.stringify(r.result).slice(0, 1500)}\n\n`;
      if (r.result?._done) { isDone = true; break; }
      if (r.result?._ask_user) { askUserQ = r.result.question; break; }
    }
    if (isDone || askUserQ) {
      const final = isDone ? (calls.find((c) => c.name === "done")?.args?.summary || "") : askUserQ;
      return { steps, final, done_reason: isDone ? "done_tool" : "awaiting_user",
               step_used: { source: "local", provider: ep.nickname, model: ep.model } };
    }
    transcript += "[J]\n";
  }
  return { steps, final: "// max_steps reached", done_reason: "max_steps_reached",
           step_used: { source: "local", provider: ep.nickname, model: ep.model } };
}
