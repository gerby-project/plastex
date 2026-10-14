# Bundled XyJax v4

`xyjaxv4.js` is the production bundle from the local XyJax-v4 checkout at
commit `448bcf5e9e1f231648b68c020222ec11c4706d10` (version 4.1.0), based on
<https://github.com/matssson/XyJax-v4> by Isao Sonobe and contributors.
It includes the cell-content parser fixes in commit `68e8d24`, allowing
compound cell text and text before, after, and between arrows.
The accompanying `LICENSE` is Apache-2.0.

Copyright (c) 2011–2021 Isao Sonobe <sonoisa@gmail.com>.

To refresh the bundle from that checkout:

```sh
cd /path/to/XyJax-v4
npm ci
npm run build
cp build/xypic.js /path/to/plastex/plasTeX/Renderers/Gerby/mathjax/vendor/xyjaxv4.js
```

Update this provenance and rerun `unittests/GerbyMath.py` when refreshing.
The bundle runs with the pinned MathJax 4 version in the parent package lock.
