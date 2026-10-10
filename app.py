"""
TurboGrab - local high-speed video downloader (yt-dlp powered).
Runs on your own PC, so it uses your full internet speed.
Run: python app.py  -> opens http://127.0.0.1:5055
"""
import os
import shutil
import threading
import uuid
import webbrowser

from flask import Flask, jsonify, request, Response

import yt_dlp

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = shutil.which("ffmpeg")

ARIA2C = shutil.which("aria2c")
DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "TurboGrab")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Flask(__name__)
jobs = {}

QUALITY = {
    "best": "bv*+ba/b",
    "2160": "bv*[height<=2160]+ba/b[height<=2160]",
    "1440": "bv*[height<=1440]+ba/b[height<=1440]",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]",
    "720": "bv*[height<=720]+ba/b[height<=720]",
    "audio": "ba/b",
}


def human(n):
    if not n:
        return "-"
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def run_job(job_id, url, quality):
    job = jobs[job_id]

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            job.update(
                status="downloading",
                percent=round(done / total * 100, 1) if total else 0,
                speed=human(d.get("speed")) + "/s" if d.get("speed") else "-",
                eta=f"{d.get('eta')}s" if d.get("eta") is not None else "-",
                size=human(total),
                title=d.get("info_dict", {}).get("title", job["title"]),
            )
        elif d["status"] == "finished":
            job.update(status="merging", percent=100)

    opts = {
        "format": QUALITY.get(quality, QUALITY["best"]),
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title).150B [%(id)s].%(ext)s"),
        "progress_hooks": [hook],
        "concurrent_fragment_downloads": 16,
        "http_chunk_size": 10 * 1024 * 1024,
        "retries": 10,
        "fragment_retries": 10,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if FFMPEG:
        opts["ffmpeg_location"] = FFMPEG
    if quality == "audio":
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}
        ]
    else:
        opts["merge_output_format"] = "mp4"
    if ARIA2C:
        opts["external_downloader"] = {"default": "aria2c"}
        opts["external_downloader_args"] = {
            "aria2c": ["-x", "16", "-s", "16", "-k", "1M", "--summary-interval=1"]
        }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            job["title"] = info.get("title", "video")
        job.update(status="done", percent=100)
    except Exception as e:
        job.update(status="error", error=str(e)[:300])


@app.post("/api/download")
def start():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify(error="Paste a link first"), 400
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = dict(status="starting", percent=0, speed="-", eta="-",
                        size="-", title=url, error=None)
    threading.Thread(target=run_job, args=(job_id, url, data.get("quality", "best")),
                     daemon=True).start()
    return jsonify(id=job_id)


@app.get("/api/jobs")
def list_jobs():
    return jsonify(jobs)


@app.post("/api/open")
def open_folder():
    os.startfile(DOWNLOAD_DIR) if os.name == "nt" else None
    return jsonify(ok=True)


@app.get("/")
def index():
    return Response(PAGE.replace("{{BOOST}}", "aria2c ON" if ARIA2C else "standard mode")
                    .replace("{{FF}}", "" if FFMPEG else "ffmpeg missing - audio won't merge!"),
                    mimetype="text/html")


PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>TurboGrab</title><style>
*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;background:#0e0f13;color:#eee}
.wrap{max-width:720px;margin:40px auto;padding:0 16px}
h1{margin:0 0 4px;font-size:28px}h1 span{color:#ff3d3d}
.sub{color:#888;font-size:13px;margin-bottom:20px}.warn{color:#ffb020}
.row{display:flex;gap:8px;flex-wrap:wrap}
input,select,button{font-size:15px;padding:12px;border-radius:10px;border:1px solid #2a2c35;background:#171920;color:#eee}
input{flex:1;min-width:220px}button{background:#ff3d3d;border:none;font-weight:700;cursor:pointer}
button.ghost{background:#171920;border:1px solid #2a2c35;font-weight:400}
.job{background:#171920;border:1px solid #2a2c35;border-radius:12px;padding:14px;margin-top:12px}
.t{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar{height:8px;background:#2a2c35;border-radius:9px;margin:10px 0;overflow:hidden}
.bar i{display:block;height:100%;background:#ff3d3d;transition:width .3s}
.meta{display:flex;gap:16px;font-size:13px;color:#aaa;flex-wrap:wrap}
.done .bar i{background:#2ecc71}.err{color:#ff6b6b;font-size:13px}
</style></head><body><div class=wrap>
<h1>Turbo<span>Grab</span></h1>
<div class=sub>Saves to Downloads/TurboGrab &middot; {{BOOST}} <span class=warn>{{FF}}</span></div>
<div class=row>
<input id=url placeholder="Paste video link...">
<select id=q><option value=best>Best quality</option><option value=2160>4K</option>
<option value=1440>1440p</option><option value=1080>1080p</option><option value=720>720p</option>
<option value=audio>MP3 audio</option></select>
<button onclick=go()>Download</button>
<button class=ghost onclick="fetch('/api/open',{method:'POST'})">Open folder</button>
</div><div id=jobs></div></div>
<script>
const $=s=>document.querySelector(s);
$('#url').addEventListener('keydown',e=>{if(e.key==='Enter')go()});
async function go(){const url=$('#url').value.trim();if(!url)return;
 const r=await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({url,quality:$('#q').value})});
 if(r.ok)$('#url').value='';else alert((await r.json()).error)}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function poll(){try{const j=await (await fetch('/api/jobs')).json();
 $('#jobs').innerHTML=Object.values(j).reverse().map(x=>`<div class="job ${x.status}">
 <div class=t>${esc(x.title)}</div><div class=bar><i style="width:${x.percent}%"></i></div>
 <div class=meta><span>${x.status}</span><span>${x.percent}%</span><span>${x.speed}</span>
 <span>ETA ${x.eta}</span><span>${x.size}</span></div>
 ${x.error?`<div class=err>${esc(x.error)}</div>`:''}</div>`).join('')}catch(e){}
 setTimeout(poll,700)}poll();
</script></body></html>"""

if __name__ == "__main__":
    threading.Timer(1, lambda: webbrowser.open("http://127.0.0.1:5055")).start()
    app.run(host="127.0.0.1", port=5055, threaded=True)
