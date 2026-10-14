#!/usr/bin/env python


"""
How to test this (for now):
  0) get yourself a copy of the Stacks project repository
  1) put the tags/tags file in the tags/tmp folder (which is populated after running make tags)
  2) comment out all but one reasonably sized chapter in book.tex
  3) run plastex --renderer=Gerby book.tex in tags/tmp
"""

import os, re, shutil
import plasTeX
from plasTeX.Renderers.PageTemplate import Renderer as _Renderer
from plasTeX.Renderers import Renderable, mixin, unmix
from plasTeX.DOM import Node
import json

log = plasTeX.Logging.getLogger()


# give the closest theorem environment to a node
def searchPrecedingTheorem(linear, node):
  # last visited node
  last = None

  for current in linear:
    # iterate over the theorems
    if current.nodeName == "thmenv":
      last = current

    # if the node matches, then return the last visited theorem node
    if current.isSameNode(node):
      return last.id

def willItBeWhitespace(node):
  if node.isElementContentWhitespace:
  # Spaces, newlines, and comments are whitespace known to plasTeX
    return True
  elif node.nodeName in ["label","reference","slogan","history"]:
  # labels, references, slogans, and history are currently assumed to be whitespace
    return True
  elif node.nodeName == "par":
  # A paragraph is whitespace if all it contains is whitespace
    return all([willItBeWhitespace(child) for child in node.childNodes])

class GerbyRenderable(Renderable):
  @property
  def filenameoverride(self):
    # handle tags
    if "tag" in self.userdata:
      environment = self.nodeName
      if self.nodeName == "thmenv":
        environment = self.thmName

        # decide whether or not paragraphs are whitespace
        for child in self.childNodes:
          child.isItWhitespace = willItBeWhitespace(child)

      # TODO hack / fix whilst testing Dan Halpern--Leistner's code
      return str(environment) + "-" + str(self.ref) + "-" + str(self.userdata["tag"]) + "-" + str(self.id) + ".tag"

    # handle proofs
    if self.nodeName == "proof":
      # caption can contain a \ref
      if "caption" in self.attributes and self.attributes["caption"] and len(self.attributes["caption"].getElementsByTagName("ref")) > 0:
        # use the first one for now, in theory there could be more
        label = [ref.attributes["label"] for ref in self.attributes["caption"].getElementsByTagName("ref")][0]
      # just take the closest theorem
      else:
        previous = self.ownerDocument.userdata["preceding-theorems"].get(id(self))
        label = previous.id

      if label in self.ownerDocument.userdata["labels"]:
        tag = self.ownerDocument.userdata["labels"][label]
        self.ownerDocument.userdata["proofs"][tag] += 1
        return tag + "-" + str(self.ownerDocument.userdata["proofs"][tag]) + ".proof"

    # handle slogans, history, ...
    if self.nodeName in ["history", "slogan", "reference"]:
      # Reach top level environment containing this node.
      # ASSUMPTION: The only other node type possibly containing this node is
      #             a paragraph node.
      parentEnv = self.parentNode
      while parentEnv.nodeName == "par":
        parentEnv = parentEnv.parentNode
      label = parentEnv.id

      if label in self.ownerDocument.userdata["labels"]:
        tag = self.ownerDocument.userdata["labels"][label]
        return tag + "." + self.nodeName

    raise AttributeError


"""Helper functors for Gerby"""

def decorateTags(node, labels):
  """Recursively decorate labeled nodes with Gerby-specific userdata"""
  if node.nodeType == plasTeX.Macro.ELEMENT_NODE and node.id[0:2] != "a0":
    # plasTeX.Packages.hyperref parses hypertargets, but we ignore them
    if node.nodeName != "hypertarget" and node.id in labels:
      node.userdata["tag"] = labels[node.id]

      if node.nodeName not in ["part", "chapter", "section", "subsection", "subsubsection"]:
        node.userdata["propagate"] = True

  if node.nodeName == "proof":
    node.userdata["propagate"] = True

    # make sure that there is always a paragraph in a proof
    if not all([child.nodeName == "par" for child in node.childNodes]):
      node.paragraphs()

  for child in node.childNodes:
    decorateTags(child, labels)

def loadTags(document):
  """Read the tags file and construct the tags and labels dictionary"""
  with open(document.userdata["working-dir"] + "/" + document.config["gerby"]["tags"]) as f:
    content = f.readlines()

  document.userdata["tags"] = dict()   # tag to label
  document.userdata["labels"] = dict() # label to tag
  document.userdata["proofs"] = dict() # count number of proofs for a tag

  for line in content:
    if line[0] == "#": continue

    (tag, label) = line.rstrip().split(",")
    document.userdata["tags"][tag] = label
    document.userdata["labels"][label] = tag
    document.userdata["proofs"][tag] = 0

def linearRepresentation(document):
  """Make a linear representation of the document containing theorems and proofs"""
  document.userdata["linear"] = list()
  stack = list()

  stack.extend(document.childNodes)

  while len(stack) > 0:
    node = stack.pop()

    if node.nodeName in ["thmenv", "proof", "reference", "history", "slogan"]:
      document.userdata["linear"].append(node)

    stack.extend(node.childNodes)

  document.userdata["linear"] = list(reversed(document.userdata["linear"]))
  cachePrecedingTheorems(document)

