/** 浏览器麦克风采集：输出 16kHz mono PCM16 WAV，供 ASR 上传。 */

export type MicrophoneHandle = {
  stop: () => Promise<Blob>;
  cancel: () => void;
};

const TARGET_RATE = 16000;

export async function startMicrophone(): Promise<MicrophoneHandle> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("当前环境不支持麦克风");
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  const context = new AudioContext();
  const source = context.createMediaStreamSource(stream);
  const processor = context.createScriptProcessor(4096, 1, 1);
  const silent = context.createGain();
  silent.gain.value = 0;
  const chunks: Float32Array[] = [];
  let closed = false;

  processor.onaudioprocess = (event) => {
    if (closed) {
      return;
    }
    chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
  };

  source.connect(processor);
  processor.connect(silent);
  silent.connect(context.destination);

  const shutdown = () => {
    if (closed) {
      return;
    }
    closed = true;
    processor.onaudioprocess = null;
    try {
      processor.disconnect();
      source.disconnect();
      silent.disconnect();
    } catch {
      // ignore
    }
    for (const track of stream.getTracks()) {
      track.stop();
    }
    void context.close();
  };

  return {
    async stop() {
      const rate = context.sampleRate;
      shutdown();
      const merged = mergeChunks(chunks);
      const pcm = downsampleTo16k(merged, rate);
      return encodeWavPcm16(pcm, TARGET_RATE);
    },
    cancel() {
      shutdown();
    },
  };
}

export function mergeChunks(chunks: Float32Array[]): Float32Array {
  const total = chunks.reduce((sum, item) => sum + item.length, 0);
  const merged = new Float32Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}

export function downsampleTo16k(input: Float32Array, inputRate: number): Int16Array {
  if (inputRate === TARGET_RATE) {
    return floatToPcm16(input);
  }
  if (inputRate <= 0 || input.length === 0) {
    return new Int16Array(0);
  }
  const ratio = inputRate / TARGET_RATE;
  const outLength = Math.max(1, Math.floor(input.length / ratio));
  const output = new Int16Array(outLength);
  for (let i = 0; i < outLength; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    let count = 0;
    for (let j = start; j < end; j += 1) {
      sum += input[j] ?? 0;
      count += 1;
    }
    const sample = count > 0 ? sum / count : (input[start] ?? 0);
    output[i] = floatSampleToInt16(sample);
  }
  return output;
}

export function encodeWavPcm16(pcm: Int16Array, sampleRate: number): Blob {
  const dataSize = pcm.length * 2;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, dataSize, true);
  let offset = 44;
  for (let i = 0; i < pcm.length; i += 1) {
    view.setInt16(offset, pcm[i] ?? 0, true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function floatToPcm16(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i += 1) {
    output[i] = floatSampleToInt16(input[i] ?? 0);
  }
  return output;
}

function floatSampleToInt16(sample: number): number {
  const clipped = Math.max(-1, Math.min(1, sample));
  return clipped < 0 ? Math.round(clipped * 0x8000) : Math.round(clipped * 0x7fff);
}

function writeString(view: DataView, offset: number, value: string): void {
  for (let i = 0; i < value.length; i += 1) {
    view.setUint8(offset + i, value.charCodeAt(i));
  }
}
