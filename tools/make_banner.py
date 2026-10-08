"""Render shopbot/assets/banner.png (1280x720, shown in chat) and shopbot/assets/description_pic.png (640x360, for BotFather).

Edit SHOP / TAGLINE / CHIPS and run:  python tools/make_banner.py   (needs playwright + chromium)
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

SHOP = "Demo Shop"
TAGLINE = "Fresh coffee, tea & brewing gear"
CHIPS = ["Coffee", "Tea", "Accessories"]

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0}
body{width:1280px;height:720px;overflow:hidden;font-family:'Inter','DejaVu Sans',sans-serif;
 background:radial-gradient(1100px 700px at 82% 40%,#5a3320 0%,#2b1a12 58%,#1d110b 100%);color:#fbf1e3;position:relative}
.beans{position:absolute;inset:0;opacity:.07;background-image:radial-gradient(ellipse 14px 22px at 20px 20px,#fff 0 60%,transparent 62%),
 radial-gradient(ellipse 14px 22px at 70px 62px,#fff 0 60%,transparent 62%);background-size:100px 84px}
.left{position:absolute;left:96px;top:0;bottom:0;width:640px;display:flex;flex-direction:column;justify-content:center}
.tag{font-size:22px;letter-spacing:.28em;text-transform:uppercase;color:#e9a15b;font-weight:600}
h1{font-size:112px;line-height:1.02;font-weight:800;letter-spacing:-.03em;margin-top:22px}
p{font-size:34px;line-height:1.35;color:#e9d8c3;margin-top:26px;font-weight:400}
.chips{display:flex;gap:16px;margin-top:44px}
.chip{padding:12px 26px;border-radius:999px;background:rgba(251,241,227,.1);border:1.5px solid rgba(233,161,91,.55);
 font-size:24px;font-weight:600;color:#fbf1e3}
.cta{margin-top:38px;font-size:26px;color:#e9a15b;font-weight:700}
svg{position:absolute;right:70px;top:90px;width:520px;height:560px}
</style></head><body><div class="beans"></div>
<div class="left"><div class="tag">Welcome to</div><h1>__SHOP__</h1><p>__TAGLINE__</p>
<div class="chips">__CHIPS__</div><div class="cta">Tap START below to open the shop</div></div>
<svg viewBox="0 0 520 560" fill="none">
 <ellipse cx="260" cy="500" rx="210" ry="38" fill="#000" opacity=".28"/>
 <ellipse cx="260" cy="470" rx="205" ry="42" fill="#f3e4cf"/><ellipse cx="260" cy="462" rx="150" ry="26" fill="#e2cfb4"/>
 <path d="M120 250h280c0 0 10 120-36 190-20 30-60 44-104 44s-84-14-104-44c-46-70-36-190-36-190z" fill="#fbf1e3"/>
 <path d="M400 290c70-6 92 34 70 78-14 28-48 44-84 48" stroke="#fbf1e3" stroke-width="26" stroke-linecap="round"/>
 <ellipse cx="260" cy="250" rx="140" ry="30" fill="#6b3a1e"/><ellipse cx="260" cy="246" rx="122" ry="22" fill="#8a4b24"/>
 <path d="M205 238c18-14 36-14 54 0s36 14 54 0" stroke="#e9a15b" stroke-width="7" stroke-linecap="round" opacity=".9"/>
 <g stroke="#e9a15b" stroke-width="12" stroke-linecap="round" opacity=".85">
  <path d="M200 180c-30-30 30-52 0-84"/><path d="M262 170c-30-34 30-62 0-100"/><path d="M324 180c-30-30 30-52 0-84"/></g>
 <path d="M150 330c0 60 10 100 30 128" stroke="#e8d6bd" stroke-width="10" stroke-linecap="round" opacity=".7"/>
</svg></body></html>"""


def main():
    out = pathlib.Path(__file__).resolve().parent.parent / "shopbot" / "assets"
    out.mkdir(exist_ok=True)
    chips = "".join(f'<div class="chip">{c}</div>' for c in CHIPS)
    html = HTML.replace("__SHOP__", SHOP).replace("__TAGLINE__", TAGLINE).replace("__CHIPS__", chips)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=sys.argv[1] if len(sys.argv) > 1 else None)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(html.replace('<div class="cta">Tap START below to open the shop</div>', ""))
        page.screenshot(path=str(out / "banner.png"))
        small = browser.new_page(viewport={"width": 640, "height": 360}, device_scale_factor=1)
        small.set_content(html.replace("width:1280px;height:720px", "width:1280px;height:720px;zoom:.5"))
        small.screenshot(path=str(out / "description_pic.png"))
        browser.close()


if __name__ == "__main__":
    main()
