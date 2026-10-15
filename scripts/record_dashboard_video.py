"""Record a ~30 s walkthrough of the dashboard (demo mode) with headless Chrome -> /tmp/delta-video/*.webm

    DELTA_PY=<python with delta deps> python scripts/record_dashboard_video.py
Then encode with ffmpeg (see README, "Re-making the screenshots and video").
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shoot_dashboard as sd  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = Path("/tmp/delta-video")
CURSOR = """
(() => { const d = document.createElement('div');
  d.style.cssText='position:fixed;z-index:99999;width:18px;height:18px;border-radius:50%;pointer-events:none;border:2px solid #a8f0ff;background:rgba(85,217,244,.25);box-shadow:0 0 14px #55d9f4;transform:translate(-50%,-50%);left:-50px;top:-50px;transition:left .06s linear,top .06s linear';
  addEventListener('DOMContentLoaded',()=>document.body.append(d));
  addEventListener('mousemove',e=>{d.style.left=e.clientX+'px';d.style.top=e.clientY+'px'},true); })();
"""


def glide(pg, selector, steps=25):
    box = pg.locator(selector).first.bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="demo-"))
    srv, url = sd.start_server(tmp)
    try:
        sd.seed(url)
        time.sleep(float(os.environ.get("WARMUP", "64")))
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=sd.CHROME, args=["--no-sandbox"], headless=True)
            ctx = b.new_context(viewport={"width": 1440, "height": 900}, record_video_dir=str(OUT), record_video_size={"width": 1440, "height": 900})
            ctx.add_init_script(CURSOR)
            pg = ctx.new_page()
            pg.goto(url)
            pg.wait_for_selector("#g-name:not(:empty)")
            pg.mouse.move(700, 450)
            time.sleep(3.0)                                   # intro: panels fade in, core idles
            glide(pg, "#nav li:nth-child(2) button"); pg.mouse.down(); pg.mouse.up(); time.sleep(1.2)       # Tasks
            glide(pg, "#view-body .form-r input"); pg.mouse.down(); pg.mouse.up()
            pg.keyboard.type("Pay the electricity bill", delay=55); pg.keyboard.press("Enter"); time.sleep(1.4)
            glide(pg, "#nav li:nth-child(1) button"); pg.mouse.down(); pg.mouse.up(); time.sleep(0.8)
            glide(pg, "#inp"); pg.mouse.down(); pg.mouse.up()
            pg.keyboard.type("volume 55", delay=70); time.sleep(0.5); pg.keyboard.press("Enter"); time.sleep(3.2)  # thinking -> responding
            pg.keyboard.press("Escape"); time.sleep(0.4)
            pg.keyboard.press("Control+k"); time.sleep(0.6)
            pg.keyboard.type("shut", delay=90); time.sleep(0.7); pg.keyboard.press("Enter")            # asks first
            pg.wait_for_selector("#tray .card.pending"); time.sleep(2.2)
            glide(pg, "#tray .btn.no"); pg.mouse.down(); pg.mouse.up(); time.sleep(1.0)               # deny
            glide(pg, "#nav li:nth-child(5) button"); pg.mouse.down(); pg.mouse.up(); time.sleep(3.0)  # Activity (safe / asked badges)
            glide(pg, "#nav li:nth-child(8) button"); pg.mouse.down(); pg.mouse.up(); time.sleep(1.0)  # Controls
            sl = pg.locator("#view-body input[type=range]").first.bounding_box()
            pg.mouse.move(sl["x"] + sl["width"] * .55, sl["y"] + sl["height"] / 2, steps=15); pg.mouse.down()
            pg.mouse.move(sl["x"] + sl["width"] * .8, sl["y"] + sl["height"] / 2, steps=25); pg.mouse.up(); time.sleep(1.6)
            glide(pg, "#nav li:nth-child(1) button"); pg.mouse.down(); pg.mouse.up(); time.sleep(2.0)
            ctx.close()
            b.close()
    finally:
        srv.terminate()
        shutil.rmtree(tmp, ignore_errors=True)
    print(list(OUT.glob("*.webm")))


if __name__ == "__main__":
    main()
