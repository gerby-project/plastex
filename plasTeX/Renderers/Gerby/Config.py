from plasTeX.ConfigManager import *

def addConfig(config: ConfigManager):
    section = config.addSection('gerby', 'Gerby renderer options')

    section['tags'] = StringOption(
        """Location of the tags file""",
        options='--tags',
        default='tags',
    )

    # ponytail: the --tikz-* options live in the html5 section (HTML5/Config.py),
    # which is where Packages/tikz.py reads them; registering them here too would
    # make argparse crash on duplicate flags
