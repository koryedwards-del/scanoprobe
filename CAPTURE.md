# Probe USB capture (no BodyView needed)

BodyView is expired — you only need the **wand** and this repo. One capture session maps the protocol.

## 3 steps on your computer

### 1. Install

```bash
cd /path/to/agent
./install.sh
```

**Windows:** install [Python 3](https://python.org), then:

```bat
pip install -r requirements.txt
copy config.example.json config.json
```

You may need [Zadig](https://zadig.akeo.ie/) to bind the probe to **WinUSB** or **libusb-win32** (only if `status` fails with access errors).

**Linux udev** (if permission denied):

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04d8", ATTR{idProduct}=="fbb7", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-bodymetrix.rules
sudo udevadm control --reload
# unplug and replug probe
```

### 2. Confirm probe is visible

```bash
python3 scripts/probe_usb.py status
```

Expect: `Connected: True` and `VID:PID: 0x04D8:0xFBB7`

If false: try another USB port/cable, check `lsusb | grep -i 04d8` (Linux/Mac).

### 3. Capture while measuring

```bash
python3 scripts/probe_usb.py listen --seconds 30
```

1. Run the command  
2. Gel on probe, place on **thigh or waist**  
3. **Press and hold the button 3–5 seconds** (slide slightly like BodyView)  
4. Wait for "Saved … bytes"

Output goes to `captures/<timestamp>.bin` plus `captures/<timestamp>.json` (metadata).

### 4. Send back the capture

Share the `.bin` and `.json` files (or paste the **hex preview** from the terminal).  
We'll update the parser so **From probe** works in Burn & Build LBA.

---

## Other useful commands

```bash
python3 scripts/probe_usb.py describe          # USB endpoints
python3 scripts/probe_usb.py capture             # single 8s read
python3 scripts/analyze_capture.py captures/*.bin  # inspect bytes
python3 run.py                                   # start Burn & Build LBA
```

## If listen returns 0 bytes

The probe may only talk after a **host init command** (BodyView used to send this). Options:

1. **Wireshark + USBPcap** (Windows) or **usbmon** (Linux) while an old BodyView install still runs once — save the `.pcap`
2. Run `python3 scripts/probe_usb.py scan` — tries control transfers and reports any response
3. Use **manual mm entry** in the app until we have one good capture

## App without probe auto-read

```bash
python3 run.py
# open http://127.0.0.1:8765
# enter Thigh mm → Set, Waist mm → Set, paste formula → Calculate
```
