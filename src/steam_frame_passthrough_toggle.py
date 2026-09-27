#!/usr/bin/env python3
"""Steam Frame Dock passthrough tri-state controller (stdlib only)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


LOG = logging.getLogger("steam-frame-passthrough-toggle")
ACTION_ID = 605400007
API_HOST = "127.0.0.1"
API_PORT = 27655
CEF_PORT = 8081
ROOT = Path(__file__).resolve().parent.parent
HELPER_DIR = ROOT / "vendor" / "frame-passthrough-shortcuts"
HELPER = HELPER_DIR / "frame-passthrough-shortcuts"


class CameraControl:
    def __init__(self, helper: Path = HELPER):
        self.helper = helper
        self._detected = False
        self._missing_since: float | None = None
        self._next_detection = 0.0

    def rgb_available(self) -> bool:
        if override := os.getenv("SF_RGB_AVAILABLE"):
            return override == "1"
        now = time.monotonic()
        if now < self._next_detection:
            return self._detected
        self._next_detection = now + 0.25
        try:
            import array
            import fcntl

            found_sensor = False
            valid_read = False
            connected = False
            for name_file in Path("/sys/class/video4linux").glob("video*/name"):
                if not name_file.read_text(errors="replace").startswith("arcimx616 "):
                    continue
                found_sensor = True
                descriptor = -1
                try:
                    descriptor = os.open(
                        Path("/dev") / name_file.parent.name,
                        os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
                    )
                    value = array.array("I", [0])
                    fcntl.ioctl(descriptor, 0x800456C1, value, True)
                    valid_read = True
                    connected = connected or value[0] == 1
                except OSError:
                    continue
                finally:
                    if descriptor >= 0:
                        os.close(descriptor)
            if found_sensor and not valid_read:
                return self._detected
            if connected:
                self._detected = True
                self._missing_since = None
            elif self._detected:
                self._missing_since = self._missing_since or now
                if now - self._missing_since >= 2:
                    self._detected = False
        except (ImportError, OSError):
            return self._detected
        return self._detected

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.helper), *arguments, "--config", str(HELPER_DIR / "config.json")],
            cwd=HELPER_DIR,
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )

    def source(self) -> str | None:
        result = self._run("--doctor")
        output = result.stdout + result.stderr
        if "Steam Frame camera source: RGB" in output:
            return "color"
        if "Steam Frame camera source: monochrome" in output:
            return "mono"
        return None

    def set_source(self, source: str, retry_seconds: float = 3.0) -> str:
        action = "rgb" if source == "color" else "monochrome"
        deadline = time.monotonic() + retry_seconds
        last_output = ""
        while True:
            result = self._run("--action", action)
            last_output = (result.stdout + result.stderr).strip()
            if result.returncode == 0:
                if "not detected" in last_output:
                    return "mono"
                if "source set to RGB" in last_output:
                    self._detected = True
                    self._missing_since = None
                    return "color"
                if "source set to monochrome" in last_output:
                    return "mono"
                return source
            if time.monotonic() >= deadline:
                raise RuntimeError(last_output or f"camera helper exited {result.returncode}")
            time.sleep(0.2)


class TriStateController:
    """Cycle off -> color (when present) -> mono -> off."""

    def __init__(self, camera: CameraControl):
        self.camera = camera
        self.mode = "off"
        self.lock = threading.Lock()

    def cycle(self, room_view_active: bool) -> dict[str, object]:
        with self.lock:
            if not room_view_active:
                # SteamVR's own action is authoritative: try RGB after the
                # renderer opens, then stay monochrome when it reports that no
                # accessory is connected.
                self.mode = "mono"
                return {"state": "mono", "invokeNative": True, "postSource": "color"}

            source = self.camera.source() or self.mode
            if source == "color":
                self.camera.set_source("mono")
                self.mode = "mono"
                return {"state": "mono", "invokeNative": False}

            self.mode = "off"
            return {"state": "off", "invokeNative": True}

    def activate_source(self, source: str) -> dict[str, object]:
        if source not in {"color", "mono"}:
            raise ValueError("invalid camera source")
        with self.lock:
            if source == "color" and not self.camera.rgb_available():
                LOG.info("RGB ioctl detection unavailable; asking SteamVR directly")
            actual = self.camera.set_source(source)
            self.mode = actual
            return {"state": actual}

    def state(self, room_view_active: bool) -> dict[str, object]:
        with self.lock:
            available = self.camera.rgb_available()
            if not room_view_active:
                self.mode = "off"
            elif self.mode == "off":
                self.mode = self.camera.source() or ("color" if available else "mono")
            if self.mode == "color":
                available = True
            return {"state": self.mode, "rgbAvailable": available}


class ApiHandler(BaseHTTPRequestHandler):
    controller: TriStateController

    def _json(self, status: int, value: object) -> None:
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            active = "active=1" in self.path
            self._json(200, self.controller.state(active))
        except Exception as error:  # hardware boundary
            LOG.exception("state request failed")
            self._json(500, {"error": str(error)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/cycle":
                response = self.controller.cycle(bool(request.get("active")))
            elif self.path == "/source":
                response = self.controller.activate_source(str(request.get("source")))
            else:
                self._json(404, {"error": "not found"})
                return
            self._json(200, response)
        except Exception as error:  # hardware boundary
            LOG.exception("control request failed")
            self._json(500, {"error": str(error)})

    def log_message(self, format: str, *args: object) -> None:
        LOG.debug(format, *args)


INJECT_SCRIPT = r"""
(() => {
  const VERSION = 4;
  if (window.__sfPassthroughToggle?.version === VERSION) return "already installed";
  window.__sfPassthroughToggle?.dispose?.();

  const API = "http://127.0.0.1:27655";
  const ACTION_ID = 605400007;
  let mode = "off";
  let bypass = false;

  function actionFor(button) {
    const key = Object.keys(button).find(key => key.startsWith("__reactFiber"));
    for (let fiber = key && button[key], depth = 0; fiber && depth < 16; fiber = fiber.return, depth++) {
      const action = fiber.memoizedProps?.action;
      if (action?.action_id === ACTION_ID) return action;
    }
  }

  function button() {
    return [...document.querySelectorAll('[role="button"]')].find(actionFor);
  }

  function decorate() {
    const target = button();
    if (!target) return;
    const visibleMode = actionFor(target)?.active ? mode : "off";
    target.dataset.sfPassthroughState = visibleMode;
    const svg = target.querySelector("svg");
    if (!svg) return;
    for (const path of svg.querySelectorAll("path")) {
      if (!path.dataset.sfOriginalFill) path.dataset.sfOriginalFill = path.getAttribute("fill") || "currentColor";
      path.setAttribute("fill", visibleMode === "color" ? "#a855f7" : path.dataset.sfOriginalFill);
    }
  }

  async function post(path, body) {
    const response = await fetch(API + path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
    return value;
  }

  async function click(event) {
    const target = button();
    if (bypass || !target || !target.contains(event.target)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      const result = await post("/cycle", {active: !!actionFor(target)?.active});
      mode = result.state;
      decorate();
      if (result.invokeNative) {
        bypass = true;
        target.click();
        bypass = false;
      }
      if (result.postSource) {
        setTimeout(async () => {
          try {
            const selected = await post("/source", {source: result.postSource});
            mode = selected.state;
            decorate();
          } catch (error) { console.error("Steam Frame passthrough source:", error); }
        }, 250);
      }
    } catch (error) {
      console.error("Steam Frame passthrough toggle:", error);
    }
  }

  async function sync() {
    const active = !!actionFor(button())?.active;
    try {
      const response = await fetch(`${API}/state?active=${active ? 1 : 0}`);
      if (!response.ok) return;
      mode = (await response.json()).state;
      decorate();
    } catch (_) {}
  }

  window.addEventListener("click", click, true);
  const observer = new MutationObserver(decorate);
  observer.observe(document.documentElement, {childList: true, subtree: true});
  const timer = setInterval(sync, 1000);
  window.__sfPassthroughToggle = {version: VERSION, dispose() { window.removeEventListener("click", click, true); observer.disconnect(); clearInterval(timer); }};
  sync();
  return "installed";
})()
"""


def _read_http_headers(sock: socket.socket) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed during WebSocket handshake")
        data += chunk
    return data


def _send_websocket_text(sock: socket.socket, text: str) -> None:
    payload = text.encode()
    mask = secrets.token_bytes(4)
    length = len(payload)
    header = bytearray([0x81])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.extend((0xFE, *struct.pack("!H", length)))
    else:
        header.extend((0xFF, *struct.pack("!Q", length)))
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("WebSocket closed")
        data += chunk
    return data


def _recv_websocket_text(sock: socket.socket) -> str:
    first, second = _recv_exact(sock, 2)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    mask = _recv_exact(sock, 4) if second & 0x80 else b""
    payload = _recv_exact(sock, length)
    if mask:
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    if first & 0x0F == 8:
        raise ConnectionError("WebSocket closed")
    return payload.decode(errors="replace")


def evaluate(websocket_url: str, expression: str) -> str:
    parsed = urlparse(websocket_url)
    key = base64.b64encode(secrets.token_bytes(16)).decode()
    with socket.create_connection((parsed.hostname, parsed.port), timeout=5) as sock:
        request = (
            f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode())
        headers = _read_http_headers(sock)
        if not headers.startswith(b"HTTP/1.1 101"):
            raise ConnectionError(headers.split(b"\r\n", 1)[0].decode())
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        if expected.lower() not in headers.lower():
            raise ConnectionError("invalid WebSocket accept key")
        _send_websocket_text(sock, json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}))
        while True:
            response = json.loads(_recv_websocket_text(sock))
            if response.get("id") == 1:
                if "error" in response:
                    raise RuntimeError(response["error"].get("message", "CDP evaluation failed"))
                result = response.get("result", {}).get("result", {})
                if result.get("subtype") == "error":
                    raise RuntimeError(result.get("description", "JavaScript injection failed"))
                return str(result.get("value", ""))


def is_dock_target(target: dict[str, object]) -> bool:
    query = parse_qs(urlparse(str(target.get("url", ""))).query)
    return query.get("vrOverlayKey") == ["valve.steam.gamepadui.bar"]


def inject_once() -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{CEF_PORT}/json", timeout=3) as response:
        targets = json.load(response)
    target = next(item for item in targets if is_dock_target(item))
    return evaluate(target["webSocketDebuggerUrl"], INJECT_SCRIPT)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    if not HELPER.is_file():
        raise SystemExit(f"missing camera helper: {HELPER}")
    ApiHandler.controller = TriStateController(CameraControl())
    server = ThreadingHTTPServer((API_HOST, API_PORT), ApiHandler)
    threading.Thread(target=server.serve_forever, name="local-api", daemon=True).start()
    LOG.info("local control API listening on %s:%d", API_HOST, API_PORT)
    last_result = None
    while True:
        try:
            result = inject_once()
            if result != last_result:
                LOG.info("Dock injection: %s", result)
                last_result = result
        except (OSError, ValueError, StopIteration) as error:
            LOG.debug("waiting for Steam CEF: %s", error)
        except Exception:
            LOG.exception("Dock injection failed")
        time.sleep(2)


if __name__ == "__main__":
    main()
