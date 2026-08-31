# SD library for the STC plain-C core

This clean-room MIT implementation supports SD version 1, SD version 2 and
SDHC cards in SPI mode. It requests 100 kHz for card initialization and then a
400 kHz target from the software SPI layer. It provides bounded `CMD17`/`CMD24`
single-sector I/O. Every card-response, data-token and busy wait has both a byte-attempt
limit and a `millis()` deadline; chip select is released on every exit path.

`SD.begin(cs)` also mounts a 512-byte-sector FAT16 or FAT32 volume. Sector zero
may be either a FAT boot sector (a superfloppy) or an MBR whose first partition
contains FAT. The file layer is intentionally small and deterministic:

If card initialization succeeds but FAT mounting fails, `begin` returns zero,
`fatType` remains `SD_FAT_NONE`, and bounded raw block I/O remains available for
diagnostics until `end` is called.

- one 512-byte cache plus state in XDATA, with a compile-time minimum of 1 KiB
  XDATA;
- one card and one open file at a time;
- root-directory, ASCII short 8.3 names only;
- read-only file access through `exists`, `open`, `peek`, `read`, `readBytes`,
  `available`, `seek`, `position`, `size`, and `close`;
- no long-file names, subdirectories, FAT12, exFAT, formatting, allocation,
  C++ `File`, or `Stream` compatibility.

Root-directory scans have a hard 4096-sector ceiling in addition to the FAT
cluster-count bound, so a corrupt cyclic directory chain cannot cause an
effectively unbounded lookup. File reads are bounded by the directory entry's
declared size and the volume cluster count, but this small reader is not a FAT
repair tool or full `fsck`; do not treat data from a damaged volume as trusted.

The raw `readBlock` and `writeBlock` calls always transfer exactly 512 bytes.
`writeBlock` bypasses FAT consistency and can irreversibly corrupt the mounted
volume; use it only when the caller owns the on-card layout. Normal file access
never writes the card.

Cards and breakout boards must use 3.3 V signaling. Provide proper level
translation when the selected STC device is operated at 5 V.
