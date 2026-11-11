#ifndef RQ_FX_H
#define RQ_FX_H
typedef unsigned char u8;
typedef signed char s8;
typedef unsigned short u16;
typedef unsigned int u32;

#define FX_CTX_MAGIC 0x52514658u     /* 'RQFX' */

/* handed over by the stub on every print */
typedef struct fx_ctx {
    u32 magic;
    void *(*malloc)(u32 size, u32 align);     /* the camera's own heap */
    void (*free)(void *p);
    u32 seed;                                 /* per print */
    u32 count;                                /* prints since power on */
    u32 force_style;                          /* tests: 0 random, 1 agi, 2 agi-grey */
    u32 force_chrome;                         /* tests: 0 random, 1 off, 2 on */
} fx_ctx;

u32 fx_main(fx_ctx *c, u8 *buf, int w, int h, int level, int mode);
#endif
