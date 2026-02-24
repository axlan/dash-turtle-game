from enum import Enum, auto
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ASSET_DIR = Path(__file__).parents[2].resolve() / 'assets'

DimType = tuple[int, int]

class CmdEvent(Enum):
    NONE = auto()
    LEFT = auto()
    RIGHT = auto()
    UP = auto()
    QUIT = auto()
    RUN_QUEUED = auto()
    STOP = auto()
    TOGGLE_QUEUING = auto()
    TOGGLE_CONNECT = auto()

class TileType(Enum):
    UNKNOWN = auto()
    EMPTY = auto()
    BLOCKED = auto()
    GOAL = auto()


@dataclass
class TurtlePose:
    x: float
    y: float
    theta: float


@dataclass
class TileState:
    type: TileType
    observed: bool = False
    text: str = ''

@dataclass
class Settings:
    START_TILE: DimType
    START_THETA: float
    GOAL_TILE: DimType
    MAP_SIZE_TILES: DimType
    TILE_SIZE_CM: float
    TILE_SIZE_PIXELS: int

    FRONT_DETECTION_THRESHOLD: int
    CRASH_DETECTION_THRESHOLD: int
    TURN_TIME: float
    FORWARD_TIME: float

    TIME_BETWEEN_PRINT_SEC: float

    MQTT_BROKER_ADDR: Optional[str]

    BOT_CONNECT_TIMEOUT_SEC: float

def normalize_ang360(angle: float) -> float:
    return angle % 360.0

