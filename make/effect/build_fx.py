"""Build the in-camera print effect for the AX3291A camera (firmware 20240822_V1.9).

Produces, from a stock firmware backup that matches the tested one:
  fx_payload.bin   header + effect image + relocation table, for flash 0x380000
                   (the erased tail; the camera never writes there)
  fx_app_image.bin the full 4 MiB image with the one-time program patch:
                   - the 3 stock calls to printer_jpeg / printer_jpeg_mem (photo
                     screen + gallery, flash sectors 0xe000 / 0xf000) -> rq_wrap_*
                   - rq_wrap_*, rq_tramp + loader stub in the unreachable Game-menu
                     window code (RAM 0x02015a00 .. 0x0201657c = flash sector 0x18000)
                   - printer_print itself is NOT changed in flash (its sector holds
                     code the camera runs at power-on); the hook there is RAM-only
                   plus the payload at 0x380000
                   None of the changed program sectors holds code that runs at
                   power-on (checked against the call graph).
  fx_build.json    sizes, sectors, sha256s

Checks: only instructions the stock firmware uses; stub fits the cave; every
payload relocation is understood; the payload relocated by the same rules the
stub uses == the linker's own output for that address; the hook site still
holds the expected stock instruction.

  python3 build_fx.py BACKUP.bin OUTDIR
"""
import hashlib
import json
import os
import struct
import subprocess
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'install'))
import rq_packs  # noqa: E402  (checks a backup against the tested firmware)

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection

HERE = os.path.dirname(os.path.abspath(__file__))
BIAS = 0x01ffda00
CAVE_LO, CAVE_HI = 0x02015a00, 0x0201657c
HOOK = 0x0205eefc
HOOK_STOCK = 0xd7e14ffc                  # l.sw -4(r1),r9 - stays in flash, patched in RAM only
PRINTER_JPEG, PRINTER_JPEG_MEM = 0x0205f6d0, 0x0205f884
CALLS = ((0x0200bb20, PRINTER_JPEG, 'rq_wrap_jpeg'), (0x0200bccc, PRINTER_JPEG_MEM, 'rq_wrap_mem'),
         (0x0200d5b4, PRINTER_JPEG, 'rq_wrap_jpeg'))
EXPECTED_SECTORS = [0xe000, 0xf000, 0x18000, 0x380000, 0x381000, 0x382000, 0x383000]
PAYLOAD_FLASH = 0x380000
CFLAGS = ['-O2', '-fno-delayed-branch', '-ffreestanding', '-fno-builtin', '-fno-tree-loop-distribute-patterns',
          '-fno-jump-tables', '-nostdlib', '-msfimm', '-mshftimm', '-Wall', '-Wextra', '-Werror',
          '-ffunction-sections', '-fdata-sections', '-fno-store-merging', '-fno-tree-vectorize']
# the compiler is big-endian, the camera little-endian: instruction words get byte-swapped, so constant
# data must be bytes only (checked below) and GCC must not merge byte stores into words (-fno-store-merging)
RODATA_OK = ('NEGLN_HI', 'NEGLN_LO', 'FONT', 'COMMANDS', 'MAX_SCORES', 'GREY_TONES', 'BAYER2', 'DIRS', 'SIZES')
ALLOWED = {
    'l.nop', 'l.add', 'l.addi', 'l.sub', 'l.and', 'l.andi', 'l.or', 'l.ori', 'l.xor', 'l.xori', 'l.mul',
    'l.div', 'l.divu', 'l.sll', 'l.srl', 'l.sra', 'l.slli', 'l.srli', 'l.srai', 'l.movhi',
    'l.lwz', 'l.lws', 'l.lbz', 'l.lbs', 'l.lhz', 'l.lhs', 'l.sw', 'l.sb', 'l.sh',
    'l.j', 'l.jal', 'l.jr', 'l.jalr', 'l.bf', 'l.bnf',
    'l.sfeq', 'l.sfne', 'l.sfgtu', 'l.sfgeu', 'l.sfltu', 'l.sfleu', 'l.sfgts', 'l.sfges', 'l.sflts', 'l.sfles',
    'l.sfeqi', 'l.sfnei', 'l.sfgtui', 'l.sfgeui', 'l.sfltui', 'l.sfleui', 'l.sfgtsi', 'l.sfgesi', 'l.sfltsi',
    'l.sflesi',
}
RT = {'R_OR1K_32': 1, 'R_OR1K_HI_16_IN_INSN': 2, 'R_OR1K_AHI16': 3, 'R_OR1K_LO_16_IN_INSN': 4, 'R_OR1K_SLO16': 5}


