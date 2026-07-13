"""
C.6.1 Quotations and Verse (p184)

"""

from plasTeX import Environment


class quote(Environment):
    blockType = True

class quotation(Environment):
    blockType = True

class verse(Environment):
    blockType = True

# TODO figure out why putting this in plasTeX.Renderers.Gerby causes things to malfunction
class slogan(Environment):
  blockType = True

class history(Environment):
  blockType = True

class reference(Environment):
  blockType = True
