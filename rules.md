# Rules — SCANOPROBE / BodyMetrix wand (Mac)

> Same content as [`rules.doc`](rules.doc) — use either file. This `.md` copy is for easy browsing on GitHub.

Lock-in doc. Verified on Kory's iMac, Sep 2026.

---

## How we work

1. **Simple first** — try the smallest thing that could work before adding layers. Same code path that already worked beats a clever rewrite. No extra tools, abstractions, or delivery paths unless the simple one fails.
2. **Plain language** — it's a project, not a research problem. No "the hard part," "blocker," or drama. State what's done and what's next.
3. **Start fresh** = get the foundation right, then build up. Not "throw away what worked."
4. **One layer, one check, clear answer** — like System Report, then Python.
5. **Do not ask** if the wand is plugged in or green-lit when the user says it is.
6. **Cloud ≠ Mac** — Cursor cloud cannot see the wand. All USB checks run on the iMac only. **User works locally** (Cursor on Mac + GitHub) — not cloud agents.
7. **No guessing** — no extra tools (Homebrew, project folders) unless a layer fails and we add one fix at a time.

---

## Device (verified)

| Field | Value |
|-------|--------|
| Name in System Report | BodyMetrix (5.94) |
| Manufacturer | IntelaMetrix Inc. |
| USB Vendor ID | 0x04d8 |
| USB Product ID | 0xfbb7 |

---

## Wand hardware (reset — verified)

**What it is:** BodyMetrix / SCANOPROBE **BX-family USB probe** — handheld transducer, not a self-contained display unit.

**What it looks like:**
- Silver body, blue accents, **BodyMetrix BX 2000** labeling (same product line)
- **Blue transducer face** at the bottom (contacts skin with gel)
- **Black cable** from the top → **USB** to the Mac

**Physical controls — one only:**
- **One side button** (easy-reach thumb button) = **SEND**

**NOT on the wand (software only):**
- No LCD, no mm readout, no 0–50 LED bar, no gain +/−, no hold switch, no view toggle

Those live in **ScanoProbe on the Mac** (and were in BodyView before it expired) — SCANOPROBE-style UI driven from the waveform bytes. Gain +/−, mm, LEDs, waveform, 2D view = **screen**, not hardware.

**Connection to Mac:** Wand is **USB-A**. User connects via **Apple USB‑A → USB‑C dongle** to the Mac. (Verified setup — not a project requirement, just this machine.)

**On SEND:** wand sends ultrasound data to the Mac over USB. Communication works; **interpretation in software** is what we are fixing.

### Data flow (locked)
