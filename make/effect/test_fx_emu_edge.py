"""Edge cases on the real patched firmware bytes: no payload, corrupted payload, out of
memory, rotated picture, unknown picture size. Each must leave printing stock (or, for
the rotated one, match the PC build)."""
import os, sys, struct
import numpy as np
import test_fx_emu as T
import host_run as H

build = sys.argv[1]
image, info = T.load(build)
grey = H.camera_input('../test_in/coffee.png')
fails = 0


def show(name, ok, rep):
    global fails
    fails += 0 if ok and not rep['problems'] else 1
    print(f'{name}: {"ok" if ok and not rep["problems"] else "FAIL"}  steps {rep["steps"]:,} calls {" ".join(rep["calls"])} '
          f'last {rep["last"]} problems {rep["problems"]}')


# 1. flash tail erased (no effect) -> nothing happens
erased = bytearray(image)
erased[0x380000:0x384000] = b'\xff' * 0x4000
cam = T.Camera(image, info, 2)
out, rep = cam.print_(grey, flash=bytes(erased))
show('no payload in flash', np.array_equal(out.reshape(grey.shape), grey) and 'malloc' not in rep['calls'], rep)
# 2. one byte of the effect corrupted -> checksum stops it, memory freed
bad = bytearray(image)
bad[0x380000 + 64 + 0x400] ^= 0x10
out, rep = T.Camera(image, info, 3).print_(grey, flash=bytes(bad))
show('corrupted payload', np.array_equal(out.reshape(grey.shape), grey) and 'free' in rep['calls'], rep)
# 3. header corrupted
bad = bytearray(image)
bad[0x380000 + 8] ^= 0x01
out, rep = T.Camera(image, info, 4).print_(grey, flash=bytes(bad))
show('corrupted header', np.array_equal(out.reshape(grey.shape), grey) and 'malloc' not in rep['calls'], rep)
# 4. out of memory
out, rep = T.Camera(image, info, 5).print_(grey, malloc_fail=True)
show('malloc fails', np.array_equal(out.reshape(grey.shape), grey), rep)
# 5. picture size the effect does not handle (320 x 240) -> untouched by the effect
g2 = np.ascontiguousarray(np.resize(grey, (240, 320)))
out, rep = T.Camera(image, info, 6).print_(g2)
show('320x240 picture', np.array_equal(out.reshape(g2.shape), g2) and rep['last'] == '0xe1', rep)
# 6. rotated layout (h = 384): camera buffer = column layout, dot k of line L at buf[(383-k)*w + L]
lines = grey.shape[0]
layout = np.zeros((384, lines), np.uint8)
for k in range(384):
    layout[383 - k] = grey[:, k]
cam = T.Camera(image, info, 7)
out, rep = cam.print_(grey, w=lines, h=384, layout=layout.reshape(-1))
seed = T.stub_seed(layout, rep['prints'])
ref, ref_rep = H.run(grey, seed, count=rep['prints'] - 1, rotated=True)
got = np.zeros_like(grey)
o = out.reshape(384, lines)
for k in range(384):
    got[:, k] = o[383 - k]
show('rotated picture', np.array_equal(got, ref) and int(rep['last'], 16) == ref_rep, rep)
# 7. printer_print in RAM is not the stock instruction (some other firmware): no hook, stock printing
cam = T.Camera(image, info, 8)
cam.app[T.HOOK - 0x02000000:T.HOOK - 0x02000000 + 4] = struct.pack('<I', 0x15000000)   # l.nop stand-in
out, rep = cam.print_(grey, ram_hook_expected=False)
rep['problems'] = [p for p in rep['problems'] if 'first store' not in p]                # the stand-in has no store
show('printer_print not stock', np.array_equal(out.reshape(grey.shape), grey) and 'flash_read' not in rep['calls'], rep)
# 8. second print in the same session: hook already in RAM, no second patch
cam = T.Camera(image, info, 9)
cam.print_(grey)
out, rep = cam.print_(grey, site_no=1)
show('second print, hook already there', 'iinv' in rep['calls'] and rep['calls'].count('dflush') == 1 and rep['prints'] == 2, rep)
print('EDGE FAILURES:', fails)
sys.exit(1 if fails else 0)
