from plasTeX.TeX import TeX
import pytest


def test_tikz_cd_exposes_tikz_picture_environment():
    tex = TeX()
    tex.input(r'''\documentclass{article}\usepackage{tikz-cd}
\begin{document}
\begin{tikzpicture}\draw (0,0) -- (1,1);\end{tikzpicture}
\end{document}''')
    document = tex.parse()
    pictures = document.getElementsByTagName('tikzpicture')
    assert len(pictures) == 1
    assert r'\draw' in pictures[0].source
    assert pictures[0].source.endswith(r'\end{tikzpicture}')


@pytest.mark.parametrize('opening,closing', [
    (r'\begin{xy}', r'\end{xy}'), (r'\xy', r'\endxy')])
def test_xy_environment_preserves_its_body(opening, closing):
    tex = TeX()
    tex.input(r'''\documentclass{article}\usepackage{xy}
\begin{document}
\begin{equation}\label{equation:xy}
''' + opening + r''' (0,0)*+{A}="a", (20,0)*+{B}="b", "a";"b" **@{-} ''' + closing + r'''
\end{equation}
After the diagram.
\end{document}''')
    document = tex.parse()
    diagrams = document.getElementsByTagName('xy')
    assert len(diagrams) == 1
    assert '(20,0)' in diagrams[0].source
    assert '**@{-}' in diagrams[0].source
    assert diagrams[0].source.rstrip().endswith(closing)
    assert 'After the diagram.' in document.textContent
