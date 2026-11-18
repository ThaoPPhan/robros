"""Web UI: live MJPEG streams, status, calibration page, snapshots, arm/disarm.

  /              live view (annotated stream + mask stream + controls)
  /stream.mjpg   annotated camera stream
  /mask.mjpg     binary mask stream
  /frame.jpg, /mask.jpg  single current frame (add ?still to / or /calibrate to use these)
  /calibrate     HSV / ROI sliders applied live, Save writes config.yaml
  /api/status    GET   latest numbers as JSON
  /api/params    GET   detector params / POST {key: value} to change live
  /api/save      POST  write current detector params to config.yaml
  /api/sample    GET   ?x=&y=  HSV of a 5x5 patch of the raw frame (click-to-sample)
  /api/snapshot  POST  save the raw frame (PNG) + annotated view to snapshots/
  /api/arm       POST  {"armed": true|false}
"""

import logging
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request
from werkzeug.serving import make_server


class Hub:
    """Thread-safe hand-off of frames and commands between vision loop and web server."""

    def __init__(self, jpeg_quality=70):
        self.q = int(jpeg_quality)
        self.cond = threading.Condition()
        self.frame_id = 0
        self.raw = self.view = self.mask = None
        self.status = {}
        self.viewers = 0
        self.t_still = -1e9          # last /frame.jpg request
        self._jpeg_cache = {}
        self._pending = {}
        self._actions = []

    # vision loop side
    def publish(self, raw, view, mask, status):
        with self.cond:
            self.raw, self.view, self.mask = raw, view, mask
            self.status = status
            self.frame_id += 1
            self._jpeg_cache = {}
            self.cond.notify_all()

    def wants_view(self):
        return self.viewers > 0 or time.monotonic() - self.t_still < 3.0

    def take_pending(self):
        with self.cond:
            p, self._pending = self._pending, {}
            a, self._actions = self._actions, []
        return p, a

    def peek_pending(self):
        with self.cond:
            return dict(self._pending)

    # server side
    def set_params(self, params):
        with self.cond:
            self._pending.update(params)

    def action(self, name, **kw):
        with self.cond:
            self._actions.append((name, kw))

    def jpeg(self, kind, after_id, timeout=2.0):
        with self.cond:
            self.cond.wait_for(lambda: self.frame_id != after_id, timeout)
            fid = self.frame_id
            if kind in self._jpeg_cache:
                return self._jpeg_cache[kind], fid
            img = self.view if kind == "view" else self.mask
            if img is None and kind == "view":
                img = self.raw
        if img is None:
            return None, fid
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self.q])
        data = buf.tobytes() if ok else None
        with self.cond:
            if fid == self.frame_id:
                self._jpeg_cache[kind] = data
        return data, fid


def create_app(hub, get_params, save_params, stream_fps=15):
    app = Flask(__name__)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    min_dt = 1.0 / max(1, stream_fps)

    def mjpeg(kind):
        def gen():
            with hub.cond:
                hub.viewers += 1
            try:
                fid, t_last = -1, 0.0
                while True:
                    wait = t_last + min_dt - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)
                    data, fid = hub.jpeg(kind, fid)
                    t_last = time.monotonic()
                    if data is None:
                        continue
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                           str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
            finally:
                with hub.cond:
                    hub.viewers -= 1
        return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame",
                        headers={"Cache-Control": "no-cache"})

    @app.route("/")
    def index():
        return INDEX_HTML

    @app.route("/calibrate")
    def calibrate():
        return CALIBRATE_HTML

    @app.route("/stream.mjpg")
    def stream():
        return mjpeg("view")

    @app.route("/mask.mjpg")
    def mask_stream():
        return mjpeg("mask")

    @app.route("/frame.jpg")
    @app.route("/mask.jpg")
    def still():
        kind = "mask" if request.path == "/mask.jpg" else "view"
        fresh = hub.wants_view()
        hub.t_still = time.monotonic()
        fid = hub.frame_id
        for _ in range(1 if fresh else 2):   # first request: wait for an annotated frame
            data, fid = hub.jpeg(kind, fid, timeout=0.5)
        if data is None:
            return "no frame yet", 503
        return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "no-cache"})

    @app.route("/api/status")
    def status():
        return jsonify(hub.status)

    @app.route("/api/params", methods=["GET", "POST"])
    def params():
        if request.method == "POST":
            data = request.get_json(force=True) or {}
            try:
                clean = _validate(data)
            except (ValueError, TypeError) as e:
                return jsonify(error=str(e)), 400
            hub.set_params(clean)
            merged = dict(get_params())
            merged.update(clean)
            return jsonify(merged)
        return jsonify(get_params())

    @app.route("/api/save", methods=["POST"])
    def save():
        try:
            p = save_params()
        except Exception as e:  # noqa: BLE001 - report any failure to the page
            return jsonify(ok=False, error=str(e)), 500
        return jsonify(ok=True, saved=p)

    @app.route("/api/sample")
    def sample():
        raw = hub.raw
        if raw is None:
            return jsonify(error="no frame yet"), 503
        h, w = raw.shape[:2]
        x = int(float(request.args.get("x", 0.5)) * w)
        y = int(float(request.args.get("y", 0.5)) * h)
        x0, y0 = max(0, x - 2), max(0, y - 2)
        patch = raw[y0:y + 3, x0:x + 3]
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
        return jsonify(x=x, y=y, hsv=np.median(hsv, axis=0).astype(int).tolist(),
                       bgr=np.median(patch.reshape(-1, 3), axis=0).astype(int).tolist())

    @app.route("/api/snapshot", methods=["POST"])
    def snapshot():
        hub.action("snapshot")
        return jsonify(ok=True)

    @app.route("/api/arm", methods=["POST"])
    def arm():
        armed = bool((request.get_json(force=True) or {}).get("armed"))
        hub.action("arm", armed=armed)
        return jsonify(ok=True, armed=armed)

    return app


