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
    MathPipeline, MathJaxWorker, MathRenderError, normalize_source,
    scope_svg_ids, scope_inline_svgs)


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
        assert 'aria-label="$x^2+1&lt;y$"' in content
        svg = ET.fromstring(content)
        groups = [node.attrib.get('data-latex') for node in svg.iter()]
        assert '+' in groups and '1' in groups and '<' in groups and 'y' in groups
    finally:
        first.close()
    # Reuse must work without starting Node or publishing any SVG files.
    assert not (tmp_path / 'images').exists()
    def unexpected_worker(*args, **kwargs):
        raise AssertionError('Warm cache started MathJax')
    monkeypatch.setattr('plasTeX.Renderers.Gerby.MathRendering.MathJaxWorker', unexpected_worker)
    second = pipeline(tmp_path, math_renderer='svg')
    try:
        assert second.render('$x^2+1<y$', False) == content
        assert second.stats['cache_hits'] == 1
        assert second.stats['rendered'] == 0
        assert not (tmp_path / 'images').exists()
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
    assert not list((output / 'images').glob('*.svg'))
    contents = '\n'.join(file.read_text() for file in output.glob('*.tag'))
    expected = 'tex' if backend == 'svg' else 'xyjaxv4'
    assert 'data-math-backend="{}"'.format(expected) in contents
    assert 'href="/tag/0002"' in contents
    assert '$x^2+1$' in contents
    assert '<tikzcd' not in contents and '<tikzpicture' not in contents
    assert '<svg' in contents and '<img' not in contents
    assert '<?xml' not in contents
    # Separate equations also propagate into their parent fragment. Their
    # SVG definitions must stay distinct when these outputs are assembled.
    ids = re.findall(r'\bid="(gerby-[^"]+)"', contents)
    assert len(ids) == len(set(ids))
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
        key = next(iter(first.results))
        svg = ET.parse(first.cache / (key + '.svg')).getroot()
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
        assert '<svg' in content
        svg = ET.fromstring(content)
        graphical = ('{http://www.w3.org/2000/svg}path', '{http://www.w3.org/2000/svg}line')
        assert sum(node.tag in graphical for node in svg.iter()) >= 3
    finally:
        renderer.close()


def test_svg_ids_and_local_references_are_scoped():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg"
        xmlns:xlink="http://www.w3.org/1999/xlink" aria-labelledby="label description">
      <title id="label">A</title><desc id="description">Diagram</desc>
      <defs><path id="glyph" d="M0 0L1 1"/>
        <clipPath id="clip"><path d="M0 0L1 1"/></clipPath>
        <linearGradient id="paint"/></defs>
      <g clip-path="url(#clip)" style="fill:url('#paint');stroke:#fff">
        <use xlink:href="#glyph"/><use href="#glyph"/>
        <image href="other.svg#glyph"/>
      </g>
    </svg>'''
    first = ET.fromstring(scope_svg_ids(svg, 'first'))
    second = ET.fromstring(scope_svg_ids(svg, 'second'))
    first_ids = {node.attrib['id'] for node in first.iter() if 'id' in node.attrib}
    second_ids = {node.attrib['id'] for node in second.iter() if 'id' in node.attrib}
    assert not first_ids & second_ids
    assert first.attrib['aria-labelledby'] == 'first-label first-description'
    group = first.find('{http://www.w3.org/2000/svg}g')
    assert group.attrib['clip-path'] == 'url(#first-clip)'
    assert group.attrib['style'] == "fill:url('#first-paint');stroke:#fff"
    uses = group.findall('{http://www.w3.org/2000/svg}use')
    assert uses[0].attrib['{http://www.w3.org/1999/xlink}href'] == '#first-glyph'
    assert uses[1].attrib['href'] == '#first-glyph'
    assert group.find('{http://www.w3.org/2000/svg}image').attrib['href'] == 'other.svg#glyph'


def test_assembled_inline_svg_handles_nested_svg():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" class="gerby-math">
      <defs><path id="gerby-svg-glyph" d="M0 0L1 1"/></defs>
      <svg><use href="#gerby-svg-glyph"/></svg>
    </svg>'''
    content = scope_inline_svgs('<div>' + svg + svg + '</div>', 'page')
    document = ET.fromstring(content)
    ids = [node.attrib['id'] for node in document.iter() if 'id' in node.attrib]
    assert len(ids) == len(set(ids)) == 2
    refs = [node.attrib['href'][1:] for node in document.iter() if 'href' in node.attrib]
    assert set(refs) == set(ids)
    # Written fragments already have gerby-fragment-* scopes; the page
    # assembler must still scope them when the same fragment is repeated.
    repeated = scope_inline_svgs(content + content, 'assembled')
    ids = re.findall(r'\bid="([^"]+)"', repeated)
    assert len(ids) == len(set(ids))


@needs_node
@needs_tex
@pytest.mark.parametrize('backend', ['xyjaxv4', 'svg'])
def test_crossing_arrows_preserve_explicit_hole(tmp_path, monkeypatch, backend):
    monkeypatch.chdir(tmp_path)
    renderer = pipeline(tmp_path, xypic_renderer=backend)
    try:
        source = r'$\xymatrix{A\ar[dr]|\hole & B\ar[dl]\\C & D}$'
        content = renderer.render(source, True)
        assert '<svg' in content
        assert r'|\hole' in content
    finally:
        renderer.close()
