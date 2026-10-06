// M1 客户端：连接后端 WS，采集麦克风（16kHz Int16 PCM），播放 TTS（24kHz Float32 PCM）。
const $ = (id) => document.getElementById(id);

function logLine(text, cls) {
  const div = document.createElement("div");
  div.className = cls;
  div.textContent = text;
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
  return div;
}

// 24kHz Float32 PCM 播放器（简单队列调度）
class AudioPlayer {
  constructor() {
    this.ctx = new AudioContext({ sampleRate: 24000 });
    this.queue = [];
    this.busy = false;
  }
  push(arrayBuffer) {
    // 火山下发的音频是 Float32 PCM，直接进缓冲，无需缩放
    const float32 = new Float32Array(arrayBuffer);
    this.queue.push(float32);
    this.pump();
  }
  pump() {
    if (this.busy || this.queue.length === 0) return;
    this.busy = true;
    if (this.ctx.state === "suspended") this.ctx.resume();
    const float32 = this.queue.shift();
    const buf = this.ctx.createBuffer(1, float32.length, 24000);
    buf.getChannelData(0).set(float32);
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctx.destination);
    src.onended = () => {
      this.busy = false;
      this.pump();
    };
    src.start();
  }
  stop() {
    this.queue = [];
  }
}

let ws = null;
let micCtx = null;
let micNode = null;
let micStream = null;
let asrLine = null; // 当前「你」流式行（ASR 累积，覆盖更新）
let aiLine = null; // 当前「AI」流式行（文本增量，追加）
const player = new AudioPlayer();

$("btnConnect").onclick = () => {
  if (ws) ws.close();
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    logLine("已连接后端", "sys");
    $("status").textContent = "已连接";
    $("btnStart").disabled = false;
  };
  ws.onclose = () => {
    logLine("连接断开", "sys");
    $("status").textContent = "未连接";
    $("btnStart").disabled = true;
    $("btnStop").disabled = true;
  };
  ws.onmessage = (ev) => (typeof ev.data === "string" ? handleJson(JSON.parse(ev.data)) : player.push(ev.data));
};

$("btnStart").onclick = () => startSession();
$("btnStop").onclick = () => stopSession();

$("textQuery").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "text_query", content: $("textQuery").value }));
    $("textQuery").value = "";
  }
});

function startSession() {
  const config = {
    voice: $("voice").value,
    system_prompt: $("prompt").value,
  };
  ws.send(JSON.stringify({ type: "start_session", config }));
  startMic();
  $("btnStart").disabled = true;
}

function stopSession() {
  stopMic();
  player.stop();
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "stop_session" }));
  $("btnStop").disabled = true;
}

async function startMic() {
  try {
    micCtx = new AudioContext({ sampleRate: 16000 });
    micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    await micCtx.audioWorklet.addModule("/worklet.js");
    const src = micCtx.createMediaStreamSource(micStream);
    micNode = new AudioWorkletNode(micCtx, "pcm-worklet");
    micNode.port.onmessage = (e) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(e.data);
    };
    src.connect(micNode); // worklet 无输出，不连 destination
    logLine("麦克风已开启 (16kHz PCM)", "sys");
  } catch (e) {
    logLine(`麦克风开启失败: ${e.message}`, "err");
  }
}

function stopMic() {
  if (micNode) micNode.disconnect();
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (micCtx) micCtx.close();
  micNode = null;
  micStream = null;
  micCtx = null;
}

function handleJson(msg) {
  switch (msg.type) {
    case "ready":
      logLine("火山连接就绪，可以开始会话", "sys");
      break;
    case "session_started":
      logLine(`会话已建立  dialog_id=${msg.dialog_id}`, "sys");
      $("btnStop").disabled = false;
      break;
    case "session_finished":
      logLine("会话结束", "sys");
      break;
    case "asr_text":
      // ASR 是累积文本，覆盖当前「你」行
      if (msg.final) {
        if (asrLine) asrLine.textContent = `你: ${msg.text}`;
        asrLine = null;
        aiLine = null; // 用户说完，AI 回复另起一行
      } else {
        if (!asrLine) asrLine = logLine(`你: ${msg.text}`, "asr");
        else asrLine.textContent = `你: ${msg.text}`;
      }
      break;
    case "chat_text":
      // AI 文本是增量，追加到当前「AI」行
      if (!aiLine) aiLine = logLine(`AI: ${msg.content}`, "tts");
      else aiLine.textContent += msg.content;
      break;
    case "error":
      logLine(`错误: ${msg.message}`, "err");
      break;
    default:
      break;
  }
}
