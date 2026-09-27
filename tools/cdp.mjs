#!/usr/bin/env node

const [host = "frame", targetNeedle = "gamepadui.bar", ...expressionParts] = process.argv.slice(2);
const expression = expressionParts.join(" ") || "document.body.innerText";

const targets = await fetch(`http://${host}:8081/json`).then((response) => {
  if (!response.ok) throw new Error(`CEF target list returned HTTP ${response.status}`);
  return response.json();
});
const target = targets.find((item) => `${item.title} ${item.url}`.includes(targetNeedle));
if (!target) throw new Error(`No CEF target matching ${JSON.stringify(targetNeedle)}`);

const socket = new WebSocket(target.webSocketDebuggerUrl);
const result = await new Promise((resolve, reject) => {
  const timeout = setTimeout(() => reject(new Error("CDP evaluation timed out")), 10_000);
  socket.addEventListener("open", () => socket.send(JSON.stringify({
    id: 1,
    method: "Runtime.evaluate",
    params: { expression, awaitPromise: true, returnByValue: true },
  })));
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id !== 1) return;
    clearTimeout(timeout);
    message.error ? reject(new Error(message.error.message)) : resolve(message.result.result);
  });
  socket.addEventListener("error", reject);
});

socket.close();
if (result.subtype === "error") throw new Error(result.description);
console.log(typeof result.value === "string" ? result.value : JSON.stringify(result.value, null, 2));
