# Build-time mathematics in Gerby

Gerby can pre-render mathematics during the plasTeX run. Ordinary formulas
use MathJax 4; TikZ and tikz-cd use native TeX. Xy-pic has two selectable
implementations, both producing inline SVG in the generated fragments:

| Option | Implementation |
| --- | --- |
| `--math-renderer=svg` | MathJax 4 SVG, using the MathJax TeX font |
| `--math-renderer=mathml` | MathJax 4 conversion to inline MathML |
| `--xypic-renderer=xyjaxv4` | Bundled XyJax v4 running in MathJax 4 |
| `--xypic-renderer=svg` | Native Xy-pic → PDF → SVG |
| `--tikz-renderer=svg` | Native TikZ / tikz-cd → PDF → SVG |

All three defaults are `raw`, preserving the existing browser-rendered
math and legacy TikZ callbacks. Options are independent: choosing MathML
for formulas still allows SVG diagrams. General diagrams have no faithful
pure MathML representation, so neither diagram backend emits MathML.

## Install

Use Node.js 18 or newer and install the pinned packages alongside the renderer:

```sh
npm ci --prefix plasTeX/Renderers/Gerby/mathjax --ignore-scripts
```

Native SVG additionally requires `pdflatex`, `standalone`, `amsmath`, `amssymb`, `mathtools`,
`mathrsfs` when script letters are used,
Xy-pic, TikZ, tikz-cd, and `pdf2svg`. On macOS with TeX Live installed:

```sh
brew install pdf2svg
```

The bundled XyJax includes the parser fixes from the local XyJax-v4 checkout.
Its version, source commit, refresh instructions, and license are recorded
in [vendor/README.md](../plasTeX/Renderers/Gerby/mathjax/vendor/README.md).

## Build and compare

Run from the TeX source directory, where Gerby expects the `tags` file:

```sh
plastex --renderer=Gerby --math-renderer=svg \
  --xypic-renderer=xyjaxv4 --tikz-renderer=svg \
  --math-cache=/path/to/shared-math-cache --dir=build-xyjax book.tex

plastex --renderer=Gerby --math-renderer=svg \
  --xypic-renderer=svg --tikz-renderer=svg \
  --math-cache=/path/to/shared-math-cache --dir=build-native book.tex
```

The comparison helper builds both versions of the supplied fixture and
creates a page that can be opened directly in a browser:

```sh
python tools/compare_gerby_math.py --output /tmp/gerby-math-comparison
```

Open `/tmp/gerby-math-comparison/comparison.html`. The fixture covers matrix
spacing, curved arrows, arrow styles, compound labels, repeated inline math,
references, TikZ, and tikz-cd. Each column uses its backend's natural dimensions;
layout and arrow shapes can differ between XyJax and native TeX.
Run the helper again to measure a warm cache.
For another tagged document, pass `--source /path/to/book.tex`.
The preview shows at most 50 fragments; use `--tag TAG` (repeatable) to select
specific diagrams, or `--limit 0` to show all fragments. Both builds always
process the complete document. The helper stages its inputs so it leaves
the source project's auxiliary files unchanged.
Logs, rendered fragments, and `timings.json` remain in the comparison directory.
The comparison HTML is self-contained.

## Macros, resources, and integration

plasTeX expands document macros before rendering. For remaining MathJax macros,
use the existing `--mj-macros NAME VALUE` option, or `--mathjax-config` with:

```json
{"macros": {"myfrac": ["\\frac{#1}{2}", 1]}}
```

Native diagrams load `amsmath`, `amssymb`, `mathtools`, all Xy-pic extensions
(including two-cells), and `tikz-cd`, plus `mathrsfs` for script letters.
Braced MathJax `raise`/`lower` syntax from `ifplastex` branches is translated
to native TeX boxes. Supply an additional preamble with
`--math-preamble=/path/to/math-preamble.tex` for extra packages, TikZ libraries,
fonts, or definitions. This is a preamble fragment, without `documentclass`
or a document environment. Relative option paths and native input resources
resolve from the source directory. The original document's entire preamble
is not copied automatically.

Publish the generated fragments directly; mathematics needs no separate SVG
assets or image URL configuration. Gerby's existing equation numbers and
tag links stay outside the rendered math. Each SVG stores its TeX in
`aria-label` and `data-math-tex`, carries its baseline and dimensions in CSS, and has classes
that tell MathJax to ignore it. With all three renderers enabled, the generated
math needs no MathJax or XyJax JavaScript in readers' browsers. Existing website
scripts and unrelated client-side math may still need their own configuration.
MathJax formulas inherit the surrounding text color; native diagrams preserve
their TeX colors. Inline SVG can also be styled by the website's CSS.
Each SVG formula is an unbroken box; zero-strength `linebreak[0]`
hints are dropped. MathML uses the reader's browser math font and can look different.
XyJax's diagram SVG does not provide full mathematical accessibility.

## Cache and failures

One persistent Node worker handles the build. Native cache misses compile in
batches of up to 64 diagrams; pdf2svg converts each page independently. Cache keys
include expanded source, resolved references, display mode, backend, macros,
additional preamble, pinned JavaScript dependencies, converter identity, and
renderer implementation. Native cache records also track the TeX package,
font, and input files actually used; changes invalidate those records.
Canonical SVGs stay in the build cache. Before embedding, local glyph,
clipping, and paint references receive unique scopes for each occurrence and
written fragment. The comparison helper scopes the assembled page as well,
so showing an equation beside its enclosing lemma keeps those IDs distinct.

By default the cache is `.gerby-math-cache` in the output directory. Set
`--math-cache` to an absolute directory outside the output tree if that tree
is cleaned between builds. `math-rendering.json` reports source requests,
unique cache hits, rendered items, and native TeX batches. A fully warm build
requires no Node or TeX rendering, though native executable identities are
still checked for cache compatibility.

Unsupported MathJax commands and native compilation failures stop the build
with the failing source or reproduction path. Failed native batches retain
their `.tex` and `.log` files under the cache. Rendering has a configurable
`--math-timeout` (120 seconds by default, per worker request or compiler/converter
invocation), and native TeX runs with shell escape disabled. The compiler,
converter, and Node executables can be selected with `--math-tex`,
`--math-converter`, and `--math-node`. The native compiler must produce PDF;
the converter must accept `input.pdf output.svg page-number` arguments.

## Verification

After installing the optional tools, run:

```sh
python -m pytest -q unittests/GerbyMath.py unittests/Gerby.py
```

Tests exercise both real engines, SVG escaping and complete inline output,
MathML, macro configuration and isolation, tag preservation, native batching,
cache reuse without invoking either engine, and invalidation of included TeX files.
