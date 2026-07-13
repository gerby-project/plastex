import os
import tempfile
from jinja2 import Template
from bs4 import BeautifulSoup

from plasTeX import NoCharSubEnvironment, Command
from plasTeX.PackageResource import PackageProcessFilecontents
from plasTeX.Packages import tikz

from plasTeX.Logging import getLogger
log = getLogger()

class tikzcd(NoCharSubEnvironment):
    """
    A tikz-cd diagram whose content will be converted in the processFileContent callback.
    """


    class ar(Command):
        pass

    class rar(Command):
        pass

    class lar(Command):
        pass

    class uar(Command):
        pass

    class drar(Command):
        pass

    class dar(Command):
        pass

    class dlar(Command):
        pass

    class ular(Command):
        pass

    class urar(Command):
        pass


def ProcessOptions(options, document):
    """This is called when the package is loaded."""

    try:
        with open(tikz.getConfig(document, 'tikz-cd-template'), "r") as file:
            template = file.read()
    except IOError:
        log.info('Using default TikZ template.')
        template = u"\\documentclass{standalone}\n\\usepackage{tikz-cd}" + \
                   u"\\begin{document}{{ tikzpicture }}\\end{document}"
    document.userdata['tikzcd'] = {
            'template': Template(template),
            'tmp_dir': tempfile.mkdtemp(),
            'compiler': tikz.getConfig(document, 'tikz-compiler', 'pdflatex'),
            'pdf2svg': tikz.getConfig(document, 'tikz-converter', 'pdf2svg'),
            }

    def convert(document, content):
        return tikz.tikzConvert(
                document,
                content,
                'tikzcd',
                'Commutative diagram')

    cb = PackageProcessFilecontents(
            renderers='html5',
            data=convert)
    document.addPackageResource(cb)

    cb = PackageProcessFilecontents(
            renderers='gerby',
            data=convert)
    document.addPackageResource(cb)
