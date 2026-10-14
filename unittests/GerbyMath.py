import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

import pytest

from plasTeX.client import main, collect_renderer_config
from plasTeX.Config import defaultConfig
from plasTeX.TeX import TeX, TeXDocument
from plasTeX.Renderers.Gerby.MathRendering import (
    MathPipeline, MathJaxWorker, MathRenderError, normalize_source)


ROOT = Path(__file__).resolve().parents[1]
NODE_READY = (shutil.which('node') and
    (ROOT / 'plasTeX/Renderers/Gerby/mathjax/node_modules/mathjax').is_dir())
TEX_READY = shutil.which('pdflatex') and shutil.which('pdf2svg')
needs_node = pytest.mark.skipif(not NODE_READY, reason='Run npm ci in Gerby/mathjax')
needs_tex = pytest.mark.skipif(not TEX_READY, reason='pdflatex and pdf2svg required')


def pipeline(tmp_path, **options):
    config = defaultConfig()
    collect_renderer_config(config)
    for name, value in options.items():
        config['gerby'][name.replace('_', '-')] = value
    document = TeXDocument(config=config)
    document.userdata['working-dir'] = str(tmp_path)
    return MathPipeline(document)


def test_raw_needs_no_dependencies_or_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with_pipeline = pipeline(tmp_path)
    assert with_pipeline.render('$x<y$', False) == '$x<y$'
    with_pipeline.close()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('source,expected', [
    ('$x+1$', 'x+1'),
    (r'\begin{equation}\label{equation:x}x\end{equation}', 'x'),
    (r'\begin{align}a&=b\\c&=d\end{align}', r'\begin{aligned}a&=b\\c&=d\end{aligned}'),
    (r'\begin{tikzcd}A & B\end{tikzcd}', r'\begin{tikzcd}A & B\end{tikzcd}'),
    (r'\xymatrix{A\ar @{~ >}[r] & B}', r'\xymatrix{A\ar @{~>}[r] & B}'),
    ('$a\n\nb$', 'a\nb'),
    (r'$x,\linebreak[0] y$', 'x, y'),
    (r'$\xy (0,0)*+{A}\endxy$', r'\begin{xy} (0,0)*+{A}\end{xy}'),
])
def test_source_normalization(source, expected):
    assert normalize_source(source) == expected


def test_reject_invalid_backend(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(MathRenderError, match='xypic-renderer'):
        pipeline(tmp_path, xypic_renderer='invalid')


@needs_node
def test_complete_svg_escaping_and_warm_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = pipeline(tmp_path, math_renderer='svg')
    try:
        content = first.render('$x^2+1<y$', False)
        assert 'alt="$x^2+1&lt;y$"' in content
        svg = ET.parse(next((tmp_path / 'images').glob('*.svg'))).getroot()
        groups = [node.attrib.get('data-latex') for node in svg.iter()]
        assert '+' in groups and '1' in groups and '<' in groups and 'y' in groups
    finally:
        first.close()
    # Reuse must work without starting Node, and restore deleted output assets.
    shutil.rmtree(str(tmp_path / 'images'))
    def unexpected_worker(*args, **kwargs):
        raise AssertionError('Warm cache started MathJax')
    monkeypatch.setattr('plasTeX.Renderers.Gerby.MathRendering.MathJaxWorker', unexpected_worker)
    second = pipeline(tmp_path, math_renderer='svg')
    try:
        assert second.render('$x^2+1<y$', False) == content
        assert second.stats['cache_hits'] == 1
        assert second.stats['rendered'] == 0
        assert len(list((tmp_path / 'images').glob('*.svg'))) == 1
    finally:
        second.close()


@needs_node
def test_mathml_and_macro_configuration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'macros.json').write_text(json.dumps({'macros': {'testmacro': [r'\frac{#1}{2}', 1]}}))
    renderer = pipeline(tmp_path, math_renderer='mathml', mathjax_config='macros.json')
    try:
        content = renderer.render(r'$\testmacro{x}$', False)
        math = ET.fromstring(re.search(r'<math\b.*</math>', content, re.S).group())
        assert math.find('.//{http://www.w3.org/1998/Math/MathML}mfrac') is not None
        assert not list((tmp_path / 'images').glob('*.svg'))
    finally:
        renderer.close()


@needs_node
def test_errors_are_explicit_and_definitions_are_isolated():
    worker = MathJaxWorker('node', {}, 10)
    try:
        worker.render(r'\def\testmacro{x}\testmacro', False)
        with pytest.raises(MathRenderError, match='Undefined control sequence'):
            worker.render(r'\testmacro', False)
    finally:
        worker.close()


