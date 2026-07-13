from plasTeX.TeX import TeX

def test_accent():
    input_data = r'\"o'
    tex = TeX()
    tex.input(input_data)
    node = tex.parse()[0]
    # gerby: source yields the accented character itself (gerby-project#4)
    assert node.source == 'ö'
    assert node.str == 'ö'

def test_combining():
    input_data = r'\c{o}'
    tex = TeX()
    tex.input(input_data)
    node = tex.parse()[0]
    assert node.source == 'o̧'
    assert node.str == 'o̧'

def test_middle_combining():
    input_data = r'\t{op}'
    tex = TeX()
    tex.input(input_data)
    node = tex.parse()[0]
    assert node.source == 'o͡p'
    assert node.str == 'o͡p'

def test_empty_accent():
    input_data = r'\~{}'
    tex = TeX()
    tex.input(input_data)
    node = tex.parse()[0]
    assert node.source == '~'
    assert node.str == '~'
