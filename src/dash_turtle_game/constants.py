from enum import Enum, auto
from pathlib import Path

ASSET_DIR = Path(__file__).parents[2].resolve() / 'assets'

class CmdEvent(Enum):
    NONE = auto()
    QUIT = auto()
    LEFT = auto()
    RIGHT = auto()
    UP = auto()
