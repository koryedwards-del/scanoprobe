/** Web USB client for BodyMetrix probe 04D8:FBB7 (browser-direct, no server). */

const VENDOR_ID = 0x04d8;
const PRODUCT_ID = 0xfbb7;

export function webUsbSupported() {
  return typeof navigator !== "undefined" && "usb" in navigator;
}

export function webUsbPlatformHint() {
  const ua = navigator.userAgent || "";
  if (/iPhone|iPad|iPod/i.test(ua)) {
    return "iOS does not support Web USB. Use manual mm entry, or use Chrome on a desktop/Android with USB OTG.";
  }
  if (/Firefox/i.test(ua)) {
    return "Firefox does not support Web USB. Use Chrome or Edge, or enter mm manually.";
  }
  if (!webUsbSupported()) {
    return "This browser cannot access USB devices. Use Chrome or Edge on desktop, or enter mm manually.";
  }
  if (!window.isSecureContext) {
    return "Web USB requires HTTPS (or localhost). Deploy with SSL or use http://127.0.0.1 locally.";
  }
  return null;
}

function parseMmFromBytes(payload) {
  if (!payload || payload.length < 2) {
    throw new Error(`Payload too short (${payload?.length || 0} bytes).`);
  }
  const view = payload instanceof Uint8Array ? payload : new Uint8Array(payload);

  for (const offset of [0, 2, 4, 8, 12, 16]) {
    if (offset + 4 <= view.length) {
      const le = new DataView(view.buffer, view.byteOffset + offset, 4).getFloat32(0, true);
      const be = new DataView(view.buffer, view.byteOffset + offset, 4).getFloat32(0, false);
      if (le >= 0.5 && le <= 80) return Math.round(le * 10) / 10;
      if (be >= 0.5 && be <= 80) return Math.round(be * 10) / 10;
    }
    if (offset + 2 <= view.length) {
      const u16le = view[offset] | (view[offset + 1] << 8);
      const u16be = (view[offset] << 8) | view[offset + 1];
      if (u16le >= 5 && u16le <= 800) return Math.round(u16le / 10) / 10;
      if (u16be >= 5 && u16be <= 800) return Math.round(u16be / 10) / 10;
    }
  }
  throw new Error(
    `Could not parse ${view.length} bytes yet. Send capture to update parser.`
  );
}

function concatChunks(chunks) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.length;
  }
  return out;
}

export class BodyMetrixWebUSB {
  constructor() {
    this.device = null;
    this.inEndpoints = [];
    this.outEndpoints = [];
  }

  get connected() {
    return Boolean(this.device?.opened);
  }

  async connect() {
    const hint = webUsbPlatformHint();
    if (hint) throw new Error(hint);

    this.device = await navigator.usb.requestDevice({
      filters: [{ vendorId: VENDOR_ID, productId: PRODUCT_ID }],
    });
    await this.device.open();
    if (this.device.configuration === null) {
      await this.device.selectConfiguration(1);
    }

    this.inEndpoints = [];
    this.outEndpoints = [];
    for (const intf of this.device.configuration.interfaces) {
      await this.device.claimInterface(intf.interfaceNumber);
      for (const alt of intf.alternates) {
        for (const ep of alt.endpoints) {
          if (ep.direction === "in") {
            this.inEndpoints.push({ number: ep.endpointNumber, packetSize: ep.packetSize });
          } else {
            this.outEndpoints.push({ number: ep.endpointNumber, packetSize: ep.packetSize });
          }
        }
      }
    }
    if (!this.inEndpoints.length) {
      throw new Error("No USB IN endpoint found on probe.");
    }
    navigator.usb.addEventListener("disconnect", (e) => {
      if (e.device === this.device) {
        this.device = null;
        this.inEndpoints = [];
        this.outEndpoints = [];
      }
    });
  }

  async _triggerWrites() {
    const payloads = [new Uint8Array([1]), new Uint8Array([0]), new Uint8Array([2])];
    for (const ep of this.outEndpoints) {
      for (const p of payloads) {
        try {
          await this.device.transferOut(ep.number, p);
        } catch {
          /* ignore */
        }
      }
    }
  }

  async listen(durationMs = 8000) {
    if (!this.connected) await this.connect();

    let best = new Uint8Array(0);
    const deadline = Date.now() + durationMs;

    while (Date.now() < deadline) {
      await this._triggerWrites();
      for (const ep of this.inEndpoints) {
        try {
          const result = await this.device.transferIn(ep.number, ep.packetSize || 64);
          if (result.data?.byteLength) {
            const chunk = new Uint8Array(result.data.buffer, result.data.byteOffset, result.data.byteLength);
            if (chunk.length > best.length) best = chunk;
          }
        } catch {
          /* timeout ok */
        }
      }
      if (best.length) break;
      await new Promise((r) => setTimeout(r, 200));
    }

    if (!best.length) {
      throw new Error(
        "No data from probe. Hold on skin and press the button 3–5 seconds."
      );
    }
    return parseMmFromBytes(best);
  }

  async measureMm() {
    return this.listen(10000);
  }
}
