(() => {
  const $ = (id) => document.getElementById(id);
  const el = {
    video: $("video"), placeholder: $("placeholder"), camPill: $("camPill"), camText: $("camText"),
    fps: $("fps"), error: $("errorBar"), wheel: $("wheelGroup"), steerBar: $("steerBar"),
    direction: $("direction"), gesture: $("gesture"), gas: $("gasChip"), brake: $("brakeChip"),
    hand: $("handChip"), start: $("startBtn"), stop: $("stopBtn"), cal: $("calBtn"),
    game: $("gameName"), scheme: $("keyScheme"), sendKeys: $("sendKeys"),
    sens: $("sens"), sensOut: $("sensOut"), dz: $("dz"), dzOut: $("dzOut"),
    accel: $("accelGesture"), brakeG: $("brakeGesture"), keysDown: $("keysDown"),
    msg: $("msg"), sessions: $("sessions"),
  };

  let videoOn = false;
  let wasRunning = false;
  let settingsTimer = null;

  async function api(path, method = "GET", body) {
    const res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch (e) { /* ignore */ }
    return { ok: res.ok, data };
  }

  function showError(text) {
    el.error.textContent = text || "";
    el.error.classList.toggle("hidden", !text);
  }

  function setVideo(on) {
    if (on === videoOn) return;
    videoOn = on;
    if (on) {
      el.video.src = "/video_feed?t=" + Date.now();
      el.video.hidden = false;
      el.placeholder.style.display = "none";
    } else {
      el.video.removeAttribute("src");
      el.video.hidden = true;
      el.placeholder.style.display = "flex";
    }
  }

  function render(s) {
    const running = s.running;
    setVideo(running);

    const cam = s.camera_status;
    el.camPill.className = "pill " + (cam === "connected" ? "ok" : cam === "error" ? "err" : cam === "connecting" ? "wait" : "");
    el.camText.textContent = "Camera: " + cam;
    el.fps.textContent = Math.round(s.fps);
    showError(s.error);

    const st = s.steering;
    el.wheel.style.transform = `rotate(${(st.value * 90).toFixed(1)}deg)`;
    const pct = Math.min(1, Math.abs(st.value)) * 50;
    el.steerBar.style.width = pct + "%";
    el.steerBar.style.left = st.value < 0 ? (50 - pct) + "%" : "50%";
    el.direction.textContent = st.direction.toUpperCase();
    el.gesture.textContent = s.gesture.replace("_", " ");

    el.gas.className = "chip" + (s.accelerating ? " on-gas" : "");
    el.brake.className = "chip" + (s.braking ? " on-brake" : "");
    el.hand.className = "chip" + (s.hand_detected ? " on-hand" : "");

    el.start.disabled = running;
    el.stop.disabled = !running;
    el.cal.disabled = !running;
    for (const c of [el.game, el.scheme, el.sendKeys]) c.disabled = running;

    el.keysDown.textContent = "Keys held: " + (s.keys_down.length ? s.keys_down.join(", ") : "none");
    el.msg.textContent = s.message && s.message !== "Running" ? s.message : "";

    if (wasRunning && !running) loadSessions();
    wasRunning = running;
  }

  async function poll() {
    try {
      const { data } = await api("/api/status");
      render(data);
    } catch (e) {
      showError("Lost connection to the server");
    }
    setTimeout(poll, 100);
  }

  async function loadSessions() {
    const { data } = await api("/api/sessions");
    if (!Array.isArray(data) || data.length === 0) {
      el.sessions.innerHTML = '<tr><td colspan="4" class="muted">No sessions yet</td></tr>';
      return;
    }
    el.sessions.innerHTML = "";
    for (const row of data) {
      const tr = document.createElement("tr");
      const mins = Math.floor(row.session_duration / 60);
      const secs = Math.round(row.session_duration % 60);
      for (const text of [row.game_name || "-", `${mins}m ${secs}s`, row.steering_events, row.created_at]) {
        const td = document.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      }
      el.sessions.appendChild(tr);
    }
  }

  async function loadSettings() {
    const { data } = await api("/api/settings");
    el.sens.value = data.steering_sensitivity;
    el.sensOut.textContent = Number(data.steering_sensitivity).toFixed(1);
    el.dz.value = data.dead_zone;
    el.dzOut.textContent = Number(data.dead_zone).toFixed(2);
    el.accel.value = data.acceleration_gesture;
    el.brakeG.value = data.brake_gesture;
  }

  function saveSettingsSoon() {
    clearTimeout(settingsTimer);
    settingsTimer = setTimeout(async () => {
      const { ok, data } = await api("/api/settings", "POST", {
        steering_sensitivity: Number(el.sens.value),
        dead_zone: Number(el.dz.value),
        acceleration_gesture: el.accel.value,
        brake_gesture: el.brakeG.value,
      });
      if (!ok) { el.msg.textContent = data.error || "Could not save settings"; loadSettings(); }
    }, 250);
  }

  el.sens.addEventListener("input", () => { el.sensOut.textContent = Number(el.sens.value).toFixed(1); saveSettingsSoon(); });
  el.dz.addEventListener("input", () => { el.dzOut.textContent = Number(el.dz.value).toFixed(2); saveSettingsSoon(); });
  el.accel.addEventListener("change", saveSettingsSoon);
  el.brakeG.addEventListener("change", saveSettingsSoon);

  el.start.addEventListener("click", async () => {
    el.start.disabled = true;
    showError("");
    const { ok, data } = await api("/api/start", "POST", {
      game_name: el.game.value, key_scheme: el.scheme.value, send_keys: el.sendKeys.checked,
    });
    if (!ok) { showError(data.error || "Could not start"); el.start.disabled = false; }
  });
  el.stop.addEventListener("click", () => api("/api/stop", "POST"));
  el.cal.addEventListener("click", () => api("/api/calibrate", "POST"));

  loadSettings();
  loadSessions();
  poll();
})();
