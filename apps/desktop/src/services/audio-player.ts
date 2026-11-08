/** 桌面端音频播放：整段 URL 用 Web Audio 解码后一次播放；分块队列仍保留兼容。 */

export type PlayerState = "idle" | "loading" | "playing" | "paused" | "ended" | "failed";

export type AudioPlayerHandle = {
  play: (url: string) => Promise<void>;
  enqueueChunk: (blob: Blob) => void;
  startChunkQueue: () => void;
  markStreamComplete: () => void;
  pause: () => void;
  resume: () => void;
  stop: () => void;
  getState: () => PlayerState;
  getCurrentUrl: () => string | null;
};

export function createAudioPlayer(onChange?: (state: PlayerState) => void): AudioPlayerHandle {
  let state: PlayerState = "idle";
  let currentUrl: string | null = null;

  // Web Audio 整段播放（主路径）
  let context: AudioContext | null = null;
  let buffer: AudioBuffer | null = null;
  let source: AudioBufferSourceNode | null = null;
  let startedAt = 0;
  let pauseOffset = 0;
  let playGeneration = 0;

  // 分块队列兼容（HTMLAudio 接力，产品主路径不走这里）
  let audio: HTMLAudioElement | null = null;
  let queue: Blob[] = [];
  let queueMode = false;
  let streamComplete = false;
  let objectUrl: string | null = null;
  let pumping = false;

  const setState = (next: PlayerState) => {
    state = next;
    onChange?.(next);
  };

  const ensureContext = (): AudioContext => {
    if (!context || context.state === "closed") {
      context = new AudioContext();
    }
    return context;
  };

  const stopSource = () => {
    if (!source) {
      return;
    }
    source.onended = null;
    try {
      source.stop();
    } catch {
      // already stopped
    }
    try {
      source.disconnect();
    } catch {
      // ignore
    }
    source = null;
  };

  const revokeObjectUrl = () => {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
  };

  const disposeElement = () => {
    if (!audio) {
      return;
    }
    audio.onplay = null;
    audio.onpause = null;
    audio.onended = null;
    audio.onerror = null;
    audio.pause();
    audio.src = "";
    audio = null;
  };

  const disposeWebAudio = () => {
    stopSource();
    buffer = null;
    pauseOffset = 0;
    startedAt = 0;
  };

  const dispose = () => {
    playGeneration += 1;
    disposeWebAudio();
    disposeElement();
    revokeObjectUrl();
    queue = [];
    queueMode = false;
    streamComplete = false;
    pumping = false;
    currentUrl = null;
  };

  const startBufferAt = async (offsetSeconds: number): Promise<void> => {
    if (!buffer) {
      throw new Error("音频未解码");
    }
    const ctx = ensureContext();
    if (ctx.state === "suspended") {
      await ctx.resume();
    }
    stopSource();
    const next = ctx.createBufferSource();
    next.buffer = buffer;
    next.connect(ctx.destination);
    const gen = playGeneration;
    next.onended = () => {
      if (gen !== playGeneration || source !== next) {
        return;
      }
      // 暂停触发的 stop 不应标 ended
      if (state === "paused") {
        return;
      }
      source = null;
      setState("ended");
    };
    const safeOffset = Math.max(0, Math.min(offsetSeconds, Math.max(buffer.duration - 0.01, 0)));
    startedAt = ctx.currentTime - safeOffset;
    pauseOffset = safeOffset;
    source = next;
    next.start(0, safeOffset);
    setState("playing");
  };

  const playNextChunk = async (): Promise<void> => {
    if (!queueMode || pumping) {
      return;
    }
    const next = queue.shift();
    if (!next) {
      if (streamComplete) {
        setState("ended");
      }
      return;
    }
    pumping = true;
    disposeElement();
    revokeObjectUrl();
    objectUrl = URL.createObjectURL(next);
    currentUrl = objectUrl;
    const element = new Audio(objectUrl);
    audio = element;
    element.onplay = () => setState("playing");
    element.onpause = () => {
      if (state !== "ended" && state !== "failed" && state !== "idle") {
        setState("paused");
      }
    };
    element.onended = () => {
      pumping = false;
      void playNextChunk();
    };
    element.onerror = () => {
      pumping = false;
      setState("failed");
    };
    try {
      await element.play();
    } catch {
      pumping = false;
      setState("failed");
    }
  };

  return {
    async play(url: string) {
      dispose();
      currentUrl = url;
      setState("loading");
      const gen = playGeneration;
      try {
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`音频下载失败 HTTP ${response.status}`);
        }
        const bytes = await response.arrayBuffer();
        if (gen !== playGeneration) {
          return;
        }
        const ctx = ensureContext();
        if (ctx.state === "suspended") {
          await ctx.resume();
        }
        // decodeAudioData 可能 detach buffer，先拷贝
        buffer = await ctx.decodeAudioData(bytes.slice(0));
        if (gen !== playGeneration) {
          return;
        }
        await startBufferAt(0);
      } catch {
        if (gen !== playGeneration) {
          return;
        }
        setState("failed");
        throw new Error("无法播放语音");
      }
    },
    enqueueChunk(blob: Blob) {
      queueMode = true;
      queue.push(blob);
      if (state === "idle" || state === "loading" || state === "ended") {
        void playNextChunk();
      }
    },
    startChunkQueue() {
      queueMode = true;
      streamComplete = false;
      setState("loading");
    },
    markStreamComplete() {
      streamComplete = true;
      if (!pumping && queue.length === 0 && (state === "loading" || state === "playing")) {
        setState(queue.length === 0 && !audio ? "ended" : state);
      }
      if (!pumping && queue.length === 0 && !audio) {
        setState("ended");
      }
    },
    pause() {
      if (queueMode) {
        audio?.pause();
        return;
      }
      if (!context || !source || state !== "playing") {
        return;
      }
      pauseOffset = Math.max(0, context.currentTime - startedAt);
      setState("paused");
      stopSource();
    },
    resume() {
      if (queueMode) {
        if ((!audio || audio.ended) && queue.length > 0) {
          void playNextChunk();
          return;
        }
        void audio?.play();
        return;
      }
      if (state !== "paused" || !buffer) {
        return;
      }
      void startBufferAt(pauseOffset).catch(() => setState("failed"));
    },
    stop() {
      dispose();
      setState("idle");
    },
    getState() {
      return state;
    },
    getCurrentUrl() {
      return currentUrl;
    },
  };
}
