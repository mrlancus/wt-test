// Reading a .wrpl header (layout verified in docs/DATA.md).

const MAGIC = 0x1000ace5;
export const HEADER_BYTES = 1226;

function text(bytes, at, size) {
  const raw = bytes.subarray(at, at + size);
  const end = raw.indexOf(0);
  return new TextDecoder().decode(end < 0 ? raw : raw.subarray(0, end));
}

/** The header fields we key storage and the manifest on. Throws on anything that is not a replay. */
export function readHeader(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes.length < HEADER_BYTES) throw new Error("file too short for a replay header");
  const view = new DataView(buffer instanceof ArrayBuffer ? buffer : bytes.buffer, bytes.byteOffset);
  if (view.getUint32(0, true) !== MAGIC) throw new Error("not a War Thunder replay (bad magic)");
  const level = text(bytes, 8, 128);
  return {
    version: view.getUint32(4, true),
    map: level.replace(/^levels\//, "").replace(/\.bin$/, ""),
    session: view.getBigUint64(732, true).toString(16).padStart(16, "0"),
    part: bytes[740],
    startTime: view.getUint32(908, true),
  };
}
