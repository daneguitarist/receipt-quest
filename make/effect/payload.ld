/* payload: linked at 0, relocated by the stub after loading */
ENTRY(fx_main)
SECTIONS
{
  . = 0;
  .text : { *(.text.fx_main) *(.text .text.*) }
  .rodata ALIGN(4) : { *(.rodata .rodata.* .srodata .srodata.*) }
  .data ALIGN(4) : { *(.data .data.* .sdata .sdata.*) }
  __image_end = ALIGN(16);
  .bss (NOLOAD) : { __bss_start = .; *(.bss .bss.* .sbss .sbss.* COMMON) __bss_end = .; }
  /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