def _validate(d):
    out = {}
    for k, v in d.items():
        if k in ("hsv_low", "hsv_high"):
            v = [int(x) for x in v]
            if len(v) != 3:
                raise ValueError(f"{k} needs 3 values")
            out[k] = [min(179, max(0, v[0])), min(255, max(0, v[1])), min(255, max(0, v[2]))]
        elif k in ("roi_top", "roi_bottom"):
            out[k] = round(min(1.0, max(0.0, float(v))), 3)
        elif k in ("glare_v_min", "glare_s_max"):
            out[k] = min(255, max(0, int(v)))
        elif k in ("blur", "open_kernel", "close_kernel"):
            out[k] = min(31, max(0, int(v)))
        elif k == "mode":
            if v not in ("center", "lane"):
                raise ValueError("mode must be center or lane")
            out[k] = v
        else:
            raise ValueError(f"unknown parameter {k}")
    if out.get("roi_bottom", 1) <= out.get("roi_top", 0):
        raise ValueError("roi_bottom must be greater than roi_top")
    return out


class WebServer:
    def __init__(self, app, host="0.0.0.0", port=8000):
        self.srv = make_server(host, port, app, threaded=True)
        self.thread = threading.Thread(target=self.srv.serve_forever, name="web", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.srv.shutdown()


_STYLE = """
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{background:#111;color:#ddd;font-family:system-ui,sans-serif;margin:0;padding:12px}
 a{color:#6cf} h2{margin:4px 0 10px;font-size:18px}
 .row{display:flex;flex-wrap:wrap;gap:10px}
 .row img{width:min(640px,100%);image-rendering:pixelated;background:#000;border:1px solid #333}
 button{background:#2a2a2a;color:#eee;border:1px solid #555;padding:8px 14px;border-radius:6px;
        font-size:15px;cursor:pointer} button:hover{background:#3a3a3a}
 #go{background:#174} #stop{background:#822}
 pre{background:#1b1b1b;padding:8px;border-radius:6px;font-size:13px;overflow:auto}
 label{display:grid;grid-template-columns:110px 1fr 46px;align-items:center;gap:8px;margin:3px 0}
 input[type=range]{width:100%} .panel{max-width:520px;flex:1 1 320px}
 .sw{display:inline-block;width:18px;height:18px;border:1px solid #888;vertical-align:middle}
</style>"""

INDEX_HTML = """<!doctype html><html><head><title>Robros Vision</title>""" + _STYLE + """</head>
<body><h2>Robros vision &middot; <a href="/calibrate">calibrate</a></h2>
<div class="row"><img data-src="/stream.mjpg" alt="view"><img data-src="/mask.mjpg" alt="mask"></div>
<p><button id="go" onclick="arm(true)">GO (arm)</button>
<button id="stop" onclick="arm(false)">STOP</button>
<button onclick="snap()">Save snapshot</button> <span id="msg"></span></p>
<pre id="st">...</pre>
<script>
// attach MJPEG streams after load, so the page finishes loading
window.addEventListener('load',()=>setTimeout(()=>document.querySelectorAll('img[data-src]')
  .forEach(i=>i.src=location.search.includes('still') ?
     i.dataset.src.replace('stream.mjpg','frame.jpg').replace('mask.mjpg','mask.jpg') : i.dataset.src),50));
function arm(a){fetch('/api/arm',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({armed:a})});}
function snap(){fetch('/api/snapshot',{method:'POST'}).then(()=>{msg.textContent='snapshot saved';
  setTimeout(()=>msg.textContent='',1500)});}
document.addEventListener('keydown',e=>{if(e.key=='s')snap(); if(e.key==' '){arm(false);e.preventDefault();}});
setInterval(()=>fetch('/api/status').then(r=>r.json()).then(s=>st.textContent=JSON.stringify(s,null,1)).catch(()=>{}),250);
</script></body></html>"""

CALIBRATE_HTML = """<!doctype html><html><head><title>Robros Calibrate</title>""" + _STYLE + """</head>
<body><h2>Calibrate &middot; <a href="/">live view</a></h2>
<div class="row">
 <div><img id="view" data-src="/stream.mjpg" alt="view" style="cursor:crosshair"><br>
  <small>Click the tape in the image to read its HSV value.</small>
  <div id="pick"></div><br><img data-src="/mask.mjpg" alt="mask"></div>
 <div class="panel" id="sliders"></div>
</div>
<script>
// attach MJPEG streams after load, so the page finishes loading
window.addEventListener('load',()=>setTimeout(()=>document.querySelectorAll('img[data-src]')
  .forEach(i=>i.src=location.search.includes('still') ?
     i.dataset.src.replace('stream.mjpg','frame.jpg').replace('mask.mjpg','mask.jpg') : i.dataset.src),50));
const S=[['H low','hsv_low',0,179],['S low','hsv_low',1,255],['V low','hsv_low',2,255],
 ['H high','hsv_high',0,179],['S high','hsv_high',1,255],['V high','hsv_high',2,255],
 ['ROI top','roi_top',-1,1,0.01],['ROI bottom','roi_bottom',-1,1,0.01],
 ['Glare V min','glare_v_min',-1,255],['Glare S max','glare_s_max',-1,255],
 ['Blur','blur',-1,15],['Open','open_kernel',-1,15],['Close','close_kernel',-1,25]];
let P={}, timer=null;
function render(){
 let h='';
 S.forEach(([lab,key,idx,max,step],i)=>{
  const v= idx>=0 ? P[key][idx] : P[key];
  h+=`<label>${lab}<input type=range id=s${i} min=0 max=${max} step=${step||1} value=${v}
      oninput="chg(${i},this.value)"><span id=v${i}>${v}</span></label>`;});
 h+=`<label>Mode<select id=mode onchange="send({mode:this.value})">
     <option value=center ${P.mode=='center'?'selected':''}>center line</option>
     <option value=lane ${P.mode=='lane'?'selected':''}>lane (2 lines)</option></select><span></span></label>
  <p><button onclick="preset('blue')">Blue preset</button> <button onclick="preset('green')">Green preset</button>
  <button onclick="save()">Save to config.yaml</button></p><pre id=out></pre>`;
 sliders.innerHTML=h;}
function chg(i,val){const [l,key,idx,max,step]=S[i]; val=step?parseFloat(val):parseInt(val);
 document.getElementById('v'+i).textContent=val;
 if(idx>=0){P[key]=P[key].slice(); P[key][idx]=val; queue({[key]:P[key]});} else {P[key]=val; queue({[key]:val});}}
let pend={}; function queue(d){Object.assign(pend,d); clearTimeout(timer); timer=setTimeout(()=>{send(pend);pend={};},60);}
function send(d){fetch('/api/params',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)})
 .then(r=>r.json()).then(j=>{if(j.error)out.textContent='error: '+j.error; else {out.textContent=''; P=j;}});}
function cancelQueued(){clearTimeout(timer); pend={};}
function preset(c){cancelQueued(); const p=c=='blue'?{hsv_low:[90,80,40],hsv_high:[130,255,255]}:{hsv_low:[35,80,40],hsv_high:[85,255,255]};
 Object.assign(P,p); render(); send(p);}
function save(){fetch('/api/save',{method:'POST'}).then(r=>r.json()).then(j=>out.textContent=
 j.ok?'saved to config.yaml:\\n'+JSON.stringify(j.saved):'save failed: '+j.error);}
view.onclick=e=>{const r=view.getBoundingClientRect();
 fetch(`/api/sample?x=${(e.clientX-r.left)/r.width}&y=${(e.clientY-r.top)/r.height}`).then(r=>r.json()).then(j=>{
  if(j.error)return; const [b,g,rr]=j.bgr;
  pick.innerHTML=`<span class=sw style="background:rgb(${rr},${g},${b})"></span> pixel (${j.x},${j.y}) HSV = <b>${j.hsv.join(', ')}</b>
   <button onclick="around(${j.hsv})">use &plusmn; range</button>`;});};
function around(h,s,v){cancelQueued(); const p={hsv_low:[Math.max(0,h-12),Math.max(0,s-70),Math.max(0,v-80)],
 hsv_high:[Math.min(179,h+12),255,255]}; Object.assign(P,p); render(); send(p);}
fetch('/api/params').then(r=>r.json()).then(j=>{P=j;render();});
</script></body></html>"""