def cachePrecedingTheorems(document):
  """Associate proofs with the preceding theorem in a single pass."""
  previous = None
  preceding = document.userdata["preceding-theorems"] = dict()
  for node in document.userdata["linear"]:
    if node.nodeName == "thmenv":
      previous = node
    elif node.nodeName == "proof":
      preceding[id(node)] = previous

def tagRollCall(document):
    # Check whether or not all tags appear in the document
    attendanceSheet = dict(map(lambda t: (t, False), document.userdata["tags"].keys()))

    stack = list()
    stack.extend(document.childNodes)
    while len(stack) > 0:
        node = stack.pop()
        try:
            tag = node.userdata.get("tag")
            if tag and tag in attendanceSheet:
                attendanceSheet[tag] = True
        except:
            pass

        stack.extend(node.childNodes)
    return attendanceSheet

def partsList(document):
  """Make an association between parts and chapters"""
  parts = dict()
  stack = list()

  stack.extend(document.childNodes)
  current = None

  while len(stack) > 0:
    node = stack.pop()

    if node.nodeName == "part":
      current = node.ref.source
      parts[current] = list()
    elif node.nodeName == "chapter" and current != None:
      parts[current].append(node.ref.source)

    stack.extend(node.childNodes)

  return parts

def copyBibliographies(document):
  """Copy bibliography files by looking for bibliography elements"""
  stack = list()

  stack.extend(document.childNodes)

  while len(stack) > 0:
    node = stack.pop()

    if node.nodeName == "bibliography":
      files = node.attributes["files"].split(",")
      for f in files:
        shutil.copyfile(document.userdata["working-dir"] + "/" + f + ".bib", f + ".bib")

    stack.extend(node.childNodes)


def checkLabels(document):
  stack = list()
  stack.extend(document.childNodes)

  while len(stack) > 0:
    node = stack.pop()

    if node.nodeName in ["thmenv", "chapter", "section", "subsection", "subsubsection"]:
      if node.id[0:3] == "a00" and hasattr(node.ref, "source"):
        print("%s %s does not have a label" % (node.thmName if node.nodeName == "thmenv" else node.nodeName, node.ref.source))

    stack.extend(node.childNodes)



class Gerby(_Renderer):
  """ Tag-aware renderer for HTML documents """

  fileExtension = ''
  imageTypes = ['.png','.jpg','.jpeg','.gif']
  vectorImageTypes = ['.svg']
  renderableClass = GerbyRenderable

  def loadTemplates(self, document):
    """Load templates as in PageTemplate but also look for packages that
    want to override some templates and handles extra css and javascript."""

    try:
      import jinja2
    except ImportError:
      log.error('Jinja2 is not available, hence the HTML5 renderer cannot be used.')

    _Renderer.loadTemplates(self, document)
    rendererdata = document.rendererdata["gerby"] = dict()
    config = document.config

    # split-level must always be -2 to not create any clutter files
    config["files"]["split-level"] = -2

    rendererDir = os.path.dirname(__file__)

    srcDir = document.userdata['working-dir']
    buildDir = os.getcwd()

    for resrc in document.packageResources:
        # Next line may load templates or change
        # document.rendererdata['html5'] or copy some files to buildDir
        resrc.alter(
                renderer=self,
                rendererName='gerby',
                document=document,
                target=buildDir)


  def cleanup(self, document, files, postProcess=None):
    res = _Renderer.cleanup(self, document, files, postProcess=postProcess)
    return res

  def processFileContent(self, document, s):
    s = _Renderer.processFileContent(self, document, s)

    for fun in document.rendererdata["gerby"].get('processFileContents', []):
      s = fun(document, s)

    # remove empty paragraphs
    s = re.compile(r'<p>\s*</p>', re.I).sub(r'', s)

    # Remove extra paragraph tags around displaymath
    s = re.compile(r'<p>(<div class="equation".*?<\/div>)<\/p>', flags=re.DOTALL).sub(r'\1',s)

    return s

  def render(self, document):
    # create the tags and labels dictionaries in the document
    loadTags(document)

    copyBibliographies(document)

    # validity check
    checkLabels(document)

    # we decorate all DOM elements with labels that appear in the tags file
    decorateTags(document, document.userdata["labels"])

    # create a linearised version of the document containing theorems and proofs in order
    linearRepresentation(document)

    tagAttendanceSheet = tagRollCall(document)
    for tag in filter(lambda t: not tagAttendanceSheet[t], tagAttendanceSheet):
      log.warning("document does not contain tag %s" % tag)

    # associate parts to chapters
    parts = partsList(document)
    with open("parts.json", "w") as f:
      json.dump(parts, f)

    _Renderer.render(self, document)

    # write footnotes if there are any
    if "footnotes" in document.userdata:
      mixin(Node, Gerby.renderableClass)
      Node.renderer = self
      for footnote in document.userdata["footnotes"]:
        with open("{0}.footnote".format(footnote.id),"w") as f:
          f.write(str(footnote))
      del Node.renderer
      unmix(Node, Gerby.renderableClass)

    # write meta information, like line count.
    with open("meta.statistics", "w") as f:
      json.dump(document.context.meta, f)

Renderer = Gerby


def outputTree(node, depth=0):
  if hasattr(node, "id") and node.id[0:2] != "a0":
    print("-" * depth + node.nodeName + ": " + node.id + ", level = " + str(depth))
  elif node.nodeName == "index":
    print("*" * depth + node.nodeName)
  else:
    print("-" * depth + node.nodeName)

  for child in node.childNodes:
    outputTree(child, depth + 1)