def run(cmd):
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'{" ".join(cmd)}\n{r.stdout}{r.stderr}')
    return r.stdout


def fx_sum(data, h):
    for (v,) in struct.iter_unpack('<I', data):
        h ^= v
        h = ((h << 7) | (h >> 25)) & 0xffffffff
        h = (h + 0x9e3779b9) & 0xffffffff
    return h


def check_opcodes(elf, what):
    out = run(['or1k-elf-objdump', '-d', elf])
    bad = set()
    for line in out.splitlines():
        parts = line.split('\t')
        if len(parts) >= 3 and parts[0].strip().endswith(':'):
            mn = parts[2].split()[0]
            if mn not in ALLOWED:
                bad.add(mn)
    if bad:
        raise SystemExit(f'{what}: instructions not used by the stock firmware: {sorted(bad)}')


def check_byte_data(obj, what):
    """every data section in the object must be byte data we know about (endian-neutral)"""
    with open(os.path.join(HERE, obj), 'rb') as f:
        e = ELFFile(f)
        for sec in e.iter_sections():
            n = sec.name
            if not n or sec['sh_type'] in ('SHT_NULL', 'SHT_SYMTAB', 'SHT_STRTAB', 'SHT_RELA', 'SHT_REL',
                                           'SHT_NOTE', 'SHT_GROUP') or n.startswith('.text') or \
                    n in ('.comment', '.note.GNU-stack') or n.startswith('.debug'):
                continue
            if sec['sh_size'] == 0:
                continue
            if n.startswith('.rodata') and '.str1.' in n:
                continue                                  # string literals: bytes
            if n.startswith('.rodata.') and n[len('.rodata.'):].split('.')[0] in RODATA_OK:
                continue
            if n in ('.bss',) or n.startswith('.bss.') or n.startswith('.sbss'):
                continue                                  # zero-filled
            raise SystemExit(f'{what}: section {n} ({sec["sh_size"]} bytes) may hold multi-byte data')


def swap_words(b):
    assert len(b) % 4 == 0
    return b''.join(b[i:i + 4][::-1] for i in range(0, len(b), 4))


def payload_image(elf_path):
    with open(elf_path, 'rb') as f:
        e = ELFFile(f)
        secs = [e.get_section_by_name(n) for n in ('.text', '.rodata', '.data')]
        end = max(s['sh_addr'] + s['sh_size'] for s in secs if s)
        img = bytearray(end)
        for s in secs:
            if s and s['sh_size']:
                img[s['sh_addr']:s['sh_addr'] + s['sh_size']] = s.data()
        img += b'\0' * ((-len(img)) % 16)
        bss = e.get_section_by_name('.bss')
        bss_size = bss['sh_size'] if bss else 0
        symtab = e.get_section_by_name('.symtab')
        syms = {s.name: s['st_value'] for s in symtab.iter_symbols()}
        relocs, kinds = [], {}
        for sec in e.iter_sections():
            if not isinstance(sec, RelocationSection):
                continue
            for rel in sec.iter_relocations():
                t = rel['r_info_type']
                # numbers from binutils include/elf/or1k.h
                name = {1: 'R_OR1K_32', 4: 'R_OR1K_LO_16_IN_INSN', 5: 'R_OR1K_HI_16_IN_INSN',
                        6: 'R_OR1K_INSN_REL_26', 35: 'R_OR1K_AHI16', 39: 'R_OR1K_SLO16'}.get(t, f'type{t}')
                sym = symtab.get_symbol(rel['r_info_sym'])
                target = (sym['st_value'] + rel['r_addend']) & 0xffffffff
                kinds[name] = kinds.get(name, 0) + 1
                if name == 'R_OR1K_INSN_REL_26':
                    if not 0 <= target < len(img):
                        raise SystemExit(f'payload calls outside itself: {target:#x}')
                    continue                      # PC-relative inside the payload: moves with it
                if name not in RT:
                    raise SystemExit(f'payload relocation {name} not handled by the stub')
                off = rel['r_offset']
                if not (0 <= off < len(img) and off % 4 == 0):
                    raise SystemExit(f'relocation at odd place {off:#x}')
                if not 0 <= target <= len(img) + bss_size:
                    raise SystemExit(f'relocation target outside the payload: {target:#x}')
                relocs.append((RT[name], off, target))
    return bytes(img), bss_size, syms, sorted(relocs, key=lambda r: r[1]), kinds