@needs_node
@needs_tex
@pytest.mark.parametrize('backend', ['xyjaxv4', 'svg'])
def test_tagged_book_both_backends_and_native_batch(tmp_path, monkeypatch, backend):
    monkeypatch.chdir(tmp_path)
    for name in ('book.tex', 'tags'):
        shutil.copyfile(str(ROOT / 'examples/gerby-math' / name), str(tmp_path / name))
    command = ['--renderer=Gerby', '--imager=none', '--vector-imager=none',
        '--math-renderer=svg', '--tikz-renderer=svg', '--xypic-renderer=' + backend, 'book.tex']
    main(command)
    output = tmp_path / 'book'
    stats = json.loads((output / 'math-rendering.json').read_text())
    assert stats['tex_batches'] == 1
    assert stats['rendered'] == 9
    assets = list((output / 'images').glob('*.svg'))
    assert len(assets) == 9
    for asset in assets:
        assert ET.parse(asset).getroot().tag == '{http://www.w3.org/2000/svg}svg'
    contents = '\n'.join(file.read_text() for file in output.glob('*.tag'))
    expected = 'tex' if backend == 'svg' else 'xyjaxv4'
    assert 'data-math-backend="{}"'.format(expected) in contents
    assert 'href="/tag/0002"' in contents
    assert '$x^2+1$' in contents
    assert '<tikzcd' not in contents and '<tikzpicture' not in contents
    refs = re.findall(r'src="(images/[^\"]+)"', contents)
    assert len(refs) > len(set(refs))  # repeated formulas share an asset
    # Full rerender must require neither Node nor TeX on a cache hit.
    monkeypatch.chdir(tmp_path)
    def unexpected(*args, **kwargs):
        raise AssertionError('Warm cache invoked a renderer')
    monkeypatch.setattr(MathPipeline, 'render_native', unexpected)
    monkeypatch.setattr(MathPipeline, 'render_mathjax', unexpected)
    main(command)
    stats = json.loads((output / 'math-rendering.json').read_text())
    assert stats['rendered'] == 0 and stats['tex_batches'] == 0
    assert stats['cache_hits'] == 9


@needs_tex
def test_native_preamble_dependency_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    macrofile = tmp_path / 'macro.tex'
    macrofile.write_text(r'\newcommand{\testmacro}{A}')
    (tmp_path / 'preamble.tex').write_text(r'\input{macro.tex}')
    first = pipeline(tmp_path, xypic_renderer='svg', math_preamble='preamble.tex')
    try:
        content = first.render(r'$\xymatrix{\testmacro\ar[r] & B}$', False)
        result = next(iter(first.results.values()))
        svg = ET.parse(next((tmp_path / 'images').glob('*.svg'))).getroot()
        # SVG's PDF points are 72/in; TeX points are 72.27/in. Extra
        # paragraph indentation would shrink the diagram in its CSS box.
        assert float(svg.attrib['width'].rstrip('pt')) == pytest.approx(
            float(result['width'][:-2]) * 10 * 72 / 72.27, rel=0.001)
    finally:
        first.close()
    macrofile.write_text(r'\newcommand{\testmacro}{CCC}')
    second = pipeline(tmp_path, xypic_renderer='svg', math_preamble='preamble.tex')
    try:
        changed = second.render(r'$\xymatrix{\testmacro\ar[r] & B}$', False)
        assert changed != content
        assert second.stats['rendered'] == 1
        assert second.stats['cache_hits'] == 0
    finally:
        second.close()


@needs_node
@needs_tex
@pytest.mark.parametrize('backend', ['xyjaxv4', 'svg'])
@pytest.mark.parametrize('opening,closing', [
    (r'\begin{xy}', r'\end{xy}'), (r'\xy', r'\endxy')])
def test_general_xy_diagram(tmp_path, monkeypatch, backend, opening, closing):
    monkeypatch.chdir(tmp_path)
    renderer = pipeline(tmp_path, xypic_renderer=backend)
    try:
        source = '$' + opening + r' (0,0)*+{A}="a", (20,0)*+{B}="b", "a";"b" **@{-} ' + closing + '$'
        content = renderer.render(source, False)
        assert '<img' in content
        svg = ET.parse(next((tmp_path / 'images').glob('*.svg'))).getroot()
        graphical = ('{http://www.w3.org/2000/svg}path', '{http://www.w3.org/2000/svg}line')
        assert sum(node.tag in graphical for node in svg.iter()) >= 3
    finally:
        renderer.close()
