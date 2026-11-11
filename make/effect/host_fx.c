/* PC build of rq_fx.c: same code, libc heap. */
#include <stdlib.h>
#include "rq_fx.h"
static void *h_malloc(u32 n, u32 a) { (void)a; return malloc(n); }
static void h_free(void *p) { free(p); }
u32 host_run(u8 *buf, int w, int h, u32 seed, u32 count, u32 fs, u32 fc)
{
    fx_ctx c = {FX_CTX_MAGIC, h_malloc, h_free, seed, count, fs, fc};
    return fx_main(&c, buf, w, h, 0, 1);
}