def apply_relocs(img, relocs, base, fmt='>I'):
    """The stub's rules, in Python (the emulator runs the real stub code). fmt: '>I' on the
    compiler's big-endian image (cross-check with the linker), '<I' on the camera's image."""
    m = bytearray(img)
    for t, off, target in relocs:
        v = (target + base) & 0xffffffff
        (w,) = struct.unpack_from(fmt, m, off)
        if t == 1:
            w = v
        elif t == 2:
            w = (w & 0xffff0000) | (v >> 16)
        elif t == 3:
            w = (w & 0xffff0000) | (((v + 0x8000) >> 16) & 0xffff)
        elif t == 4:
            w = (w & 0xffff0000) | (v & 0xffff)
        elif t == 5:
            w = (w & ~0x03e007ff & 0xffffffff) | ((v & 0xf800) << 10) | (v & 0x7ff)
        struct.pack_into(fmt, m, off, w)
    return bytes(m)


def build(backup, outdir):
    assert rq_packs.check_backup(backup)[0], 'the backup does not match the tested firmware'
    # ---- payload
    run(['or1k-elf-gcc'] + CFLAGS + ['-c', 'rq_fx.c', '-o', 'rq_fx.o'])
    run(['or1k-elf-ld', '--no-warn-rwx-segments', '-q', '-T', 'payload.ld', 'rq_fx.o', '-o', 'payload.elf'])
    check_opcodes('payload.elf', 'payload')
    img, bss, syms, relocs, kinds = payload_image(os.path.join(HERE, 'payload.elf'))
    entry = syms['fx_main']
    # cross-check the relocation rules against the linker itself at a test address
    test_base = 0x02412340
    run(['or1k-elf-ld', '--no-warn-rwx-segments', '-T', 'payload.ld', '--defsym=__x=0',
         '--section-start=.text=%#x' % test_base, 'rq_fx.o', '-o', 'payload_at.elf'])
    with open(os.path.join(HERE, 'payload_at.elf'), 'rb') as f:
        e = ELFFile(f)
        ref = bytearray(len(img))
        for n in ('.text', '.rodata', '.data'):
            s = e.get_section_by_name(n)
            if s and s['sh_size']:
                ref[s['sh_addr'] - test_base:s['sh_addr'] - test_base + s['sh_size']] = s.data()
    mine = apply_relocs(img, relocs, test_base)
    if mine != bytes(ref):
        bad = [hex(i) for i in range(0, len(img), 4) if mine[i:i + 4] != ref[i:i + 4]]
        raise SystemExit(f'relocated payload != linker output at {bad[:8]}')
    check_byte_data('rq_fx.o', 'payload')
    if any(t == 1 for t, off, target in relocs):
        raise SystemExit('payload has 32-bit pointer data (would need byte swapping)')
    with open(os.path.join(HERE, 'payload.elf'), 'rb') as f:
        text_end = ELFFile(f).get_section_by_name('.text')['sh_size']
    assert text_end % 4 == 0
    img = swap_words(img[:text_end]) + img[text_end:]       # big-endian code -> the camera's little-endian
    rel_bytes = b''.join(struct.pack('<II', t << 28 | off, target) for t, off, target in relocs)
    body = img + rel_bytes
    words = [0x52514658, 1, len(img), len(relocs), bss, entry, fx_sum(body, 0xc0ffee)]
    hdr = struct.pack('<7I', *words)
    hdr += struct.pack('<I', fx_sum(hdr, 0x5a17)) + b'\0' * 32
    payload = hdr + body
    payload += b'\xff' * ((-len(payload)) % 0x1000)
    # ---- stub
    run(['or1k-elf-gcc'] + CFLAGS + ['-c', 'rq_stub.c', '-o', 'rq_stub.o'])
    run(['or1k-elf-gcc', '-c', 'rq_tramp.S', '-o', 'rq_tramp.o'])
    run(['or1k-elf-ld', '--no-warn-rwx-segments', '-T', 'stub.ld', 'rq_tramp.o', 'rq_stub.o', '-o', 'stub.elf'])
    check_opcodes('stub.elf', 'stub')
    check_byte_data('rq_stub.o', 'stub')
    with open(os.path.join(HERE, 'stub.elf'), 'rb') as f:
        e = ELFFile(f)
        t = e.get_section_by_name('.text')
        assert t['sh_addr'] == CAVE_LO
        stub = swap_words(t.data())       # code + zero-initialised words, little-endian
        ssyms = {s.name: s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    if CAVE_LO + len(stub) > CAVE_HI:
        raise SystemExit(f'stub too big: {len(stub)} > {CAVE_HI - CAVE_LO}')
    tramp = ssyms['rq_tramp']
    # ---- patch the image
    out = bytearray(backup)
    assert struct.unpack_from('<I', out, HOOK - BIAS)[0] == HOOK_STOCK, 'printer_print not as expected'
    off = CAVE_LO - BIAS
    out[off:off + len(stub)] = stub
    hook = ((tramp - HOOK) >> 2) & 0x3ffffff                 # l.j (opcode 0): what rq_ensure_hook writes in RAM
    for site, target, wrapper in CALLS:
        stock = (1 << 26) | (((target - site) >> 2) & 0x3ffffff)
        have = struct.unpack_from('<I', out, site - BIAS)[0]
        if have != stock:
            raise SystemExit(f'call site {site:#x} holds {have:08x}, expected l.jal {target:#x}')
        struct.pack_into('<I', out, site - BIAS, (1 << 26) | (((ssyms[wrapper] - site) >> 2) & 0x3ffffff))
    assert out[PAYLOAD_FLASH:PAYLOAD_FLASH + len(payload)] == b'\xff' * len(payload), 'payload area not erased'
    out[PAYLOAD_FLASH:PAYLOAD_FLASH + len(payload)] = payload
    out = bytes(out)
    changed = [s for s in range(0, len(out), 0x1000) if out[s:s + 0x1000] != backup[s:s + 0x1000]]
    if changed != EXPECTED_SECTORS:
        raise SystemExit(f'changed sectors {[hex(c) for c in changed]} != planned {[hex(c) for c in EXPECTED_SECTORS]}')
    info = {
        'payload_image': len(img), 'payload_relocs': len(relocs), 'reloc_kinds': kinds, 'bss': bss,
        'entry': entry, 'payload_bytes': len(payload), 'stub_bytes': len(stub),
        'cave_free': CAVE_HI - CAVE_LO - len(stub), 'tramp': hex(tramp), 'ram_hook_word': f'{hook:08x}',
        'wrap_jpeg': hex(ssyms['rq_wrap_jpeg']), 'wrap_mem': hex(ssyms['rq_wrap_mem']),
        'changed_sectors': [hex(s) for s in changed],
        'payload_sha': hashlib.sha256(payload).hexdigest(), 'image_sha': hashlib.sha256(out).hexdigest(),
        'rq_prints': hex(ssyms['rq_prints']), 'rq_last': hex(ssyms['rq_last']),
    }
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'fx_payload.bin'), 'wb').write(payload)
    open(os.path.join(outdir, 'fx_app_image.bin'), 'wb').write(out)
    open(os.path.join(outdir, 'fx_build.json'), 'w').write(json.dumps(info, indent=1))
    return out, payload, info


if __name__ == '__main__':
    image, payload, info = build(open(sys.argv[1], 'rb').read(), sys.argv[2])
    print(json.dumps(info, indent=1))
