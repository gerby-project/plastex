import pytest

from plasTeX.client import main
from plasTeX.Renderers.Gerby import GerbyRenderable, linearRepresentation
from plasTeX.TeX import TeX


def render_book(tmp_path, monkeypatch, body, tags):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tags").write_text(tags)
    (tmp_path / "book.tex").write_text(
        r"\documentclass{book}\usepackage{amsmath}"
        r"\newtheorem{lemma}{Lemma}\begin{document}" + body +
        r"\end{document}")
    main(["--renderer=Gerby", "--imager=none", "--vector-imager=none", "book.tex"])
    return tmp_path / "book"


def test_proof_associations_and_caption_override(tmp_path, monkeypatch):
    output = render_book(tmp_path, monkeypatch, r"""
\begin{lemma}\label{lemma:first}First statement.\end{lemma}
\begin{proof}First proof.\end{proof}
\begin{proof}Second proof.\end{proof}
\begin{lemma}\label{lemma:second}Second statement.\end{lemma}
\begin{proof}[Proof of Lemma~\ref{lemma:first}]Explicit reference.\end{proof}
\begin{proof}Implicit reference.\end{proof}
""", "0001,lemma:first\n0002,lemma:second\n")
    assert {file.name for file in output.glob("*.proof")} == {
        "0001-1.proof", "0001-2.proof", "0001-3.proof", "0002-1.proof"}
    assert "First proof." in (output / "0001-1.proof").read_text()
    assert "Second proof." in (output / "0001-2.proof").read_text()
    assert "Explicit reference." in (output / "0001-3.proof").read_text()
    assert "Implicit reference." in (output / "0002-1.proof").read_text()


def test_proof_outside_document_has_no_filename_override():
    tex = TeX()
    tex.input(r"""
\documentclass{article}
\usepackage{amsthm}
\begin{document}
\begin{proof}A proof.\end{proof}
\end{document}
""")
    document = tex.parse()
    document.userdata["labels"] = {}
    linearRepresentation(document)
    proof = document.getElementsByTagName("proof")[0].cloneNode(True)
    with pytest.raises(AttributeError):
        GerbyRenderable.filenameoverride.fget(proof)
