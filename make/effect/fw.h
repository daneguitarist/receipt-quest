/* The camera's firmware 20240822_V1.9: stock routines the stub uses (RAM addresses,
 * found by signature against the MK1 dump and checked by reading their code). */
#ifndef FW_H
#define FW_H
#include "rq_fx.h"
#define FW_FLASH_READ   ((void (*)(u32 flash, void *dst, u32 len))0x020404f0u)  /* SPI 03 read; >15 B by DMA (len rounded up to 16, D-cache invalidated first) */
#define FW_MALLOC       ((void *(*)(u32 size, u32 align))0x0204195cu)
#define FW_FREE         ((void (*)(void *p))0x0204179cu)
#define FW_DCACHE_FLUSH ((void (*)(void *addr, u32 len))0x0202da34u)            /* SPR 0x180c per line */
#define FW_ICACHE_INV   ((void (*)(void))0x0202d9f0u)                           /* SPR 0x2008 */
#define PRINTER_PRINT   0x0205eefcu                                              /* printer_print(buf,w,h,level,mode,density) */
#define PAYLOAD_FLASH   0x00380000u                                              /* erased tail of the flash */
#endif
