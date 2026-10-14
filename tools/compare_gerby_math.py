#!/usr/bin/env python3
"""Build the same tagged document using both Xy-pic backends."""
import argparse
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from plasTeX.Renderers.Gerby.MathRendering import scope_inline_svgs
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=root / 'examples/gerby-math/book.tex')
    parser.add_argument('--output', type=Path, default=Path('math-comparison'))
    parser.add_argument('--math-preamble', type=Path)
    parser.add_argument('--mathjax-config', type=Path)
    parser.add_argument('--tag', action='append', help='Show only this tag (repeatable)')
    parser.add_argument('--limit', type=int, default=50,
        help='Maximum fragments to show; 0 shows all (default: 50)')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('--limit must be nonnegative')
    source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root) + os.pathsep + env.get('PYTHONPATH', '')
    env['TEXINPUTS'] = str(source.parent) + os.pathsep + env.get('TEXINPUTS', '')
    timings = {}
    # Stage read-only inputs: plasTeX writes its auxiliary file in its cwd.
    with tempfile.TemporaryDirectory(prefix='inputs-', dir=str(output)) as staging:
        staging = Path(staging)
        for entry in source.parent.iterdir():
            if entry.name in ('.git', source.stem + '.paux') or entry == output:
                continue
            (staging / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
        for backend in ('xyjaxv4', 'svg'):
            command = [sys.executable, '-c',
                'import sys; from plasTeX.client import main; main(sys.argv[1:])',
                '--renderer=Gerby', '--imager=none', '--vector-imager=none',
                '--math-renderer=svg', '--tikz-renderer=svg', '--xypic-renderer=' + backend,
                '--dir=' + str(output / backend), '--math-cache=' + str(output / 'cache')]
            for option in ('math_preamble', 'mathjax_config'):
                filename = getattr(args, option)
                if filename:
                    command.append('--' + option.replace('_', '-') + '=' + str(filename.resolve()))
            command.append(source.name)
            started = time.perf_counter()
            with (output / (backend + '.log')).open('w', encoding='utf-8') as log:
                process = subprocess.run(command, cwd=str(staging), env=env,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            if process.returncode:
                raise SystemExit('Build failed; see ' + str(output / (backend + '.log')))
            timings[backend] = {'seconds': time.perf_counter() - started,
                'cache': json.loads((output / backend / 'math-rendering.json').read_text())}
    files = sorted(path.name for path in (output / 'svg').glob('*.tag'))
    if args.tag:
        files = [filename for filename in files if any('-' + tag + '-' in filename for tag in args.tag)]
    if args.limit:
        files = files[:args.limit]
    rows = []
    for filename in files:
        cells = []
        for backend in ('xyjaxv4', 'svg'):
            content = (output / backend / filename).read_text(encoding='utf-8')
            cells.append('<td><div class="fragment">' + content + '</div></td>')
        rows.append('<tr><th colspan="2">' + html.escape(filename) + '</th></tr><tr>' + ''.join(cells) + '</tr>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Gerby math backend comparison</title>
<style>
body {font:18px Georgia,serif;max-width:1400px;margin:2rem auto;padding:0 1rem;color:#222}
table {width:100%;table-layout:fixed;border-collapse:collapse}
td,th {padding:1rem;border:1px solid #ddd;vertical-align:top;overflow:auto}
.fragment {overflow:auto}
th {font:16px system-ui;text-align:left;background:#f4f4f4}
.equation {text-align:center;margin:1rem 0}.equation-label {float:right}
td svg {max-width:none}pre {white-space:pre-wrap;font-size:14px}
</style><h1>Gerby math backend comparison</h1>
<p>Both columns contain inline SVG. XyJax v4 runs during the build;
the native backend compiles Xy-pic with TeX and converts the PDF to SVG.
TikZ and tikz-cd use native TeX in both columns.</p>
<table><tr><th>XyJax v4 / MathJax 4</th><th>Native TeX / pdf2svg</th></tr>'''
    page += ''.join(rows) + '</table><h2>Build measurements</h2><pre>'
    page += html.escape(json.dumps(timings, indent=2)) + '</pre></html>'
    (output / 'comparison.html').write_text(scope_inline_svgs(page, 'comparison'), encoding='utf-8')
    (output / 'timings.json').write_text(json.dumps(timings, indent=2) + '\n', encoding='utf-8')
    print(output / 'comparison.html')


if __name__ == '__main__':
    main()
