// P5 客户端：麦克风常开，连续流式对话（不用按键）
const $ = (id) => document.getElementById(id);

// 24kHz PCM 流式播放器（时间线无缝调度，块与块精确衔接）——类定义必须在实例化之前
class PcmPlayer {
  constructor(onEnd) {
    this.ctx = null; // 延迟到首次 push 时创建（用户手势后）
    this.nextTime = 0;
    this.sources = [];
    this.turnId = null;
    this.inputFinished = false;
    this.endSent = false;
    this.onEnd = onEnd;
  }
  _ensureCtx() {
    if (!this.ctx) this.ctx = new AudioContext({ sampleRate: 24000 });
    return this.ctx;
  }
  begin(turnId) {
    this.stop();
    this.turnId = turnId;
    this.inputFinished = false;
    this.endSent = false;
  }
  push(int16, turnId) {
    if (turnId !== this.turnId || this.inputFinished || !int16.length) return;
    const ctx = this._ensureCtx();
    if (ctx.state === "suspended") ctx.resume();
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;
    const buf = ctx.createBuffer(1, float32.length, 24000);
    buf.getChannelData(0).set(float32);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const now = ctx.currentTime;
    if (this.nextTime < now) this.nextTime = now;
    this.sources.push(src);
    src.onended = () => {
      if (turnId !== this.turnId) return;
      const i = this.sources.indexOf(src);
      if (i >= 0) this.sources.splice(i, 1);
      this._maybeEnd();
    };
    src.start(this.nextTime); // 在时间线上精确衔接，无间隙
    this.nextTime += float32.length / 24000;
  }
  finish(turnId) {
    if (turnId !== this.turnId) return;
    this.inputFinished = true;
    this._maybeEnd();
  }
  _maybeEnd() {
    if (this.turnId !== null && this.inputFinished && !this.sources.length && !this.endSent) {
      this.endSent = true;
      this.onEnd(this.turnId);
    }
  }
  stop() {
    this.turnId = null;
    this.inputFinished = false;
    const sources = this.sources;
    this.sources = [];
    for (const src of sources) {
      try {
        src.stop();
      } catch (e) {}
    }
    this.nextTime = 0;
  }
}

let ws = null;
let micCtx = null;
let micNode = null;
let micStream = null;
let chunkBuffer = new Int16Array(0);
const CHUNK = 800; // 50ms @ 16kHz
let currentTurnId = null;
let latestTurnId = 0;
let aiLine = null;
let aiText = "";
const player = new PcmPlayer((turnId) => {
  if (turnId === currentTurnId && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "play_end", turn_id: turnId }));
    $("status").textContent = "听你说…";
  }
});

$("btnStart").onclick = start;
$("btnStop").onclick = stop;

async function start() {
  $("storyMode").textContent = "";
  $("btnStart").disabled = true;
  $("btnStop").disabled = false;
  $("status").textContent = "连接中...";

  latestTurnId = 0;
  currentTurnId = null;
  const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws = socket;
  socket.binaryType = "arraybuffer";
  socket.onopen = () => {
    if (socket !== ws) return;
    $("status").textContent = "已连接，开始说话吧";
    startMic();
  };
  socket.onclose = () => {
    if (socket !== ws) return;
    stop();
    $("status").textContent = "已断开";
  };
  socket.onmessage = (ev) => {
    if (socket !== ws) return;
    if (typeof ev.data === "string") handleJson(JSON.parse(ev.data));
  };
}

