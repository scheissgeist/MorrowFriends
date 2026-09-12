(() => {
  "use strict";

  const SDK = window.LivekitClient;
  const claimPanel = document.querySelector("#claim-panel");
  const voicePanel = document.querySelector("#voice-panel");
  const partyInput = document.querySelector("#party-id");
  const claimStatus = document.querySelector("#claim-status");
  const connectionBadge = document.querySelector("#connection-badge");
  const voiceTitle = document.querySelector("#voice-title");
  const voiceStatus = document.querySelector("#voice-status");
  const positionStatus = document.querySelector("#position-status");
  const participantsRoot = document.querySelector("#participants");
  const audioRoot = document.querySelector("#audio-root");
  const talkButton = document.querySelector("#push-to-talk");
  const enableAudioButton = document.querySelector("#enable-audio");
  const bindButton = document.querySelector("#bind-button");
  const bindingValue = document.querySelector("#binding-value");
  const bindingStatus = document.querySelector("#binding-status");

  let room = null;
  let positionSocket = null;
  let positionToken = "";
  let participantIdentity = "";
  let mixByIdentity = new Map();
  let lastMixAt = 0;
  let positionReconnectDelay = 1000;
  let positionReconnectTimer = null;
  let joinRetryTimer = null;
  let joinRetryFailures = 0;
  let sessionActive = false;
  // Names already in the party when THIS page opened. A new character is the
  // one name that arrives after that. Guessing from the full list is how a
  // visitor claimed the host (Vicksauce, 2026-08-18).
  let namesAtOpen = null;
  let talking = false;
  let micQueue = Promise.resolve();
  let bindingCapture = false;
  let bindingPressed = false;
  let desktopPttSource = null;
  let spatialAudioContext = null;
  const audioGraphsByIdentity = new Map();
  const impulseByEnvironment = new Map();

  const acousticProfiles = {
    outdoors: {cutoff: 18000, wet: 0.025, seconds: 0.22, decay: 2.2},
    interior: {cutoff: 14500, wet: 0.08, seconds: 0.55, decay: 2.8},
    "large-interior": {cutoff: 12500, wet: 0.14, seconds: 1.15, decay: 3.2},
    cavern: {cutoff: 9500, wet: 0.18, seconds: 1.45, decay: 3.7},
  };
  const environmentLabels = {
    outdoors: "open air",
    interior: "interior",
    "large-interior": "large stone interior",
    cavern: "cavern",
  };

  const defaultBinding = {kind: "keyboard", code: "Space", label: "Space"};
  let pttBinding = loadBinding();

  const linkParams = new URLSearchParams(window.location.search);
  const partyFromLink = linkParams.get("party") || "";
  const codeFromLink = (linkParams.get("code") || "").trim().toUpperCase();
  const playerFromLink = (linkParams.get("player") || "").trim();
  // One server, one party. The field is hidden, so it must always hold a value
  // even when the page is opened without ?party= — otherwise every claim posts
  // an empty party_id and fails.
  const DEFAULT_PARTY = "broteam-morrowind";
  partyInput.value = partyFromLink || DEFAULT_PARTY;

  function validBinding(value) {
    if (!value || typeof value !== "object" || typeof value.label !== "string" ||
        value.label.length < 1 || value.label.length > 40) return false;
    if (value.kind === "keyboard") {
      return typeof value.code === "string" && /^[A-Za-z0-9]+$/.test(value.code) &&
        value.code.length <= 32;
    }
    return value.kind === "mouse" && Number.isInteger(value.button) &&
      value.button >= 0 && value.button <= 4;
  }

  function bindingFromLink() {
    // The launcher Settings key wins over this tab's last localStorage value.
    // Read the URL here: loadBinding() runs before linkParams is assigned.
    const params = new URLSearchParams(window.location.search);
    const kind = (params.get("ptt_kind") || "").trim();
    const value = (params.get("ptt") || "").trim();
    const label = (params.get("ptt_label") || "").trim();
    if (kind === "keyboard" && value) {
      const candidate = {kind: "keyboard", code: value, label: label || value};
      return validBinding(candidate) ? candidate : null;
    }
    if (kind === "mouse" && /^\d+$/.test(value)) {
      const candidate = {kind: "mouse", button: Number(value), label: label || value};
      return validBinding(candidate) ? candidate : null;
    }
    return null;
  }

  function loadBinding() {
    const fromLink = bindingFromLink();
    if (fromLink) return fromLink;
    try {
      const saved = JSON.parse(window.localStorage.getItem("morrowvoice.pttBinding") || "null");
      if (validBinding(saved)) return saved;
    } catch (_error) {
      // Private browsing or disabled storage simply falls back to Space.
    }
    return {...defaultBinding};
  }

  function saveBinding(binding) {
    pttBinding = binding;
    try {
      window.localStorage.setItem("morrowvoice.pttBinding", JSON.stringify(binding));
    } catch (_error) {
      // The binding still works for this tab when persistent storage is unavailable.
    }
    bindingValue.textContent = binding.label;
    talkButton.querySelector(".talk-key").textContent =
      `${binding.label} or hold this button`;
  }

  function keyboardLabel(event) {
    const named = {
      Space: "Space", Escape: "Escape", Enter: "Enter", Tab: "Tab",
      Backspace: "Backspace", Delete: "Delete", Insert: "Insert",
      Home: "Home", End: "End", PageUp: "Page Up", PageDown: "Page Down",
      ArrowUp: "Up Arrow", ArrowDown: "Down Arrow",
      ArrowLeft: "Left Arrow", ArrowRight: "Right Arrow",
      ShiftLeft: "Left Shift", ShiftRight: "Right Shift",
      ControlLeft: "Left Ctrl", ControlRight: "Right Ctrl",
      AltLeft: "Left Alt", AltRight: "Right Alt",
    };
    if (named[event.code]) return named[event.code];
    if (event.code.startsWith("Key")) return event.code.slice(3);
    if (event.code.startsWith("Digit")) return event.code.slice(5);
    if (event.code.startsWith("Numpad")) return `Numpad ${event.code.slice(6)}`;
    return event.code.replace(/([a-z])([A-Z])/g, "$1 $2");
  }

  function mouseLabel(button) {
    return ["Left Mouse", "Middle Mouse", "Right Mouse", "Mouse Back", "Mouse Forward"][button];
  }

  function finishBindingCapture(binding) {
    bindingCapture = false;
    bindButton.textContent = "Change binding";
    bindButton.blur();
    bindingStatus.classList.remove("listening");
    if (binding) {
      releaseTalk();
      bindingPressed = false;
      saveBinding(binding);
      connectDesktopPtt();
      bindingStatus.textContent = `${binding.label} is now push-to-talk.`;
    } else {
      bindingStatus.textContent = `Kept ${pttBinding.label}.`;
    }
  }

  saveBinding(pttBinding);

  function desktopBindingValue() {
    return pttBinding.kind === "keyboard" ? pttBinding.code : String(pttBinding.button);
  }

  function connectDesktopPtt() {
    if (desktopPttSource) desktopPttSource.close();
    const url = new URL("http://127.0.0.1:47981/v1/ptt/events");
    url.searchParams.set("kind", pttBinding.kind);
    url.searchParams.set("value", desktopBindingValue());
    const source = new EventSource(url);
    desktopPttSource = source;
    source.addEventListener("open", () => {
      if (source !== desktopPttSource || bindingCapture) return;
      bindingStatus.textContent =
        `${pttBinding.label} is ready globally — it works while Morrowind has focus.`;
      bindingStatus.classList.remove("listening");
    });
    source.addEventListener("message", (event) => {
      if (source !== desktopPttSource || bindingCapture) return;
      try {
        const payload = JSON.parse(event.data);
        if (typeof payload.pressed !== "boolean") throw new Error("bad PTT state");
        bindingPressed = payload.pressed;
        queueTalking(payload.pressed);
      } catch (_error) {
        releaseTalk();
      }
    });
    source.addEventListener("error", () => {
      if (source !== desktopPttSource || bindingCapture) return;
      releaseTalk();
      bindingStatus.textContent =
        "Global binding is waiting for MorrowFriends. Keep the launcher open and allow local network access if asked.";
    });
  }

  function setStatus(element, message, kind = "") {
    element.textContent = message;
    element.classList.toggle("error", kind === "error");
    element.classList.toggle("ok", kind === "ok");
  }

  function setBadge(message, kind = "") {
    connectionBadge.textContent = message;
    connectionBadge.classList.toggle("online", kind === "online");
    connectionBadge.classList.toggle("error", kind === "error");
  }

  function audioContext() {
    if (spatialAudioContext) return spatialAudioContext;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return null;
    spatialAudioContext = new AudioContextClass({latencyHint: "interactive"});
    spatialAudioContext.addEventListener("statechange", refreshAudioGate);
    return spatialAudioContext;
  }

  // Once the HRTF graph attaches it is the ONLY audible path, because the
  // LiveKit element is deliberately muted. room.canPlaybackAudio only tracks
  // those elements, and a muted element always satisfies autoplay, so it
  // reports healthy while a suspended context plays nothing at all. Gate the
  // Enable sound button on both or an auto-joined page is silent with no
  // control that fixes it.
  function audioIsBlocked() {
    if (room && !room.canPlaybackAudio) return true;
    return spatialAudioContext !== null && spatialAudioContext.state !== "running";
  }

  function refreshAudioGate() {
    if (!room || !sessionActive) return;
    enableAudioButton.classList.toggle("hidden", !audioIsBlocked());
  }

  async function resumeSpatialAudio() {
    const context = audioContext();
    if (!context || context.state === "running") return;
    try {
      await context.resume();
    } catch (_error) {
      // Autoplay policy needs a real gesture; Enable sound supplies one.
    }
    refreshAudioGate();
  }

  // MorrowFriends opens this page with ?auto=1, so joinVoice() can run with no
  // gesture behind it and the context starts suspended. Treat any later gesture
  // anywhere on the page as the unlock.
  function unlockAudioOnGesture() {
    if (!spatialAudioContext || spatialAudioContext.state === "running") return;
    resumeSpatialAudio();
  }

  window.addEventListener("pointerdown", unlockAudioOnGesture, true);
  window.addEventListener("keydown", unlockAudioOnGesture, true);

  function impulseFor(environment) {
    const cached = impulseByEnvironment.get(environment);
    if (cached) return cached;
    const context = audioContext();
    const profile = acousticProfiles[environment] || acousticProfiles.interior;
    if (!context) return null;
    const frames = Math.max(1, Math.round(context.sampleRate * profile.seconds));
    const impulse = context.createBuffer(2, frames, context.sampleRate);
    let seed = 0x4d46564f;
    for (let channel = 0; channel < impulse.numberOfChannels; channel += 1) {
      const data = impulse.getChannelData(channel);
      for (let index = 0; index < frames; index += 1) {
        seed ^= seed << 13;
        seed ^= seed >>> 17;
        seed ^= seed << 5;
        const noise = ((seed >>> 0) / 0xffffffff) * 2 - 1;
        const time = index / context.sampleRate;
        const onset = Math.min(1, time / 0.018);
        const tail = Math.pow(1 - index / frames, profile.decay);
        data[index] = noise * onset * tail;
      }
    }
    impulseByEnvironment.set(environment, impulse);
    return impulse;
  }

  function destroyAudioGraph(identity) {
    const graph = audioGraphsByIdentity.get(identity);
    if (!graph) return;
    for (const node of graph.nodes) {
      try { node.disconnect(); } catch (_error) { /* Already disconnected. */ }
    }
    audioGraphsByIdentity.delete(identity);
  }

  function createAudioGraph(track, identity) {
    const context = audioContext();
    if (!context || !track.mediaStreamTrack || typeof window.MediaStream !== "function") {
      return null;
    }
    destroyAudioGraph(identity);
    let source = null;
    try {
      source = context.createMediaStreamSource(new MediaStream([track.mediaStreamTrack]));
      const filter = context.createBiquadFilter();
      filter.type = "lowpass";
      filter.Q.value = 0.35;
      const gain = context.createGain();
      gain.gain.value = 0;
      const panner = context.createPanner();
      panner.panningModel = "HRTF";
      panner.distanceModel = "linear";
      panner.refDistance = 1;
      panner.maxDistance = 100000;
      panner.rolloffFactor = 0;
      const dry = context.createGain();
      dry.gain.value = 1;
      const convolver = context.createConvolver();
      const wet = context.createGain();
      wet.gain.value = 0;

      source.connect(filter);
      filter.connect(gain);
      gain.connect(panner);
      panner.connect(dry);
      dry.connect(context.destination);
      gain.connect(convolver);
      convolver.connect(wet);
      wet.connect(context.destination);

      const graph = {
        context, filter, gain, panner, convolver, wet,
        nodes: [source, filter, gain, panner, dry, convolver, wet],
        environment: "",
      };
      audioGraphsByIdentity.set(identity, graph);
      return graph;
    } catch (_error) {
      if (source) {
        try { source.connect(context.destination); } catch (_ignored) { /* Element fallback. */ }
      }
      return null;
    }
  }

  function applyParticipantMix(participant, mix, immediate = false) {
    const graph = audioGraphsByIdentity.get(participant.identity);
    if (!graph) {
      participant.setVolume(mix.gain);
      return;
    }
    const now = graph.context.currentTime;
    const settle = immediate ? 0.005 : 0.06;
    graph.gain.gain.setTargetAtTime(mix.gain, now, settle);
    const position = mix.position || {right: 0, up: 0, forward: 0.01};
    graph.panner.positionX.setTargetAtTime(position.right, now, settle);
    graph.panner.positionY.setTargetAtTime(position.up, now, settle);
    graph.panner.positionZ.setTargetAtTime(-position.forward, now, settle);

    const profile = acousticProfiles[mix.environment] || acousticProfiles.interior;
    graph.filter.frequency.setTargetAtTime(profile.cutoff, now, 0.12);
    graph.wet.gain.setTargetAtTime(profile.wet, now, 0.12);
    if (graph.environment !== mix.environment) {
      graph.convolver.buffer = impulseFor(mix.environment);
      graph.environment = mix.environment;
    }
  }

  function muteAll(reason) {
    mixByIdentity = new Map();
    if (room) {
      for (const participant of room.remoteParticipants.values()) {
        applyParticipantMix(
          participant,
          {gain: 0, position: null, environment: "interior"},
          true,
        );
      }
    }
    renderParticipants();
    positionStatus.textContent = reason;
  }

  function applyMix(frame) {
    if (!frame || frame.type !== "mix" || frame.listener !== participantIdentity ||
        !Array.isArray(frame.speakers) || frame.speakers.length > 64) {
      muteAll("Invalid position update — muted");
      return;
    }
    const environment = acousticProfiles[frame.environment] ? frame.environment : "interior";
    const nextMix = new Map();
    for (const speaker of frame.speakers) {
      const position = speaker && speaker.position;
      if (!speaker || typeof speaker.player !== "string" ||
          typeof speaker.gain !== "number" || !Number.isFinite(speaker.gain) ||
          (position !== null && position !== undefined &&
           (typeof position !== "object" ||
            ![position.right, position.up, position.forward].every(Number.isFinite)))) {
        muteAll("Invalid position update — muted");
        return;
      }
      nextMix.set(speaker.player, {
        gain: Math.max(0, Math.min(1, speaker.gain)),
        position: position || null,
        environment,
      });
    }
    mixByIdentity = frame.stale ? new Map() : nextMix;
    lastMixAt = performance.now();
    if (room) {
      for (const participant of room.remoteParticipants.values()) {
        applyParticipantMix(
          participant,
          mixByIdentity.get(participant.identity) ||
            {gain: 0, position: null, environment},
        );
      }
    }
    positionStatus.textContent = frame.stale
      ? "Game positions stale — everyone muted"
      : `Live game position #${Number(frame.sequence) || 0} · ${environmentLabels[environment]}`;
    renderParticipants();
  }

  function renderParticipants() {
    participantsRoot.replaceChildren();
    if (!room || room.remoteParticipants.size === 0) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No one else in voice yet.";
      participantsRoot.append(empty);
      return;
    }
    const participants = [...room.remoteParticipants.values()]
      .sort((left, right) => left.identity.localeCompare(right.identity));
    for (const participant of participants) {
      const gain = mixByIdentity.get(participant.identity)?.gain || 0;
      const row = document.createElement("div");
      row.className = "participant";
      const name = document.createElement("span");
      name.className = "participant-name";
      name.textContent = participant.name || participant.identity;
      const meter = document.createElement("span");
      meter.className = "meter";
      const fill = document.createElement("span");
      fill.style.width = `${Math.round(gain * 100)}%`;
      meter.append(fill);
      const value = document.createElement("span");
      value.className = "gain";
      value.textContent = gain > 0 ? `${Math.round(gain * 100)}%` : "muted";
      row.append(name, meter, value);
      participantsRoot.append(row);
    }
  }

  function playerSocketUrl() {
    const url = new URL("v1/player", window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.search = "";
    return url.toString();
  }

  function connectPositionSocket() {
    if (!sessionActive || !positionToken) return;
    clearTimeout(positionReconnectTimer);
    muteAll("Connecting game positions…");
    const socket = new WebSocket(playerSocketUrl());
    positionSocket = socket;
    socket.addEventListener("open", () => {
      positionReconnectDelay = 1000;
      socket.send(JSON.stringify({type: "auth", token: positionToken}));
    });
    socket.addEventListener("message", (event) => {
      if (socket !== positionSocket || typeof event.data !== "string" || event.data.length > 65536) return;
      try {
        applyMix(JSON.parse(event.data));
      } catch (_error) {
        muteAll("Invalid position update — muted");
      }
    });
    socket.addEventListener("close", (event) => {
      if (socket !== positionSocket) return;
      muteAll("Game position link lost — everyone muted");
      if (!sessionActive || event.code === 4401) {
        if (event.code === 4401) {
          // The relay dropped this session: it expired, or the relay itself
          // restarted and lost its in-memory sessions. The game keeps an unused
          // claim minted for every logged-in character, so re-attach instead of
          // demanding a code nobody can read off a fullscreen game.
          setStatus(voiceStatus, "Voice session ended — reattaching…", "");
          resetPartialJoin().then(tryAutomaticJoin);
        }
        return;
      }
      positionReconnectTimer = window.setTimeout(connectPositionSocket, positionReconnectDelay);
      positionReconnectDelay = Math.min(positionReconnectDelay * 2, 15000);
    });
    socket.addEventListener("error", () => muteAll("Game position link lost — everyone muted"));
  }

  function queueTalking(next) {
    if (!room || !sessionActive || talkButton.disabled || next === talking) return;
    talking = next;
    talkButton.classList.toggle("talking", next);
    talkButton.querySelector(".talk-label").textContent = next ? "Talking" : "Hold to talk";
    const target = next;
    micQueue = micQueue
      .then(() => room.localParticipant.setMicrophoneEnabled(target))
      .catch((error) => {
        talking = false;
        talkButton.classList.remove("talking");
        talkButton.querySelector(".talk-label").textContent = "Hold to talk";
        setStatus(voiceStatus, `Microphone error: ${error.message || error}`, "error");
      });
  }

  function releaseTalk() {
    bindingPressed = false;
    queueTalking(false);
  }

  bindButton.addEventListener("click", () => {
    if (bindingCapture) {
      finishBindingCapture(null);
      return;
    }
    releaseTalk();
    bindingPressed = false;
    bindingCapture = true;
    bindButton.textContent = "Cancel";
    bindingStatus.textContent = "Press one keyboard key or mouse button. Escape cancels.";
    bindingStatus.classList.add("listening");
  });

  async function resetPartialJoin() {
    sessionActive = false;
    talking = false;
    clearTimeout(positionReconnectTimer);
    if (desktopPttSource) {
      desktopPttSource.close();
      desktopPttSource = null;
    }
    if (positionSocket) {
      positionSocket.close();
      positionSocket = null;
    }
    if (room) {
      await room.disconnect();
      room = null;
    }
    positionToken = "";
    participantIdentity = "";
    mixByIdentity = new Map();
    for (const identity of [...audioGraphsByIdentity.keys()]) destroyAudioGraph(identity);
    talkButton.disabled = true;
    talkButton.classList.remove("talking");
    talkButton.querySelector(".talk-label").textContent = "Hold to talk";
    voicePanel.classList.add("hidden");
    claimPanel.classList.remove("hidden");
    setBadge("Not connected");
  }

  talkButton.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    talkButton.setPointerCapture(event.pointerId);
    queueTalking(true);
  });
  talkButton.addEventListener("pointerup", releaseTalk);
  talkButton.addEventListener("pointercancel", releaseTalk);
  window.addEventListener("blur", releaseTalk);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) releaseTalk();
  });
  document.addEventListener("keydown", (event) => {
    if (bindingCapture) {
      event.preventDefault();
      if (event.code === "Escape") finishBindingCapture(null);
      else finishBindingCapture({kind: "keyboard", code: event.code, label: keyboardLabel(event)});
      return;
    }
    if (pttBinding.kind !== "keyboard" || event.code !== pttBinding.code || event.repeat ||
        ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
    event.preventDefault();
    bindingPressed = true;
    queueTalking(true);
  });
  document.addEventListener("keyup", (event) => {
    if (pttBinding.kind !== "keyboard" || event.code !== pttBinding.code) return;
    event.preventDefault();
    bindingPressed = false;
    releaseTalk();
  });
  window.addEventListener("pointerdown", (event) => {
    if (bindingCapture) {
      if (event.target === bindButton || bindButton.contains(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
      finishBindingCapture({kind: "mouse", button: event.button, label: mouseLabel(event.button)});
      return;
    }
    if (pttBinding.kind !== "mouse" || event.button !== pttBinding.button ||
        event.target === talkButton || talkButton.contains(event.target)) return;
    event.preventDefault();
    bindingPressed = true;
    queueTalking(true);
  }, true);
  window.addEventListener("pointerup", (event) => {
    if (pttBinding.kind !== "mouse" || event.button !== pttBinding.button || !bindingPressed) return;
    event.preventDefault();
    bindingPressed = false;
    releaseTalk();
  }, true);
  window.addEventListener("contextmenu", (event) => {
    if (pttBinding.kind === "mouse" && pttBinding.button === 2 && bindingPressed) {
      event.preventDefault();
    }
  });

  enableAudioButton.addEventListener("click", async () => {
    if (!room) return;
    try {
      await room.startAudio();
      await resumeSpatialAudio();
      refreshAudioGate();
    } catch (error) {
      setStatus(voiceStatus, `Could not start sound: ${error.message || error}`, "error");
    }
  });

  async function joinVoice(credentials) {
    if (!SDK || !SDK.isBrowserSupported()) {
      throw new Error("This browser does not support WebRTC voice. Use current Chrome, Edge, or Firefox.");
    }
    participantIdentity = credentials.participant_identity;
    positionToken = credentials.position_token;
    room = new SDK.Room({adaptiveStream: false, dynacast: false});
    room
      .on(SDK.RoomEvent.TrackSubscribed, (track, _publication, participant) => {
        if (track.kind !== SDK.Track.Kind.Audio) return;
        const element = track.attach();
        element.autoplay = true;
        audioRoot.append(element);
        const graph = createAudioGraph(track, participant.identity);
        if (graph) {
          // LiveKit may update its attached element after subscription. Keep
          // that centered path silent so only the independent HRTF graph is
          // audible; volume remains untouched when the compatibility fallback
          // is in use.
          element.muted = true;
          element.volume = 0;
          element.dataset.spatialAudio = "true";
        }
        applyParticipantMix(
          participant,
          mixByIdentity.get(participant.identity) ||
            {gain: 0, position: null, environment: "interior"},
          true,
        );
        renderParticipants();
      })
      .on(SDK.RoomEvent.TrackUnsubscribed, (track, _publication, participant) => {
        if (participant) destroyAudioGraph(participant.identity);
        for (const element of track.detach()) element.remove();
        renderParticipants();
      })
      .on(SDK.RoomEvent.ParticipantConnected, renderParticipants)
      .on(SDK.RoomEvent.ParticipantDisconnected, renderParticipants)
      .on(SDK.RoomEvent.AudioPlaybackStatusChanged, refreshAudioGate)
      .on(SDK.RoomEvent.Reconnecting, () => setBadge("Reconnecting…"))
      .on(SDK.RoomEvent.Reconnected, () => setBadge("Connected", "online"))
      .on(SDK.RoomEvent.Disconnected, () => {
        sessionActive = false;
        if (desktopPttSource) {
          desktopPttSource.close();
          desktopPttSource = null;
        }
        releaseTalk();
        talkButton.disabled = true;
        for (const identity of [...audioGraphsByIdentity.keys()]) destroyAudioGraph(identity);
        muteAll("Voice room disconnected");
        setBadge("Disconnected", "error");
      });

    await room.connect(credentials.server_url, credentials.participant_token, {autoSubscribe: true});
    await resumeSpatialAudio();
    sessionActive = true;
    setBadge("Connected", "online");
    voiceTitle.textContent = credentials.participant_name || participantIdentity;
    claimPanel.classList.add("hidden");
    voicePanel.classList.remove("hidden");
    connectPositionSocket();
    connectDesktopPtt();

    // Ask during the Join gesture, then return to safe muted push-to-talk mode.
    await room.localParticipant.setMicrophoneEnabled(true);
    await room.localParticipant.setMicrophoneEnabled(false);
    talkButton.disabled = false;
    setStatus(voiceStatus, `Ready. Hold ${pttBinding.label} or the button while speaking.`, "ok");
    refreshAudioGate();
    renderParticipants();
  }

  async function redeemAndJoin(body, path) {
    setStatus(claimStatus, "Attaching your in-game voice…");
    let claimWasRedeemed = false;
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        cache: "no-store",
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Voice could not attach yet.");
      claimWasRedeemed = true;
      await joinVoice(payload);
    } catch (error) {
      await resetPartialJoin();
      const retry = claimWasRedeemed
        ? " MorrowFriends will try again after you finish logging in."
        : "";
      setStatus(claimStatus, (error.message || String(error)) + retry, "error");
      throw error;
    }
  }

  function scheduleJoinRetry() {
    window.clearTimeout(joinRetryTimer);
    // Back off as failures accumulate. A fixed 5s interval with several open
    // tabs hit the relay's 30-attempts-per-minute limiter (2026-08-21).
    joinRetryFailures += 1;
    const delayMs = Math.min(5000 * (2 ** Math.min(joinRetryFailures - 1, 3)), 40000);
    joinRetryTimer = window.setTimeout(tryAutomaticJoin, delayMs);
  }

  async function tryAutomaticJoin() {
    if (sessionActive) return;
    const party = partyInput.value.trim();
    if (!party) return;
    if (codeFromLink.length === 16) {
      try {
        await redeemAndJoin({party_id: party, code: codeFromLink}, "v1/claim");
        joinRetryFailures = 0;
        return;
      } catch (_error) {
        // Fall through to the name the launcher already sent.
      }
    }
    // The launcher already knows who this is: the "You are" field, which is
    // the TES3MP account. Asking the page to pick a name was leftover from a
    // bare-URL footgun — /health lists everyone, so "only one name" claimed
    // the host (Vicksauce, 2026-08-18). Never guess from the party list.
    if (playerFromLink) {
      try {
        await redeemAndJoin({party_id: party, player: playerFromLink}, "v1/auto-claim");
        joinRetryFailures = 0;
        return;
      } catch (_error) {
        setStatus(claimStatus, `Waiting for ${playerFromLink} to finish logging in…`, "");
        scheduleJoinRetry();
        return;
      }
    }
    // No name from the launcher: first-time / new character. Wait for the
    // one account that appears after this page opened.
    try {
      const names = await namesInParty();
      if (namesAtOpen === null) {
        namesAtOpen = new Set(names.map((name) => name.toLowerCase()));
      }
      const arrived = names.filter((name) => !namesAtOpen.has(name.toLowerCase()));
      if (arrived.length === 1) {
        await redeemAndJoin({party_id: party, player: arrived[0]}, "v1/auto-claim");
        joinRetryFailures = 0;
        return;
      }
    } catch (_error) {
      // Relay health is down; try again on the same backoff.
    }
    setStatus(claimStatus, "Waiting for your character to finish logging in…", "");
    scheduleJoinRetry();
  }

  async function namesInParty() {
    const response = await fetch(new URL("health", window.location.href), {cache: "no-store"});
    if (!response.ok) throw new Error("health");
    const health = await response.json();
    const names = Array.isArray(health && health.names) ? health.names.filter(Boolean) : [];
    return names.filter((name) => typeof name === "string" && name);
  }

  if (playerFromLink) {
    setStatus(claimStatus, `Attaching as ${playerFromLink}…`, "");
  } else {
    setStatus(claimStatus, "Waiting for your character to finish logging in…", "");
  }
  tryAutomaticJoin();

  window.setInterval(() => {
    if (sessionActive && lastMixAt && performance.now() - lastMixAt > 2500) {
      muteAll("Game position updates stopped — everyone muted");
      lastMixAt = 0;
    }
    refreshAudioGate();
  }, 500);

  window.addEventListener("beforeunload", () => {
    sessionActive = false;
    window.clearTimeout(joinRetryTimer);
    if (desktopPttSource) desktopPttSource.close();
    if (positionSocket) positionSocket.close();
    if (room) room.disconnect();
  });
})();
