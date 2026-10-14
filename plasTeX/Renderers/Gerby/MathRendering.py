"""Optional, cached build-time mathematics and diagram rendering.

MathJax runs once per build; native diagrams are compiled in bounded batches.
SVG assets have their own documents, so cached glyph IDs cannot collide.
"""
import hashlib
import html
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET


MATH_NODES = frozenset(('math ensuremath eqnarray eqnarray* align align* '
    'gather gather* flalign flalign* multline multline* alignat alignat* '
    'split displaymath equation equation*').split())
DIAGRAM_NODES = frozenset(('tikzpicture', 'tikzcd'))
XYPIC_NODES = frozenset(('xy xybox xymatrix xymatrix@R xymatrix@C '
    'xymatrix@M xymatrix@W xymatrix@H xymatrix@L xymatrix@1').split())
XYPIC = re.compile(r'\\(?:xymatrix\b|xy\b|xybox\b|begin\s*\{xy\})')
TIKZ = re.compile(r'\\begin\s*\{(?:tikzpicture|tikzcd)\}')


class MathRenderError(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        ensure_ascii=False).encode('utf-8')).hexdigest()


def normalize_source(source):
    """Remove delimiters/numbering; Gerby owns equation labels and numbers."""
    source = source.strip()
    if not source.startswith((r'\begin{tikzpicture}', r'\begin{tikzcd}')):
        # Array row source can contain synthetic paragraph breaks, which
        # become illegal \par tokens when handed back to native TeX.
        source = re.sub(r'\n\s*\n', '\n', source)
    if XYPIC.search(source):
        source = re.sub(r'\\xy\b', lambda match: r'\begin{xy}', source)
        source = re.sub(r'\\endxy\b', lambda match: r'\end{xy}', source)
        # plasTeX's active '~' source gains a trailing space. In an Xy-pic
        # direction, '~>' is a wavy arrow, not a nonbreaking space.
        source = re.sub(r'@\{([^{}]*)\}', lambda match: '@{' +
            re.sub(r'~\s+', '~', match.group(1)) + '}', source)
    for left, right in [(r'\(', r'\)'), (r'\[', r'\]'), ('$$', '$$'), ('$', '$')]:
        if source.startswith(left) and source.endswith(right):
            source = source[len(left):-len(right)].strip()
            break
    source = re.sub(r'\\label\s*\{[^{}]*\}', '', source)
    # A cached SVG is one unbroken box; discard optional zero-strength breaks.
    source = re.sub(r'\\linebreak\s*\[\s*0\s*\]', '', source)
    source = re.sub(r'\\(?:tag\*?\s*\{[^{}]*\}|notag\b|nonumber\b)', '', source)
    match = re.fullmatch(r'\\begin\s*\{([^{}]+)\}(.*)\\end\s*\{\1\}',
                         source, re.S)
    if match:
        env, body = match.groups()
        if env in ('math', 'displaymath', 'equation', 'equation*'):
            source = body.strip()
        elif env.rstrip('*') in ('align', 'eqnarray', 'flalign', 'alignat', 'gather'):
            replacement = 'gathered' if env.rstrip('*') == 'gather' else 'aligned'
            if env.rstrip('*') == 'alignat':
                replacement = 'alignedat'
            if env.rstrip('*') == 'eqnarray':
                body = body.replace('&=&', '&=')
            source = r'\begin{' + replacement + '}' + body + r'\end{' + replacement + '}'
    if source.startswith(r'\ensuremath{') and source.endswith('}'):
        source = source[len(r'\ensuremath{'):-1]
    return source


