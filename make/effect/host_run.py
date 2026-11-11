"""Run the PC build of the in-camera effect on photos, the way the camera hands
them to printer_print: grey (JPEG Y), 384 dots wide, 224 lines (2304x1344 / 6)."""
import ctypes, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, 'libfx_host.so')
if not os.path.exists(LIB):          # PC build of the very same C
    import subprocess
    subprocess.run(['gcc', '-O2', '-fno-builtin', '-shared', '-fPIC', '-o', LIB, 'host_fx.c', 'rq_fx.c'], cwd=HERE, check=True)
lib = ctypes.CDLL(LIB)
lib.host_run.restype = ctypes.c_uint32
lib.host_run.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32,
                         ctypes.c_uint32, ctypes.c_uint32]


def camera_input(path, w=384, h=224):
    im = Image.open(path).convert('RGB')
    W, H = im.size                       # crop to the camera's 2304x1344 shape (12:7)
    t = w / h
    if W / H > t:
        nw = int(H * t); im = im.crop(((W - nw) // 2, 0, (W - nw) // 2 + nw, H))
    else:
        nh = int(W / t); im = im.crop((0, (H - nh) // 2, W, (H - nh) // 2 + nh))
    im = im.resize((w, h), Image.BOX)
    a = np.asarray(im).astype(np.float32)
    y = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    return np.clip(np.round(y), 0, 255).astype(np.uint8)


def run(grey, seed, count=0, style=0, chrome=0, rotated=False):
    g = np.ascontiguousarray(grey.T[::-1].copy() if rotated else grey.copy())
    if rotated:          # build the camera's column layout: dot k of line L = buf[(383-k)*w + L]
        H, W = grey.shape                # print lines, 384
        buf = np.zeros((384, H), np.uint8)
        for k in range(384):
            buf[383 - k] = grey[:, k]
        g = np.ascontiguousarray(buf)
        rep = lib.host_run(g.ctypes.data, H, 384, seed, count, style, chrome)
        out = np.zeros_like(grey)
        for k in range(384):
            out[:, k] = g[383 - k]
        return out, rep
    rep = lib.host_run(g.ctypes.data, g.shape[1], g.shape[0], seed, count, style, chrome)
    return g, rep


def paper(dots, scale=2):
    """rough thermal-paper look: the measured tone response (0-60 same soft black, 165+ white)"""
    d = dots.astype(np.float32)
    dark = np.interp(d, [0, 60, 75, 90, 105, 120, 135, 150, 165, 255],
                     [0.50, 0.50, 0.39, 0.33, 0.25, 0.15, 0.10, 0.05, 0.0, 0.0])
    paper_rgb = np.array([238, 236, 228], np.float32)
    ink_rgb = np.array([40, 40, 52], np.float32)
    rgb = paper_rgb + (ink_rgb - paper_rgb) * (dark[..., None] / 0.5) * 0.92
    im = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    return im.resize((im.width * scale, im.height * scale), Image.NEAREST)


if __name__ == '__main__':
    # python3 host_run.py photo.jpg [prints] -> photo_rq_N.png: what N prints of that photo would look like
    path = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    grey = camera_input(path)
    base = os.path.splitext(path)[0]
    for k in range(n):
        out, rep = run(grey, 0x9e3779b9 * (k + 1) & 0xffffffff, count=k)
        paper(out).save(f'{base}_rq_{k + 1}.png')
        print(f'{base}_rq_{k + 1}.png  report {rep:#x}')
