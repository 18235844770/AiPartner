import assert from "node:assert/strict";

function mergeChunks(chunks) {
  const total = chunks.reduce((sum, item) => sum + item.length, 0);
  const merged = new Float32Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}

function floatSampleToInt16(sample) {
  const clipped = Math.max(-1, Math.min(1, sample));
  return clipped < 0 ? Math.round(clipped * 0x8000) : Math.round(clipped * 0x7fff);
}

function downsampleTo16k(input, inputRate) {
  const target = 16000;
  if (inputRate === target) {
    const output = new Int16Array(input.length);
    for (let i = 0; i < input.length; i += 1) {
      output[i] = floatSampleToInt16(input[i] ?? 0);
    }
    return output;
  }
  const ratio = inputRate / target;
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
    output[i] = floatSampleToInt16(count > 0 ? sum / count : input[start] ?? 0);
  }
  return output;
}

const merged = mergeChunks([new Float32Array([0.1, 0.2]), new Float32Array([0.3])]);
assert.equal(merged.length, 3);
const pcm = downsampleTo16k(new Float32Array(32000).fill(0.25), 32000);
assert.equal(pcm.length, 16000);
console.log("microphone helpers ok");
