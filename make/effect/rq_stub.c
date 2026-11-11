/* Receipt Quest loader stub - lives in the camera's unreachable "Game menu"
 * window code (RAM 0x02015a00 .. 0x0201657c, flash sector 0x18000 only). The
 * stock calls to printer_jpeg / printer_jpeg_mem go through rq_wrap_* first,
 * which put a RAM-only hook at the start of printer_print (flash untouched there:
 * that sector also holds code the camera runs at power-on). On every print it looks for the
 * effect in the erased flash tail; if a valid one is there it is loaded into a
 * fresh heap block, relocated, run on the print picture and freed again.
 * Anything wrong (no payload, bad header, bad checksum, no memory) -> it does
 * nothing and the camera prints exactly as stock. */
#include "fw.h"
#include "rq_stub.h"

u32 rq_prints;                  /* prints since power on (lives in the cave, RAM) */
u32 rq_last;                    /* last result word, for debugging */

extern void rq_tramp(void);

/* RAM hook: printer_print's first instruction (l.sw -4(r1),r9) -> l.j rq_tramp.
 * Only if the stock instruction is there; then out of the D-cache, I-cache cleared. */
void rq_ensure_hook(void)
{
    volatile u32 *site = (volatile u32 *)PRINTER_PRINT;
    u32 want = ((u32)rq_tramp - PRINTER_PRINT) >> 2 & 0x03ffffffu;     /* l.j (opcode 0) */
    if (*site == want)
        return;
    if (*site != 0xd7e14ffcu)
        return;
    *site = want;
    FW_DCACHE_FLUSH((void *)(PRINTER_PRINT & ~15u), 16);
    FW_ICACHE_INV();
}

static void patch16(u32 *insn, u32 v)
{
    *insn = (*insn & 0xffff0000u) | (v & 0xffffu);
}

void rq_stub_main(u8 *buf, int w, int h, int level, int mode)
{
    u32 raw[(sizeof(fx_header) + 32) / 4];
    fx_header *hd = (fx_header *)(((u32)raw + 15) & ~15u);   /* own cache lines: the DMA read invalidates them */
    rq_last = 1;
    FW_FLASH_READ(PAYLOAD_FLASH, hd, sizeof(fx_header));
    if (hd->magic != FX_CTX_MAGIC || hd->version != FX_VERSION)
        return;
    if (fx_sum(&hd->magic, 7, 0x5a17u) != hd->hdr_sum)
        return;
    u32 isz = hd->image_size, nrel = hd->reloc_count, bss = hd->bss_size;
    if (!isz || isz > FX_MAX_IMAGE || (isz & 15) || nrel > FX_MAX_RELOCS || bss > FX_MAX_BSS ||
        hd->entry >= isz || (hd->entry & 3))
        return;
    u32 rsz = nrel * 8;
    u32 load = (isz + rsz + 15) & ~15u;
    u32 need = isz + bss > load ? ((isz + bss + 15) & ~15u) : load;
    rq_last = 2;
    u8 *p = FW_MALLOC(need + 32, 32);
    if (!p)
        return;
    FW_FLASH_READ(PAYLOAD_FLASH + sizeof(fx_header), p, load);
    rq_last = 3;
    if (fx_sum((const u32 *)p, (isz + rsz) / 4, 0xc0ffeeu) != hd->sum) {
        FW_FREE(p);
        return;
    }
    /* relocate: link address 0 -> p */
    const u32 *rel = (const u32 *)(p + isz);
    u32 base = (u32)p;
    for (u32 i = 0; i < nrel; i++) {
        u32 type = rel[2 * i] >> 28, off = rel[2 * i] & 0x0fffffffu, v = rel[2 * i + 1] + base;
        if (off + 4 > isz || (off & 3)) {
            FW_FREE(p);
            return;
        }
        u32 *q = (u32 *)(p + off);
        if (type == RT_WORD)
            *q = v;
        else if (type == RT_HI)
            patch16(q, v >> 16);
        else if (type == RT_AHI)
            patch16(q, (v + 0x8000u) >> 16);
        else if (type == RT_LO)
            patch16(q, v);
        else if (type == RT_SLO)
            *q = (*q & ~0x03e007ffu) | ((v & 0xf800u) << 10) | (v & 0x7ffu);
        else {
            FW_FREE(p);
            return;
        }
    }
    for (u32 i = 0; i < bss; i++)        /* the relocation table is no longer needed */
        p[isz + i] = 0;
    FW_DCACHE_FLUSH(p, need);            /* patched code out of the D-cache into RAM */
    FW_ICACHE_INV();
    rq_prints++;
    /* seed: what is in the picture, and how many prints so far */
    u32 seed = rq_prints * 0x9e3779b9u;
    if (w > 0 && h > 0) {
        u32 n = (u32)w * (u32)h;
        for (u32 i = 0; i < n; i += 97)
            seed = (seed ^ buf[i]) * 0x01000193u;
    }
    fx_ctx c = {FX_CTX_MAGIC, FW_MALLOC, FW_FREE, seed, rq_prints - 1, 0, 0};
    rq_last = 4;
    u32 (*fx)(fx_ctx *, u8 *, int, int, int, int) = (u32 (*)(fx_ctx *, u8 *, int, int, int, int))(p + hd->entry);
    rq_last = fx(&c, buf, w, h, level, mode);
    FW_FREE(p);
}
