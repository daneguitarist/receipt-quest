"""End-to-end test of the in-camera effect on the real (patched) firmware bytes.

Enters at printer_print (0x0205eefc) exactly as the camera's print code calls
it, runs hook -> trampoline -> loader stub -> loaded effect, and stops when
printer_print continues at +4. Checks registers, stack, heap, the replaced
instruction, and compares the printed dots with the PC build of the same C.

  python3 test_fx_emu.py BUILD_DIR PHOTO...
"""
import ctypes
import os
import random
import struct
import sys
import time

import numpy as np

import emu as E
import host_run as H

BIAS = 0x01ffda00
APP_LEN = 0x53a * 512
HOOK, CONT = 0x0205eefc, 0x0205ef00
BUF = 0x02300000
SITES = (0x0200bb20, 0x0200bccc, 0x0200d5b4)          # stock calls, now l.jal rq_wrap_*
PRINTER_JPEG, PRINTER_JPEG_MEM = 0x0205f6d0, 0x0205f884


def load(build):
    img = open(os.path.join(build, 'fx_app_image.bin'), 'rb').read()
    import json
    info = json.load(open(os.path.join(build, 'fx_build.json')))
    return img, info


def stub_seed(grey, prints):
    seed = (prints * 0x9e3779b9) & 0xffffffff
    flat = grey.reshape(-1)
    for i in range(0, flat.size, 97):
        seed = ((seed ^ int(flat[i])) * 0x01000193) & 0xffffffff
    return seed


