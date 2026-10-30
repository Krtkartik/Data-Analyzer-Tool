import io
import os
import unicodedata

s = io.open("README.md", encoding="utf-8").read()
chars = sorted({c for c in s if ord(c) > 126})
lines = [f"U+{ord(c):04X}  {unicodedata.name(c, 'UNNAMED')}" for c in chars]
io.open("charset.txt", "w", encoding="utf-8").write("\n".join(lines))
print("distinct non-ascii:", len(chars))

import matplotlib

mdir = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
print("matplotlib fonts dir:", mdir, os.path.isdir(mdir))
print("candidates:", [f for f in os.listdir(mdir) if f.lower().startswith("dejavu")])