class MathJaxWorker:
    def __init__(self, node, config, timeout):
        self.timeout = timeout
        self.errors = tempfile.TemporaryFile(mode='w+b')
        self.lines = queue.Queue()
        worker = Path(__file__).with_name('mathjax') / 'worker.cjs'
        try:
            self.process = subprocess.Popen([node, str(worker), json.dumps(config)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
                universal_newlines=True, bufsize=1)
        except OSError as error:
            self.errors.close()
            raise MathRenderError('Cannot start MathJax: {}'.format(error)) from error
        def read():
            for line in self.process.stdout:
                self.lines.put(line)
            self.lines.put(None)
        threading.Thread(target=read, daemon=True).start()
        try:
            if not self.receive().get('ready'):
                raise MathRenderError('MathJax worker did not become ready')
        except Exception:
            self.close()
            raise

    def receive(self):
        try:
            line = self.lines.get(timeout=self.timeout)
        except queue.Empty:
            raise MathRenderError('MathJax exceeded {} seconds'.format(self.timeout))
        if line is None:
            self.errors.seek(0)
            detail = self.errors.read().decode('utf-8', 'replace')
            raise MathRenderError('MathJax worker exited. Run npm ci in the Gerby '
                'mathjax directory.\n' + detail[-4000:])
        try:
            result = json.loads(line)
        except ValueError as error:
            raise MathRenderError('Invalid MathJax worker response: ' + line[:200]) from error
        if 'error' in result:
            raise MathRenderError(result['error'])
        return result

    def render(self, source, display, output='svg'):
        self.process.stdin.write(json.dumps({'tex': source, 'display': display, 'output': output}) + '\n')
        self.process.stdin.flush()
        return self.receive()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()
        self.errors.close()


class MathPipeline:
    def __init__(self, document):
        self.document = document
        self.options = document.config['gerby']
        for name, choices in [
            ('math-renderer', ('raw', 'svg', 'mathml')),
            ('xypic-renderer', ('raw', 'xyjaxv4', 'svg')),
            ('tikz-renderer', ('raw', 'svg')),
        ]:
            if self.options[name] not in choices:
                raise MathRenderError('--{} must be {}'.format(name, ', '.join(choices)))
        self.timeout = self.options['math-timeout']
        if self.timeout <= 0:
            raise MathRenderError('--math-timeout must be positive')
        self.enabled = any(self.options[name] != 'raw' for name in
            ('math-renderer', 'xypic-renderer', 'tikz-renderer'))
        self.cache = Path(self.options['math-cache']).resolve()
        self.source_dir = Path(document.userdata['working-dir'])
        self.output = Path.cwd() / 'images'
        self.worker = None
        self.results = {}
        self.keys = {}
        self.nodes = {}
        self.assets = set()
        self.dependency_stats = {}
        self.fingerprints = {}
        self.stats = {'requests': 0, 'cache_hits': 0, 'rendered': 0, 'tex_batches': 0}
        self.preamble = ''
        self.macros = {}
        if not self.enabled:
            return
        self.cache.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(exist_ok=True)
        if self.options['math-preamble']:
            self.preamble = self.read_source_file(self.options['math-preamble'])
        if self.options['mathjax-config']:
            config = json.loads(self.read_source_file(self.options['mathjax-config']))
            if set(config) - {'macros'} or not isinstance(config.get('macros', {}), dict):
                raise MathRenderError('--mathjax-config accepts a JSON object with a macros object')
            self.macros.update(config.get('macros', {}))
        if 'mathjax-macros' in document.config:
            self.macros.update(document.config['mathjax-macros']['macros'])

    def read_source_file(self, filename):
        path = Path(filename)
        if not path.is_absolute():
            path = self.source_dir / path
        return path.read_text(encoding='utf-8')

    def classify(self, source, kind='math'):
        if kind in DIAGRAM_NODES or TIKZ.search(source):
            return 'tex' if self.options['tikz-renderer'] == 'svg' else 'raw'
        if XYPIC.search(source):
            return {'svg': 'tex', 'xyjaxv4': 'xyjaxv4', 'raw': 'raw'}[
                self.options['xypic-renderer']]
        return self.options['math-renderer']

    def resolve_references(self, source):
        def replace(match):
            label = match.group(2)
            target = self.document.context.labels.get(label)
            if target is None:
                raise MathRenderError('Unresolved mathematics reference: ' + label)
            value = target.ref.source
            return '(' + value + ')' if match.group(1) == 'eqref' else value
        return re.sub(r'\\(eqref|ref)\s*\{([^{}]+)\}', replace, source)

    def fingerprint(self, backend):
        group = 'tex' if backend == 'tex' else 'mathjax'
        if group not in self.fingerprints:
            implementation = Path(__file__).read_bytes()
            if group == 'mathjax':
                directory = Path(__file__).with_name('mathjax')
                files = [directory / 'worker.cjs', directory / 'package-lock.json']
                if self.options['xypic-renderer'] == 'xyjaxv4':
                    files.append(directory / 'vendor' / 'xyjaxv4.js')
                value = [file.read_text(encoding='utf-8') for file in files]
                value.append(self.macros)
            else:
                value = [self.preamble]
                for name in ('math-tex', 'math-converter'):
                    executable = shutil.which(self.options[name])
                    if not executable:
                        raise MathRenderError('Executable not found: ' + self.options[name])
                    path = Path(executable).resolve()
                    stat = path.stat()
                    value.append((str(path), stat.st_size, stat.st_mtime_ns))
            self.fingerprints[group] = digest([hashlib.sha256(implementation).hexdigest(), value])
        return self.fingerprints[group]

    def request(self, source, display, kind='math'):
        backend = self.classify(source, kind)
        if backend == 'raw':
            return None
        normalized = self.resolve_references(normalize_source(source))
        key = digest([self.fingerprint(backend), backend, normalized, display, kind])
        self.stats['requests'] += 1
        if key not in self.results:
            cached = self.read_cache(key)
            if cached is not None:
                self.results[key] = cached
                self.stats['cache_hits'] += 1
            self.keys[key] = (backend, normalized, display, kind)
        return key

    def read_cache(self, key):
        try:
            result = json.loads((self.cache / (key + '.json')).read_text(encoding='utf-8'))
            if result.get('svg') and not (self.cache / (key + '.svg')).is_file():
                return None
            for filename, size, mtime in result.get('dependencies', []):
                if filename not in self.dependency_stats:
                    stat = Path(filename).stat()
                    self.dependency_stats[filename] = (stat.st_size, stat.st_mtime_ns)
                if self.dependency_stats[filename] != (size, mtime):
                    return None
            return result
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def write_cache(self, key, result):
        def write(suffix, content):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                    dir=str(self.cache), delete=False) as file:
                file.write(content)
                temporary = file.name
            os.replace(temporary, str(self.cache / (key + suffix)))
        if 'svg_content' in result:
            # Check that the converter produced an SVG, rather than an error page.
            svg = result.pop('svg_content')
            try:
                root = ET.fromstring(svg)
            except ET.ParseError as error:
                raise MathRenderError('Invalid SVG for {}: {}'.format(key, error)) from error
            if root.tag != '{http://www.w3.org/2000/svg}svg':
                raise MathRenderError('Converter did not produce an SVG')
            result['asset_digest'] = hashlib.sha256(svg.encode('utf-8')).hexdigest()
            write('.svg', svg)
            result['svg'] = True
        write('.json', json.dumps(result, sort_keys=True))
        self.results[key] = result
        self.stats['rendered'] += 1

    def prepare(self):
        if not self.enabled:
            return
        stack = list(reversed(self.document.childNodes))
        stack.extend(reversed(self.document.userdata.get('footnotes', [])))
        while stack:
            node = stack.pop()
            if node.nodeName in MATH_NODES | DIAGRAM_NODES | XYPIC_NODES:
                source = node.source
                key = self.request(source, node.nodeName not in ('math', 'ensuremath'), node.nodeName)
                self.nodes[id(node)] = (source, key)
                # These templates use source; they do not render descendants.
                continue
            stack.extend(reversed(node.childNodes))
        native = [key for key in self.keys if key not in self.results and self.keys[key][0] == 'tex']
        for start in range(0, len(native), 64):
            self.render_native(native[start:start + 64])
        for key in self.keys:
            if key not in self.results:
                self.render_mathjax(key)

    def render_mathjax(self, key):
        if self.worker is None:
            self.worker = MathJaxWorker(self.options['math-node'],
                {'macros': self.macros, 'xypic': self.options['xypic-renderer'] == 'xyjaxv4'},
                self.timeout)
        backend, source, display, kind = self.keys[key]
        try:
            result = self.worker.render(source, display, 'mathml' if backend == 'mathml' else 'svg')
        except MathRenderError as error:
            raise MathRenderError('MathJax failed for {}: {}\n{}'.format(key, error, source)) from error
        if backend == 'mathml':
            self.write_cache(key, {'mathml': result['mathml']})
        else:
            self.write_cache(key, {'svg_content': result['svg'],
                'style': result['style'], 'width': result['width'], 'height': result['height']})

    def render_native(self, keys):
        directory = Path(tempfile.mkdtemp(prefix='tex-', dir=str(self.cache)))
        lines = [r'\documentclass[multi=gerbydiagram,border=1pt]{standalone}',
            r'\usepackage{amsmath,amssymb,mathtools}', r'\usepackage[all]{xy}',
            r'\xyoption{2cell}\UseAllTwocells', r'\usepackage{tikz-cd}',
            r'\newcommand{\gerbymathraise}[2]{\raisebox{#1}{\ensuremath{#2}}}',
            r'\newcommand{\gerbymathlower}[2]{\raisebox{-#1}{\ensuremath{#2}}}',
            r'\usepackage{mathrsfs}' if any(r'\mathscr' in self.keys[key][1] for key in keys) else '',
            self.preamble, r'\newenvironment{gerbydiagram}{}{}',
            r'\newsavebox{\gerbybox}\newwrite\gerbysizes',
            r'\immediate\openout\gerbysizes=diagrams.sizes', r'\begin{document}',
            r'\setlength{\parindent}{0pt}']
        for key in keys:
            backend, source, display, kind = self.keys[key]
            # Some \ifplastex branches deliberately emit MathJax's braced
            # raise/lower syntax; leave TeX's primitive commands untouched.
            source = re.sub(r'\\(raise|lower)\s*(?=\{)',
                lambda match: r'\gerbymath' + match.group(1), source)
            body = source if kind in DIAGRAM_NODES else '$' + (
                r'\displaystyle ' if display else '') + source + '$'
            lines.extend([r'\begin{gerbydiagram}', r'\typeout{GERBY-BEGIN:' + key + '}',
                r'\setbox\gerbybox=\hbox{' + body + '}',
                r'\immediate\write\gerbysizes{' + key + r':\number\wd\gerbybox:\number\ht\gerbybox:\number\dp\gerbybox:\number\fontdimen6\font}',
                r'\noindent\usebox{\gerbybox}', r'\end{gerbydiagram}'])
        lines.append(r'\end{document}')
        texfile = directory / 'diagrams.tex'
        # standalone collects the environment in horizontal mode. End the
        # control lines with comments so their newlines add no interword glue.
        texfile.write_text('%\n'.join(lines) + '%\n', encoding='utf-8')
        env = dict(os.environ)
        env['TEXINPUTS'] = str(self.source_dir) + os.pathsep + env.get('TEXINPUTS', '')
        try:
            run = subprocess.run([self.options['math-tex'], '-no-shell-escape',
                '-interaction=nonstopmode', '-halt-on-error', '-recorder', texfile.name],
                cwd=str(directory), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=self.timeout, universal_newlines=True)
            if run.returncode:
                raise MathRenderError('Native TeX failed. Reproduction: {}\n{}'.format(texfile, run.stdout[-4000:]))
            sizes = dict((match[0], tuple(int(value) for value in match[1:])) for match in
                re.findall(r'([a-f0-9]+):(\d+):(\d+):(\d+):(\d+)',
                    (directory / 'diagrams.sizes').read_text(encoding='utf-8')))
            dependencies = []
            for line in (directory / 'diagrams.fls').read_text(encoding='utf-8').splitlines():
                if line.startswith('INPUT '):
                    path = Path(line[6:])
                    if not path.is_absolute():
                        path = directory / path
                    path = path.resolve()
                    if path.is_file() and directory not in path.parents:
                        stat = path.stat()
                        dependencies.append((str(path), stat.st_size, stat.st_mtime_ns))
            dependencies = sorted(set(dependencies))
            self.stats['tex_batches'] += 1
            for page, key in enumerate(keys, 1):
                svgfile = directory / (key + '.svg')
                convert = subprocess.run([self.options['math-converter'],
                    str(directory / 'diagrams.pdf'), str(svgfile), str(page)],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=self.timeout, universal_newlines=True)
                if convert.returncode or not svgfile.is_file():
                    raise MathRenderError('PDF to SVG conversion failed for {}: {}'.format(key, convert.stdout))
                if key not in sizes:
                    raise MathRenderError('Missing TeX dimensions for ' + key)
                width, height, depth, em = sizes[key]
                border = 65536  # standalone's one-point border, in scaled points
                self.write_cache(key, {'svg_content': svgfile.read_text(encoding='utf-8'),
                    'width': '{:.6f}em'.format((width + 2 * border) / em),
                    'height': '{:.6f}em'.format((height + depth + 2 * border) / em),
                    'style': 'vertical-align: -{:.6f}em;'.format((depth + border) / em),
                    'dependencies': dependencies})
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MathRenderError('Native rendering failed; source retained at {}: {}'.format(texfile, error)) from error
        # Keep failed batches for diagnosis; discard successful intermediates.
        shutil.rmtree(str(directory))

    def render(self, source, display, kind='math'):
        key = self.request(source, display, kind)
        return self.markup(source, key)

    def render_node(self, node):
        if id(node) in self.nodes:
            source, key = self.nodes[id(node)]
            return self.markup(source, key)
        return self.render(node.source, node.nodeName not in ('math', 'ensuremath'), node.nodeName)

    def markup(self, source, key):
        if key is None:
            return source
        if key not in self.results:
            if self.keys[key][0] == 'tex':
                self.render_native([key])
            else:
                self.render_mathjax(key)
        result = self.results[key]
        backend = self.keys[key][0]
        escaped = html.escape(source, quote=True)
        attributes = 'class="gerby-math mathjax_ignore tex2jax_ignore" data-math-backend="{}" data-math-tex="{}"'.format(backend, escaped)
        if 'mathml' in result:
            return '<span {}>{}</span>'.format(attributes, result['mathml'])
        filename = 'math-' + result['asset_digest'] + '.svg'
        target = self.output / filename
        if key not in self.assets:
            shutil.copyfile(str(self.cache / (key + '.svg')), str(target))
            self.assets.add(key)
        style = 'width:{};height:{};{}max-width:none'.format(result['width'], result['height'], result['style'])
        url = self.document.config['images']['base-url'].rstrip('/')
        url = (url + '/' if url else '') + 'images/' + filename
        return '<img {} src="{}" alt="{}" style="{}">'.format(attributes, html.escape(url, quote=True), escaped, style)

    def close(self):
        if self.worker is not None:
            self.worker.close()
            self.worker = None
        if self.enabled:
            (Path.cwd() / 'math-rendering.json').write_text(json.dumps(self.stats,
                indent=2, sort_keys=True) + '\n', encoding='utf-8')
