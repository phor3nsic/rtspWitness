# 📹 rtspWitness

A command-line tool that connects to a list of **RTSP** streams, captures a frame
from each camera and generates an **elegant HTML report** with thumbnails, search,
filters, a lightbox and **pagination** for very large lists.

![status](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/use-authorized-green)

---

## ✨ Features

- 🚀 **Parallel capture** (multithreaded) with configurable timeout.
- 🖼️ **HTML report** with dark theme, thumbnails and a fullscreen viewer (lightbox).
- 🔎 **Search and filters** by host, URL or error — and by status (online / failed).
- 📄 **Client-side pagination** (12/24/48/96 per page) for thousands of results.
- 📊 Stats summary (total, captured, failed) and metadata (resolution, timestamp).
- 🧩 Accepts URLs with or without the `rtsp://` prefix, skips comments (`#`) and duplicates.

---

## 📦 Installation

```bash
# (optional) virtual environment
python3 -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt
```

> Requires **Python 3.10+**. OpenCV already ships with the FFmpeg backend needed for RTSP.

---

## ▶️ Usage

```bash
python main.py -l urls.txt -o output
```

| Flag | Description | Default |
|------|-------------|---------|
| `-l`, `--list` | File with one RTSP URL per line **(required)** | — |
| `-o`, `--output` | Output folder | `rtspwitness_output` |
| `-t`, `--timeout` | Connection timeout per camera (seconds) | `10` |
| `-w`, `--workers` | Concurrent captures | `10` |

Full example:

```bash
python main.py -l urls.txt -o output -t 15 -w 20
```

When it finishes, open **`output/report.html`** in your browser.

```
output/
├── images/            # captured .jpg frames
└── report.html        # navigable report
```

---

## 📄 URL list format

One target per line. The `rtsp://` prefix is optional and lines starting with `#` are ignored:

```text
# block A cameras
rtsp://192.168.0.10:554/onvif1
192.168.0.11:554/live.sdp
rtsp://admin:password@192.168.0.12:554/Streaming/Channels/101
```

---

## 🛰️ Generating the list with Nmap

`nmap` is the fastest way to discover cameras exposing the RTSP port
(default **554**, sometimes **8554**) and turn the result into the format this
script expects.

> ⚠️ **Only use this on networks and devices you are authorized to test.**

### 1. Find hosts with RTSP open

```bash
# Scan the subnet for the RTSP port and save the "greppable" output
nmap -p 554 --open -oG rtsp_scan.txt 192.168.0.0/24
```

To also include the alternate port 8554:

```bash
nmap -p 554,8554 --open -oG rtsp_scan.txt 192.168.0.0/24
```

### 2. Convert the Nmap output into a URL list

From the `-oG` (greppable) file, extract `IP:port` and build the URLs:

```bash
grep "Ports:" rtsp_scan.txt \
  | awk '{print $2}' \
  | while read ip; do
      port=$(grep "Host: $ip " rtsp_scan.txt | grep -oE '[0-9]+/open' | cut -d/ -f1 | head -1)
      echo "rtsp://$ip:$port/"
    done > urls.txt
```

**Simple version** (assumes port 554, which covers most cases):

```bash
grep "554/open" rtsp_scan.txt | awk '{print "rtsp://" $2 ":554/"}' > urls.txt
```

### 3. (Optional) Identify the stream path

Many cameras require a specific *path* (e.g. `/onvif1`, `/live.sdp`,
`/Streaming/Channels/101`). The Nmap NSE script helps identify them:

```bash
nmap -p 554 --script rtsp-url-brute 192.168.0.0/24
```

Append the discovered path to the URLs in `urls.txt`. Common paths:

```text
/                              # generic
/live.sdp                      # various vendors
/onvif1                        # ONVIF
/Streaming/Channels/101        # Hikvision
/cam/realmonitor?channel=1&subtype=0   # Dahua
/h264Preview_01_main           # Reolink
```

### 4. Run rtspWitness

```bash
python main.py -l urls.txt -o output -w 20
```

---

## 🔧 Tips

- **Lots of failures?** Increase `--timeout` (slow cameras) or lower `--workers`.
- **Credentials:** include them in the URL → `rtsp://user:password@ip:554/path`.
- **Large report:** pagination is automatic; use the "N / page" selector and the search box.

---

## ⚖️ Legal notice

This tool is intended for **authorized security testing**, internal audits and
educational purposes. Using it against systems without explicit permission may be
illegal. You are solely responsible for how you use it.

---

## 📜 License

Released under the [MIT License](LICENSE).
