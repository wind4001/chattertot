// P5 客户端：麦克风常开，连续流式对话（不用按键）
const $ = (id) => document.getElementById(id);

// 24kHz PCM 流式播放器（时间线无缝调度，块与块精确衔接）——类定义必须在实例化之前
class PcmPlayer {
  constructor() {
    this.ctx = null; // 延迟到首次 push 时创建（用户手势后）
    this.nextTime = 0;
    this.sources = [];
    this.endTimer = null;
  }
  _ensureCtx() {
    if (!this.ctx) this.ctx = new AudioContext({ sampleRate: 24000 });
    return this.ctx;
  }
  push(int16) {
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
    src.start(this.nextTime); // 在时间线上精确衔接，无间隙
    this.nextTime += float32.length / 24000;
    this.sources.push(src);
    src.onended = () => {
      const i = this.sources.indexOf(src);
      if (i >= 0) this.sources.splice(i, 1);
    };
    this._scheduleEnd();
  }
  _scheduleEnd() {
    // 队列播完时通知服务端（服务端以此开始计静默，而不是按"发送完成"计）
    clearTimeout(this.endTimer);
    const remainMs = Math.max(0, (this.nextTime - this.ctx.currentTime) * 1000);
    this.endTimer = setTimeout(() => {
      if (this.sources.length === 0 && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "play_end" }));
      }
    }, remainMs + 200);
  }
  stop() {
    clearTimeout(this.endTimer);
    for (const src of this.sources) {
      try {
        src.stop();
      } catch (e) {}
    }
    this.sources = [];
    this.nextTime = 0;
  }
}

let ws = null;
let micCtx = null;
let micNode = null;
let micStream = null;
let chunkBuffer = new Int16Array(0);
const CHUNK = 800; // 50ms @ 16kHz
const player = new PcmPlayer();

$("btnStart").onclick = start;
$("btnStop").onclick = stop;

async function start() {
  $("btnStart").disabled = true;
  $("btnStop").disabled = false;
  $("status").textContent = "连接中...";

  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    $("status").textContent = "已连接，开始说话吧";
    startMic();
  };
  ws.onclose = () => {
    $("status").textContent = "已断开";
  };
  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") handleJson(JSON.parse(ev.data));
  };
}

function handleJson(msg) {
  switch (msg.type) {
    case "asr_text":
      log("你: " + msg.text, "asr");
      break;
    case "ai_text":
      log("小云: " + msg.text, "ai");
      break;
    case "ai_audio":
      // 流式 PCM：base64 -> Int16 -> 送入播放器（边收边播）
      player.push(base64ToInt16(msg.audio));
      break;
    case "user_speaking":
      player.stop(); // 用户插话，停掉正在播的声音
      break;
    case "wake":
      log("我在呢！", "sys");
      break;
    case "idle":
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
    log("麦克风开启失败: " + e.message, "sys");
  }
}

function stop() {
  player.stop();
  if (micNode) micNode.disconnect();
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (micCtx) micCtx.close();
  if (ws) ws.close();
  micNode = null;
  micStream = null;
  micCtx = null;
  ws = null;
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
}
