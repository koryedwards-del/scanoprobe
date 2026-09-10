# Rules — SCANOPROBE / BodyMetrix wand (Mac)

> Same content as [`rules.doc`](rules.doc) — use either file. This `.md` copy is for easy browsing on GitHub.

Lock-in doc. Verified on Kory's iMac, Sep 2026.

---

## On Kory's Mac

**Project folder:** `~/scanoprobe` (home folder — **not** Desktop)

**Run the app:** double-click `Start Scanoprobe.command` in Finder.

**Terminal:** Kory starts a **clean Terminal** each time. **Every command block must begin with:**

```bash
cd ~/scanoprobe
```

Never run `.venv/bin/python …` from `~` (home) — that folder has no `.venv`.

**USB driver error:** run `./fix-usb.sh` from `~/scanoprobe`, then try again.

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

### LED scale workflow (locked — Kory, years of use)

**Assume:** gel on skin, **SEND held**.

1. **Gain +** until the **0–50 LED bar fills** (all lights on).
2. **Gain −** until only **three consecutive LEDs** remain in the fat zone.
3. **Ignore LEDs 1, 2, 3** — those are **skin depth**, not the fat reading.
4. Example bracket: **14, 15, 16** — **15 is the mm reading** (center LED solid).
5. Fine-tune gain: **14 and 16 bounce**, **15 stays solid** — that is correct.
6. **Repeat steps 2–5 three times** — confirm the center mm (e.g. 15) stays consistent before locking. (Production standard: 20k+ users, 15 years.)
7. **HOLD** locks the mm. Put down wand.

Gain changes **which echoes are visible** on the bar. It does not change the mm formula — you tune until the fascia sits in the three-LED bracket.

### Data flow (locked)

```
SEND held + gel
  → USB bulk packet (header 00 00 00 XX + envelope waveform)
  → decode peak depth → mm on 0–50 LED bar + LCD
  → gain + fills bar, gain − brackets to 3 LEDs (ignore 1–3 skin)
  → repeat bracket tune ×3, confirm center mm stable
  → HOLD locks center LED mm (e.g. 15 from 14–15–16)
```

**Do not** use header byte 3 as mm — it is not the thickness (e.g. `04` → 4.0 mm is wrong).

**Fat mm (decode):** assume **3 mm skin**, find **fat/muscle fascia** peak on envelope (bytes 4+, 0.1 mm/bin), **fat = fascia depth − 3 mm**. Gain must be high enough for the fascia echo to appear before bracketing.

---

## Status (Sep 2026)

| Layer | State |
|-------|--------|
| UI (LED bar, gain, HOLD) | Working |
| USB + tick loop | Working |
| mm decode | Not accurate — needs capture + validate against research |

**BodyView:** expired, reference only. **B&B:** retired.

**Next:** one raw capture while holding SEND → paste hex → align decode to research (two peaks, sample index, 1400 m/s fat).
