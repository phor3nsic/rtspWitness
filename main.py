#!/usr/bin/env python3
"""
rtspWitness — captures frames from RTSP streams and generates an elegant HTML report.

Basic usage:
    python main.py -l urls.txt -o output

The URL list (-l) is a text file with one RTSP URL per line. See README.md to
generate this list automatically from an nmap scan.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from datetime import datetime

try:
    import cv2
except ImportError:
    sys.exit(
        "Error: the 'opencv-python' dependency is not installed.\n"
        "Install it with: pip install -r requirements.txt"
    )


# ---------------------------------------------------------------------------
# Terminal colors (degrade to empty when there is no TTY)
# ---------------------------------------------------------------------------
class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"
    BOLD = "\033[1m"
    END = "\033[0m"

    @classmethod
    def disable(cls):
        for attr in ("GREEN", "RED", "YELLOW", "CYAN", "GRAY", "BOLD", "END"):
            setattr(cls, attr, "")


if not sys.stdout.isatty():
    C.disable()


# ---------------------------------------------------------------------------
# Data model for each capture
# ---------------------------------------------------------------------------
@dataclass
class CaptureResult:
    url: str
    status: str = "fail"            # "ok" | "fail"
    image: str = ""                 # relative image path (from output)
    error: str = ""                 # error message, if any
    width: int = 0
    height: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def host(self) -> str:
        """Extracts 'host:port' from the URL for friendly display."""
        body = self.url.split("://", 1)[-1]
        if "@" in body:
            body = body.split("@", 1)[-1]
        return body.split("/", 1)[0]


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------
def _safe_name(url: str) -> str:
    """Builds a safe filename from the URL."""
    name = (
        url.replace("rtsp://", "")
        .replace("@", "_")
        .replace(":", "_")
        .replace("/", "_")
        .replace("?", "_")
        .replace("&", "_")
    )
    return name[:120] or "stream"


def capture_frame(url: str, output: str, timeout: int) -> CaptureResult:
    """Connects to the RTSP stream, captures one frame and saves it as JPG."""
    result = CaptureResult(url=url)

    # Configure the FFmpeg timeout (in microseconds) before opening the stream.
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
        f"rtsp_transport;tcp|stimeout;{timeout * 1_000_000}"
    )

    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            result.error = "Could not open the stream (timeout or refused)."
            return result

        ret, frame = cap.read()
        if not ret or frame is None:
            result.error = "Connection opened, but no frame was received."
            return result

        height, width = frame.shape[:2]
        rel_path = os.path.join("images", f"{_safe_name(url)}.jpg")
        abs_path = os.path.join(output, rel_path)
        cv2.imwrite(abs_path, frame)

        result.status = "ok"
        result.image = rel_path
        result.width = int(width)
        result.height = int(height)
    except Exception as exc:  # noqa: BLE001 — we want to record any failure
        result.error = f"Exception: {exc}"
    finally:
        cap.release()

    return result


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------
def generate_report(output: str, results: list[CaptureResult]) -> str:
    report_path = os.path.join(output, "report.html")

    ok = sum(1 for r in results if r.status == "ok")
    fail = len(results) - ok
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Data is embedded as JSON and rendering/pagination is done client-side
    # (JavaScript), which keeps the HTML lightweight even with thousands of items.
    data_json = json.dumps([asdict(r) for r in results], ensure_ascii=False)

    html = _HTML_TEMPLATE.format(
        generated_at=generated_at,
        total=len(results),
        ok=ok,
        fail=fail,
        data_json=data_json,
    )

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    return report_path


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>rtspWitness — Report</title>
<style>
  :root {{
    --bg: #0d1117;
    --bg-elev: #161b22;
    --bg-elev2: #1c2330;
    --border: #2d3645;
    --text: #e6edf3;
    --muted: #8b949e;
    --accent: #58a6ff;
    --ok: #3fb950;
    --fail: #f85149;
    --shadow: 0 8px 24px rgba(0,0,0,.4);
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    padding: 0 0 60px;
  }}
  header {{
    background: linear-gradient(135deg, #161b22 0%, #1c2742 100%);
    border-bottom: 1px solid var(--border);
    padding: 28px 24px;
  }}
  header .wrap {{ max-width: 1280px; margin: 0 auto; }}
  h1 {{
    font-size: 26px; font-weight: 700; letter-spacing: -.5px;
    display: flex; align-items: center; gap: 10px;
  }}
  h1 .dot {{ color: var(--accent); }}
  header p {{ color: var(--muted); margin-top: 6px; font-size: 14px; }}

  .stats {{ display: flex; gap: 14px; flex-wrap: wrap; margin-top: 20px; }}
  .stat {{
    background: var(--bg-elev); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 20px; min-width: 120px;
  }}
  .stat .num {{ font-size: 24px; font-weight: 700; }}
  .stat .lbl {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }}
  .stat.ok .num {{ color: var(--ok); }}
  .stat.fail .num {{ color: var(--fail); }}
  .stat.accent .num {{ color: var(--accent); }}

  .toolbar {{
    max-width: 1280px; margin: 24px auto 0; padding: 0 24px;
    display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
  }}
  .search {{
    flex: 1; min-width: 220px; position: relative;
  }}
  .search input {{
    width: 100%; background: var(--bg-elev); border: 1px solid var(--border);
    color: var(--text); border-radius: 8px; padding: 10px 12px 10px 36px; font-size: 14px;
  }}
  .search input:focus {{ outline: none; border-color: var(--accent); }}
  .search::before {{
    content: "⌕"; position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
    color: var(--muted); font-size: 18px;
  }}
  .filters {{ display: flex; gap: 8px; }}
  .filters button {{
    background: var(--bg-elev); border: 1px solid var(--border); color: var(--muted);
    padding: 9px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600;
    transition: all .15s;
  }}
  .filters button:hover {{ color: var(--text); border-color: var(--accent); }}
  .filters button.active {{ background: var(--accent); color: #04122b; border-color: var(--accent); }}

  .grid {{
    max-width: 1280px; margin: 24px auto 0; padding: 0 24px;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px;
  }}
  .card {{
    background: var(--bg-elev); border: 1px solid var(--border); border-radius: 12px;
    overflow: hidden; transition: transform .15s, border-color .15s;
  }}
  .card:hover {{ transform: translateY(-3px); border-color: var(--accent); }}
  .card .thumb {{
    position: relative; aspect-ratio: 16/9; background: #000;
    display: flex; align-items: center; justify-content: center; overflow: hidden;
  }}
  .card .thumb img {{ width: 100%; height: 100%; object-fit: cover; cursor: zoom-in; }}
  .card .thumb .noimg {{ color: var(--muted); font-size: 13px; text-align: center; padding: 20px; }}
  .badge {{
    position: absolute; top: 10px; left: 10px; font-size: 11px; font-weight: 700;
    padding: 3px 9px; border-radius: 20px; text-transform: uppercase; letter-spacing: .5px;
  }}
  .badge.ok {{ background: rgba(63,185,80,.18); color: var(--ok); border: 1px solid rgba(63,185,80,.4); }}
  .badge.fail {{ background: rgba(248,81,73,.18); color: var(--fail); border: 1px solid rgba(248,81,73,.4); }}
  .res {{
    position: absolute; bottom: 10px; right: 10px; font-size: 11px;
    background: rgba(0,0,0,.6); color: #fff; padding: 2px 8px; border-radius: 6px;
  }}
  .card .body {{ padding: 12px 14px; }}
  .card .host {{ font-size: 14px; font-weight: 600; word-break: break-all; }}
  .card .url {{ font-size: 12px; color: var(--muted); word-break: break-all; margin-top: 4px; }}
  .card .err {{ font-size: 12px; color: var(--fail); margin-top: 6px; }}
  .card .meta {{ font-size: 11px; color: var(--gray, #6e7681); margin-top: 6px; }}

  .empty {{ text-align: center; color: var(--muted); padding: 80px 20px; }}

  .pagination {{
    max-width: 1280px; margin: 28px auto 0; padding: 0 24px;
    display: flex; gap: 6px; justify-content: center; align-items: center; flex-wrap: wrap;
  }}
  .pagination button {{
    background: var(--bg-elev); border: 1px solid var(--border); color: var(--text);
    min-width: 38px; height: 38px; padding: 0 10px; border-radius: 8px; cursor: pointer; font-size: 13px;
  }}
  .pagination button:hover:not(:disabled) {{ border-color: var(--accent); }}
  .pagination button.active {{ background: var(--accent); color: #04122b; border-color: var(--accent); font-weight: 700; }}
  .pagination button:disabled {{ opacity: .4; cursor: not-allowed; }}
  .pagination .info {{ color: var(--muted); font-size: 13px; margin: 0 10px; }}
  .pagination select {{
    background: var(--bg-elev); border: 1px solid var(--border); color: var(--text);
    border-radius: 8px; padding: 8px; font-size: 13px;
  }}

  /* Lightbox */
  .lightbox {{
    position: fixed; inset: 0; background: rgba(0,0,0,.92); display: none;
    align-items: center; justify-content: center; z-index: 100; padding: 30px; flex-direction: column;
  }}
  .lightbox.open {{ display: flex; }}
  .lightbox img {{ max-width: 95%; max-height: 85%; border-radius: 8px; box-shadow: var(--shadow); }}
  .lightbox .cap {{ color: var(--text); margin-top: 16px; font-size: 14px; word-break: break-all; text-align: center; }}
  .lightbox .close {{
    position: absolute; top: 20px; right: 28px; color: #fff; font-size: 38px;
    cursor: pointer; line-height: 1; background: none; border: none;
  }}
  footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 50px; }}
  footer a {{ color: var(--accent); text-decoration: none; }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1><span class="dot">●</span> rtspWitness</h1>
    <p>RTSP capture report · generated at {generated_at}</p>
    <div class="stats">
      <div class="stat accent"><div class="num">{total}</div><div class="lbl">Total</div></div>
      <div class="stat ok"><div class="num">{ok}</div><div class="lbl">Captured</div></div>
      <div class="stat fail"><div class="num">{fail}</div><div class="lbl">Failed</div></div>
    </div>
  </div>
</header>

<div class="toolbar">
  <div class="search"><input id="search" type="text" placeholder="Filter by host, URL or error..."></div>
  <div class="filters">
    <button data-filter="all" class="active">All</button>
    <button data-filter="ok">Captured</button>
    <button data-filter="fail">Failed</button>
  </div>
</div>

<div class="grid" id="grid"></div>
<div class="empty" id="empty" style="display:none">No results found.</div>
<div class="pagination" id="pagination"></div>

<div class="lightbox" id="lightbox">
  <button class="close" id="lbClose">&times;</button>
  <img id="lbImg" src="" alt="">
  <div class="cap" id="lbCap"></div>
</div>

<footer>
  Generated by <strong>rtspWitness</strong> · <a href="https://github.com/">github</a>
</footer>

<script>
const DATA = {data_json};
let perPage = 24;
let page = 1;
let filter = "all";
let query = "";

const grid = document.getElementById("grid");
const empty = document.getElementById("empty");
const pag = document.getElementById("pagination");

function escapeHtml(s) {{
  return (s || "").replace(/[&<>"']/g, c => (
    {{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }}[c]
  ));
}}

function getFiltered() {{
  const q = query.toLowerCase();
  return DATA.filter(d => {{
    if (filter !== "all" && d.status !== filter) return false;
    if (!q) return true;
    return (d.url + " " + (d.error || "")).toLowerCase().includes(q);
  }});
}}

function hostOf(url) {{
  let b = url.split("://").pop();
  if (b.includes("@")) b = b.split("@").pop();
  return b.split("/")[0];
}}

function render() {{
  const items = getFiltered();
  const totalPages = Math.max(1, Math.ceil(items.length / perPage));
  if (page > totalPages) page = totalPages;
  const start = (page - 1) * perPage;
  const slice = items.slice(start, start + perPage);

  grid.innerHTML = "";
  empty.style.display = items.length ? "none" : "block";

  for (const d of slice) {{
    const card = document.createElement("div");
    card.className = "card";
    const host = escapeHtml(hostOf(d.url));
    const url = escapeHtml(d.url);
    let thumb;
    if (d.status === "ok" && d.image) {{
      thumb = `<img src="${{encodeURI(d.image)}}" loading="lazy" data-full="${{encodeURI(d.image)}}" data-cap="${{url}}" alt="${{host}}">`
            + `<span class="res">${{d.width}}×${{d.height}}</span>`;
    }} else {{
      thumb = `<div class="noimg">⚠ No image</div>`;
    }}
    const badge = d.status === "ok"
      ? `<span class="badge ok">online</span>`
      : `<span class="badge fail">failed</span>`;
    const err = d.error ? `<div class="err">${{escapeHtml(d.error)}}</div>` : "";
    card.innerHTML =
      `<div class="thumb">${{badge}}${{thumb}}</div>` +
      `<div class="body">` +
        `<div class="host">${{host}}</div>` +
        `<div class="url">${{url}}</div>` +
        err +
        `<div class="meta">${{escapeHtml(d.timestamp || "")}}</div>` +
      `</div>`;
    grid.appendChild(card);
  }}

  // Lightbox bindings
  grid.querySelectorAll("img[data-full]").forEach(img => {{
    img.addEventListener("click", () => openLightbox(img.dataset.full, img.dataset.cap));
  }});

  renderPagination(items.length, totalPages);
}}

function renderPagination(total, totalPages) {{
  pag.innerHTML = "";
  if (!total) return;

  const mk = (label, p, opts = {{}}) => {{
    const b = document.createElement("button");
    b.textContent = label;
    if (opts.active) b.className = "active";
    if (opts.disabled) b.disabled = true;
    if (!opts.disabled && !opts.active) b.addEventListener("click", () => {{ page = p; render(); window.scrollTo({{top:0,behavior:"smooth"}}); }});
    return b;
  }};

  pag.appendChild(mk("«", 1, {{ disabled: page === 1 }}));
  pag.appendChild(mk("‹", page - 1, {{ disabled: page === 1 }}));

  const win = 2;
  let lo = Math.max(1, page - win), hi = Math.min(totalPages, page + win);
  if (lo > 1) {{ pag.appendChild(mk("1", 1, {{ active: page === 1 }})); if (lo > 2) pag.appendChild(dots()); }}
  for (let p = lo; p <= hi; p++) pag.appendChild(mk(String(p), p, {{ active: p === page }}));
  if (hi < totalPages) {{ if (hi < totalPages - 1) pag.appendChild(dots()); pag.appendChild(mk(String(totalPages), totalPages, {{ active: page === totalPages }})); }}

  pag.appendChild(mk("›", page + 1, {{ disabled: page === totalPages }}));
  pag.appendChild(mk("»", totalPages, {{ disabled: page === totalPages }}));

  const info = document.createElement("span");
  info.className = "info";
  info.textContent = `${{total}} result(s) · page ${{page}}/${{totalPages}}`;
  pag.appendChild(info);

  const sel = document.createElement("select");
  [12, 24, 48, 96].forEach(n => {{
    const o = document.createElement("option");
    o.value = n; o.textContent = n + " / page";
    if (n === perPage) o.selected = true;
    sel.appendChild(o);
  }});
  sel.addEventListener("change", () => {{ perPage = +sel.value; page = 1; render(); }});
  pag.appendChild(sel);
}}

function dots() {{
  const s = document.createElement("span");
  s.className = "info"; s.textContent = "…";
  return s;
}}

// Lightbox
const lightbox = document.getElementById("lightbox");
const lbImg = document.getElementById("lbImg");
const lbCap = document.getElementById("lbCap");
function openLightbox(src, cap) {{
  lbImg.src = src; lbCap.textContent = decodeURIComponent(cap);
  lightbox.classList.add("open");
}}
function closeLightbox() {{ lightbox.classList.remove("open"); lbImg.src = ""; }}
document.getElementById("lbClose").addEventListener("click", closeLightbox);
lightbox.addEventListener("click", e => {{ if (e.target === lightbox) closeLightbox(); }});
document.addEventListener("keydown", e => {{ if (e.key === "Escape") closeLightbox(); }});

// Controls
document.getElementById("search").addEventListener("input", e => {{ query = e.target.value; page = 1; render(); }});
document.querySelectorAll(".filters button").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll(".filters button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    filter = btn.dataset.filter; page = 1; render();
  }});
}});

render();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def read_urls(path: str) -> list[str]:
    if not os.path.isfile(path):
        sys.exit(f"{C.RED}Error: URL list file not found: {path}{C.END}")
    with open(path, encoding="utf-8", errors="ignore") as f:
        urls = []
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                # Accept lines without the rtsp:// scheme and add it automatically.
                if "://" not in line:
                    line = "rtsp://" + line
                urls.append(line)
    # Remove duplicates while preserving order.
    return list(dict.fromkeys(urls))


def main():
    parser = argparse.ArgumentParser(
        description="Captures frames from RTSP streams and generates an elegant HTML report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  python main.py -l urls.txt -o output -t 10 -w 16",
    )
    parser.add_argument("-l", "--list", dest="list_of_urls", required=True,
                        help="File with one RTSP URL per line.")
    parser.add_argument("-o", "--output", default="rtspwitness_output",
                        help="Output folder (default: rtspwitness_output).")
    parser.add_argument("-t", "--timeout", type=int, default=10,
                        help="Connection timeout in seconds (default: 10).")
    parser.add_argument("-w", "--workers", type=int, default=10,
                        help="Concurrent captures (default: 10).")
    args = parser.parse_args()

    os.makedirs(os.path.join(args.output, "images"), exist_ok=True)
    urls = read_urls(args.list_of_urls)

    if not urls:
        sys.exit(f"{C.YELLOW}No valid URLs found in the list.{C.END}")

    print(f"{C.BOLD}{C.CYAN}rtspWitness{C.END} — {len(urls)} target(s) · "
          f"{args.workers} worker(s) · timeout {args.timeout}s\n")

    results: list[CaptureResult] = []
    done = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(capture_frame, u, args.output, args.timeout): u for u in urls}
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            done += 1
            if res.status == "ok":
                tag = f"{C.GREEN}[OK]{C.END}  "
                extra = f" {C.GRAY}({res.width}x{res.height}){C.END}"
            else:
                tag = f"{C.RED}[FAIL]{C.END}"
                extra = f" {C.GRAY}{res.error}{C.END}"
            print(f"  {tag} [{done}/{len(urls)}] {res.host}{extra}")

    # Keep the original list order in the report.
    order = {u: i for i, u in enumerate(urls)}
    results.sort(key=lambda r: order.get(r.url, 1e9))

    ok = sum(1 for r in results if r.status == "ok")
    elapsed = time.time() - start
    print(f"\n{C.BOLD}Done{C.END}: {C.GREEN}{ok} ok{C.END}, "
          f"{C.RED}{len(results) - ok} failed{C.END} in {elapsed:.1f}s")

    report = generate_report(args.output, results)
    print(f"Report: {C.CYAN}{os.path.abspath(report)}{C.END}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(f"\n{C.YELLOW}Interrupted by the user.{C.END}")
