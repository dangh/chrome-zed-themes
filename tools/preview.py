#!/usr/bin/env python3
"""Install a theme into a throwaway Chrome profile over the DevTools pipe,
open tabs, screenshot the window, quit.

usage: preview.py <theme-dir> <out.png> [url ...]
env: CAP_H=<px> capture height (default 260), UNFOCUSED=1 focus Finder instead
"""
import ctypes
import ctypes.util
import json
import os
import subprocess
import sys
import tempfile
import time

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROF = os.path.join(tempfile.gettempdir(), "chrome-zed-preview-profile")
X, Y = 40, 80
# Store screenshots must be exactly 1280x800, so the window can be asked for that
# aspect and the retina capture downscaled with no cropping or distortion.
W = int(os.environ.get("WIN_W", 1100))
H = int(os.environ.get("WIN_H", 700))
CAP_H = int(os.environ.get("CAP_H", 260))
UNFOCUSED = bool(os.environ.get("UNFOCUSED"))

theme, out = os.path.abspath(sys.argv[1]), sys.argv[2]
# A previous run left running would sit at the same screen position and get
# captured instead of this one, silently reporting the wrong theme's colors.
subprocess.run(["pkill", "-f", os.path.basename(PROF)], capture_output=True)
time.sleep(1.5)
subprocess.run(["rm", "-rf", PROF])
if os.environ.get("VERTICAL"):
    os.makedirs(os.path.join(PROF, "Default"))
    with open(os.path.join(PROF, "Default", "Preferences"), "w") as f:
        json.dump({"vertical_tabs": {"enabled": True}}, f)

to_r, to_chrome_w = os.pipe()
from_chrome_r, from_w = os.pipe()


def place(src, dst):
    """Move src to fd dst, inheritable. dst==src just marks it inheritable."""
    if src != dst:
        os.dup2(src, dst)
        os.close(src)
    else:
        os.set_inheritable(dst, True)
    return dst


# Park our own ends high, since os.pipe() hands out 3 and 4 first.
to_chrome_w = place(to_chrome_w, 20)
from_chrome_r = place(from_chrome_r, 21)
# Chrome reads CDP on fd 3 and writes on fd 4. dup2 inside preexec_fn is closed
# before exec, so place them in the parent and pass the numbers through.
place(to_r, 3)
place(from_w, 4)

proc = subprocess.Popen(
    [CHROME, f"--user-data-dir={PROF}", "--remote-debugging-pipe",
     "--enable-unsafe-extension-debugging", "--silent-debugger-extension-api",
     "--no-first-run", "--no-default-browser-check", "--disable-sync"]
    + (["--enable-features=VerticalTabs,VerticalTabStrip"] if os.environ.get("VERTICAL") else [])
    + [
     f"--window-size={W},{H}", f"--window-position={X},{Y}",
     os.environ.get("START_URL", "about:blank")],
    pass_fds=(3, 4), close_fds=True)
os.close(3)
os.close(4)

def window_id(pid):
    """CGWindowID of the largest on-screen window owned by `pid`."""
    cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
    cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    cf.CFDictionaryGetValue.restype = ctypes.c_void_p
    cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cf.CFNumberGetValue.restype = ctypes.c_bool
    cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

    def key(text):
        return cf.CFStringCreateWithCString(None, text.encode(), 0x08000100)

    def number(d, k, kind, ctype):
        v = cf.CFDictionaryGetValue(d, k)
        if not v:
            return None
        out = ctype(0)
        cf.CFNumberGetValue(v, kind, ctypes.byref(out))
        return out.value

    k_pid, k_num, k_bounds = key("kCGWindowOwnerPID"), key("kCGWindowNumber"), key("kCGWindowBounds")
    k_w, k_h = key("Width"), key("Height")
    # on-screen windows, excluding desktop elements
    windows = cg.CGWindowListCopyWindowInfo((1 << 0) | (1 << 4), 0)
    best_area, best = 0, None
    for i in range(cf.CFArrayGetCount(windows)):
        d = cf.CFArrayGetValueAtIndex(windows, i)
        if number(d, k_pid, 4, ctypes.c_int64) != pid:
            continue
        bounds = cf.CFDictionaryGetValue(d, k_bounds)
        area = (number(bounds, k_w, 6, ctypes.c_double) or 0) * \
               (number(bounds, k_h, 6, ctypes.c_double) or 0)
        if area > best_area:
            best_area, best = area, number(d, k_num, 4, ctypes.c_int64)
    if best is None:
        raise SystemExit(f"found no on-screen window for pid {pid}")
    return best


buf = b""
seq = 0


def send(method, session=None, **params):
    global seq, buf
    seq += 1
    msg = {"id": seq, "method": method, "params": params}
    if session:
        msg["sessionId"] = session
    os.write(to_chrome_w, json.dumps(msg).encode() + b"\0")
    while True:
        while b"\0" in buf:
            raw, buf = buf.split(b"\0", 1)
            msg = json.loads(raw)
            if msg.get("id") == seq:
                if "error" in msg:
                    raise SystemExit(f"{method} failed: {msg['error']}")
                return msg.get("result", {})
        chunk = os.read(from_chrome_r, 65536)
        if not chunk:
            raise SystemExit("chrome closed the pipe")
        buf += chunk


time.sleep(2)
print("loadUnpacked ->", send("Extensions.loadUnpacked", path=theme))
target = None
for url in (sys.argv[3:] or ["chrome://settings", "https://example.com"]):
    target = send("Target.createTarget", url=url)["targetId"]
    time.sleep(1.5)
time.sleep(2)

# Never AppleScript-activate Chrome: "tell application \"Google Chrome\"" addresses
# the app, so with the user's own Chrome running it raises and photographs their
# session. Page.bringToFront is executed by *this* Chrome process, so it activates
# this instance only.
send("Target.activateTarget", targetId=target)
session = send("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
if not UNFOCUSED:
    send("Page.bringToFront", session=session)
    time.sleep(1.0)
else:
    # Focus another app so the frame renders inactive. Finder is a different app,
    # so this cannot pull the user's Chrome forward.
    subprocess.run(["osascript", "-e", 'tell application "Finder" to activate'],
                   capture_output=True)
    time.sleep(1.5)

# Capture the window by id rather than by screen rect. A rect grabs whatever is
# on screen, so anything overlapping -- another app, Mission Control -- silently
# lands in the shot instead of the window.
wid = window_id(proc.pid)
subprocess.run(["screencapture", "-x", "-o", f"-l{wid}", out], check=True)
send("Browser.close")
proc.wait(timeout=15)
print("wrote", out)