function handleJson(msg) {
  if (msg.type === "turn_start") {
    if (!Number.isInteger(msg.turn_id) || msg.turn_id <= latestTurnId) return;
    currentTurnId = latestTurnId = msg.turn_id;
    player.begin(msg.turn_id);
    aiText = "";
    aiLine = log("小云: ", "ai");
    $("status").textContent = "小云正在想…";
    return;
  }
  if (msg.turn_id !== undefined && msg.turn_id !== currentTurnId) return;
  switch (msg.type) {
    case "story_mode":
      $("storyMode").textContent = {
        role: "一起编故事 · 选一个角色",
        scene: "一起编故事 · 选一个场景",
        playing: "故事进行中 · 可以改剧情，也可以说「不玩故事了」",
        off: "故事已结束，可以继续聊天",
      }[msg.phase] || "";
      break;
    case "asr_text":
      log("你: " + msg.text, "asr");
      break;
    case "ai_text_delta":
      if (!aiLine || currentTurnId === null) break;
      aiText += msg.text;
      aiLine.textContent = "小云: " + aiText;
      $("log").scrollTop = $("log").scrollHeight;
      break;
    case "ai_text":
      if (aiLine) aiLine.textContent = "小云: " + msg.text;
      break;
    case "ai_audio":
      // 流式 PCM：base64 -> Int16 -> 送入播放器（边收边播）
      if (currentTurnId === null) break;
      player.push(base64ToInt16(msg.audio), msg.turn_id);
      $("status").textContent = "小云正在说…";
      break;
    case "audio_end":
      player.finish(msg.turn_id);
      break;
    case "response_error":
      log(msg.message, "sys");
      $("status").textContent = msg.message;
      break;
    case "user_speaking":
      player.stop(); // 用户插话，停掉正在播的声音
      currentTurnId = null;
      $("status").textContent = "听你说…";
      break;
    case "wake":
      log("我在呢！", "sys");
      break;
    case "idle":
      player.stop();
      currentTurnId = null;
      $("status").textContent = "待机中";
      log("（待机中）说「小云小云」唤醒我", "sys");
      break;
  }
}

function base64ToInt16(b64) {
  const binary = atob(b64);
  const len = binary.length - (binary.length % 2); // 保证偶数（16bit）
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}

async function startMic() {
  try {
    micCtx = new AudioContext({ sampleRate: 16000 });
    // echoCancellationType:'system' 用系统级 AEC（比浏览器内置强）；关掉 AGC（它会放大回声残余，破坏 AEC）
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        echoCancellationType: "system",
        noiseSuppression: true,
        autoGainControl: false,
      },
    });
    // 诊断：打印浏览器实际应用的音频处理设置（验证 AEC/AGC 是否真生效）
    const track = micStream.getAudioTracks()[0];
    console.log("[麦克风实际设置]", JSON.stringify(track.getSettings()));
    log("麦克风处理: AEC=" + track.getSettings().echoCancellation + " AGC=" + track.getSettings().autoGainControl + " NS=" + track.getSettings().noiseSuppression, "sys");
    await micCtx.audioWorklet.addModule("/worklet.js");
    const src = micCtx.createMediaStreamSource(micStream);
    micNode = new AudioWorkletNode(micCtx, "pcm-worklet");
    chunkBuffer = new Int16Array(0);
    micNode.port.onmessage = (e) => {
      const incoming = new Int16Array(e.data);
      let merged = new Int16Array(chunkBuffer.length + incoming.length);
      merged.set(chunkBuffer);
      merged.set(incoming, chunkBuffer.length);
      while (merged.length >= CHUNK) {
        const send = merged.slice(0, CHUNK);
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(send.buffer);
        merged = merged.slice(CHUNK);
      }
      chunkBuffer = merged;
    };
    src.connect(micNode);
  } catch (e) {
    stop();
    log("麦克风开启失败: " + e.message, "sys");
    $("status").textContent = "麦克风未开启，请检查权限后重试";
  }
}

function stop() {
  $("storyMode").textContent = "";
  player.stop();
  currentTurnId = null;
  if (micNode) micNode.disconnect();
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (micCtx) micCtx.close();
  const socket = ws;
  ws = null;
  if (socket) socket.close();
  micNode = null;
  micStream = null;
  micCtx = null;
  $("btnStart").disabled = false;
  $("btnStop").disabled = true;
  $("status").textContent = "已停止";
}

function log(text, cls) {
  const div = document.createElement("div");
  div.className = cls;
  div.textContent = text;
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
  return div;
}
