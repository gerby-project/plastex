# Stub for the microtype package.
#
# microtype only performs print-oriented micro-typography (character
# protrusion, font expansion, tracking) which has no meaning for HTML/Gerby
# output. Providing this empty Python stub makes plasTeX's package loader
# succeed via `import microtype` instead of falling back to parsing the real
# microtype.sty, which sends the tokenizer into an infinite loop on recent
# TeXLive versions (microtype.sty 2026/03/01 v3.2d).