class Camera:
    """one power-on session: the app RAM (incl. the cave counters) persists across prints"""

    def __init__(self, image, info, rng_seed=1):
        self.image = image
        self.info = info
        self.app = bytearray(image[0x2600:0x2600 + APP_LEN])
        self.rng = random.Random(rng_seed)
        self.first = True

    def print_(self, grey, w=None, h=None, level=2, mode=1, density=2, flash=None, malloc_fail=False,
               layout=None, site_no=0, ram_hook_expected=True):
        buf = bytes(layout if layout is not None else grey.reshape(-1))
        h = h if h is not None else grey.shape[0]
        w = w if w is not None else grey.shape[1]
        m = E.Emu(bytes(self.app), flash if flash is not None else self.image, BUF, buf, seed=self.rng.random())
        if malloc_fail:
            m.hooks[0x0204195c] = lambda: (m.calls.append(('malloc-fail',)), m._ret(0))
        r = m.r
        problems = []
        # 1. the stock caller: l.jal at the call site (patched to rq_wrap_*) with printer_jpeg's arguments
        site = SITES[site_no]
        target = PRINTER_JPEG_MEM if site == 0x0200bccc else PRINTER_JPEG
        jargs = {3: 0x02345678, 4: level, 5: mode, 6: density}
        for k, v in jargs.items():
            r[k] = v
        sent = {k: self.rng.getrandbits(32) for k in (2, 10, 14, 16, 18, 20, 22, 24, 26, 28, 30)}
        for k, v in sent.items():
            r[k] = v
        sp = r[1] = 0x027f0000
        seen = {}

        def stock_printer_jpeg():
            # the stock function: check what the wrapper handed over, then (after decoding) it calls
            # printer_print - continue there with the decoded picture
            seen['args'] = {k: r[k] for k in jargs}
            seen['ret'] = r[9]
            seen['sp'] = r[1]
            seen['ram_hook'] = m.read_bytes(HOOK, 4)
            seen['iinv_after_write'] = bool(m.ram_writes) and any(c[0] == 'iinv' for c in m.calls) and \
                ('dflush', HOOK & ~15, 16) in m.calls
            for k, v in sent.items():
                if r[k] != v:
                    problems.append(f'wrapper changed callee-saved r{k}')
            r[1] = (r[1] - 64) & ~3        # printer_jpeg's own frame
            for k, v in pargs.items():
                r[k] = v
            m.pc = HOOK
        pargs = {3: BUF, 4: w, 5: h, 6: level, 7: mode, 8: density, 9: 0x0205f818}
        m.hooks[target] = stock_printer_jpeg
        args = pargs
        t = time.time()
        m.run(site, CONT)
        dt = time.time() - t
        if not seen:
            problems.append('printer_jpeg never reached')
        else:
            if seen['args'] != jargs:
                problems.append(f'printer_jpeg got {seen["args"]}')
            if seen['ret'] != site + 4:
                problems.append(f'printer_jpeg would return to {seen["ret"]:#x}, not the caller')
            if seen['sp'] != sp:
                problems.append('wrapper left the stack moved')
            hook_word = int(self.info['ram_hook_word'], 16)
            if not ram_hook_expected:
                if seen['ram_hook'] != self.app[HOOK - 0x02000000:HOOK - 0x02000000 + 4]:
                    problems.append('RAM hook written although printer_print was not stock')
            elif seen['ram_hook'] != struct.pack('<I', hook_word):
                problems.append('RAM hook not in place when printer_jpeg runs')
            elif not seen['iinv_after_write'] and self.first:
                problems.append('no D-cache flush / I-cache clear after the RAM hook')
        self.first = False
        sp = (0x027f0000 - 64) & ~3          # printer_print's sp, inside printer_jpeg's frame
        for k, v in args.items():
            if r[k] != v:
                problems.append(f'r{k} not restored')
        for k, v in sent.items():
            if r[k] != v:
                problems.append(f'callee-saved r{k} changed')
        if r[1] != sp:
            problems.append('stack pointer changed')
        if m.read_bytes(sp - 4, 4) != struct.pack('<I', 0x0205f818):
            problems.append("printer_print's own first store (r9 at -4(r1)) missing")
        if m.heap.blocks:
            problems.append(f'heap blocks left: {m.heap.blocks}')
        # keep the session state (the cave words, the RAM hook) for the next print
        lo, n = 0x02015a00 - 0x02000000, 0x0201657c - 0x02015a00
        self.app[lo:lo + n] = m.read_bytes(0x02015a00, n)
        self.app[HOOK - 0x02000000:HOOK - 0x02000000 + 4] = m.read_bytes(HOOK, 4)
        out = np.frombuffer(m.read_bytes(BUF, len(buf)), np.uint8)
        prints = struct.unpack('<I', m.read_bytes(int(self.info['rq_prints'], 16), 4))[0]
        last = struct.unpack('<I', m.read_bytes(int(self.info['rq_last'], 16), 4))[0]
        return out, dict(steps=m.steps, seconds=round(dt, 1), stack=sp - m.min_sp, heap_peak=m.heap.peak,
                         calls=[c[0] for c in m.calls], prints=prints, last=hex(last), problems=problems)


def main(build, photos):
    image, info = load(build)
    cam = Camera(image, info)
    fails = 0
    for n, path in enumerate(photos, 1):
        grey = H.camera_input(path)
        out, rep = cam.print_(grey, site_no=(n - 1) % 3)
        seed = stub_seed(grey, rep['prints'])
        ref, ref_rep = H.run(grey, seed, count=rep['prints'] - 1)
        same = np.array_equal(out.reshape(grey.shape), ref)
        print(f'print {n} {os.path.basename(path)} via call site {SITES[(n - 1) % 3]:#x}: {rep["steps"]:,} instructions ({rep["seconds"]} s emu), '
              f'stack {rep["stack"]} B, heap peak {rep["heap_peak"]} B, report {rep["last"]} '
              f'(PC build {ref_rep:#x}), dots == PC build: {same}')
        print('   calls:', ' '.join(c for c in rep['calls'] if c != 'malloc-fail')[:200])
        if rep['problems'] or not same or int(rep['last'], 16) != ref_rep:
            fails += 1
            print('   PROBLEMS:', rep['problems'])
        np.save(os.path.join(build, f'emu_print_{n}.npy'), out.reshape(grey.shape))
    print('FAILURES:', fails)
    return fails


if __name__ == '__main__':
    sys.exit(1 if main(sys.argv[1], sys.argv[2:]) else 0)
