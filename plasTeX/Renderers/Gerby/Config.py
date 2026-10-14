from plasTeX.ConfigManager import *

def addConfig(config: ConfigManager):
    section = config.addSection('gerby', 'Gerby renderer options')

    section['tags'] = StringOption(
        """Location of the tags file""",
        options='--tags',
        default='tags',
    )

    for name, description, default in [
        ('math-renderer', 'Ordinary mathematics: raw, svg, or mathml', 'raw'),
        ('xypic-renderer', 'Xy-pic diagrams: raw, xyjaxv4, or svg (native TeX)', 'raw'),
        ('tikz-renderer', 'TikZ and tikz-cd diagrams: raw or svg', 'raw'),
        ('math-cache', 'Persistent build-time math cache directory', '.gerby-math-cache'),
        ('math-preamble', 'Additional native TeX preamble file', ''),
        ('mathjax-config', 'JSON file containing MathJax macros', ''),
        ('math-node', 'Node.js executable for MathJax', 'node'),
        ('math-tex', 'Native diagram PDF compiler', 'pdflatex'),
        ('math-converter', 'Native diagram PDF to SVG converter', 'pdf2svg'),
    ]:
        section[name] = StringOption(description, options='--' + name, default=default)
    section['math-timeout'] = IntegerOption(
        'Maximum seconds per MathJax request or native diagram batch',
        options='--math-timeout', default=120)

    # ponytail: the --tikz-* options live in the html5 section (HTML5/Config.py),
    # which is where Packages/tikz.py reads them; registering them here too would
    # make argparse crash on duplicate flags
