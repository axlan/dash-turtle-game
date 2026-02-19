from enum import Enum, auto
from typing import Iterable, Sequence
from dataclasses import dataclass

import pygame


from .constants import ASSET_DIR

BG_COLOR      = pygame.Color("white")
WINDOW_TITLE = 'TurtleBot'
TILE_SHEET = ASSET_DIR / 'images' / 'CC_Tileset.webp'
TILE_SHEET_CELL_SIZE = 32
TURTLE_IMAGE = ASSET_DIR / 'images' / 'turtle.png'

DimType = tuple[int,int]

class WindowEvent(Enum):
    QUIT = auto()
    LEFT = auto()
    RIGHT = auto()
    UP = auto()

class TileType(Enum):
    UNKNOWN = auto()
    EMPTY = auto()
    BLOCKED = auto()
    GOAL = auto()


@dataclass(frozen=False)
class TurtlePose:
    x: float = 0
    y: float = 0
    theta: float = 0

TILE_SHEET_OFFSETS = {
    TileType.UNKNOWN: (2, 13),
    TileType.EMPTY: (0, 0),
    TileType.BLOCKED: (0, 1),
    TileType.GOAL: (3, 2),
}

class GameMap:
    def __init__(self,
                 num_map_tiles: DimType,
                 goal_tile:DimType,
                 tile_size_pixels: int
                 ) -> None:
        pygame.init()
        pygame.display.set_caption(WINDOW_TITLE)
        
        self.tile_size = tile_size_pixels
        self.width = self.tile_size * num_map_tiles[0]
        self.height = self.tile_size * num_map_tiles[1]

        self.tiles:list[list[TileType]] = []
        for _ in range(num_map_tiles[0]):
            col = [TileType.UNKNOWN] * num_map_tiles[1]
            self.tiles.append(col)

        self.tiles[goal_tile[0]][goal_tile[1]] = TileType.GOAL

        self.screen = pygame.display.set_mode((self.width, self.height))

        self.turtle_pose = TurtlePose()
        self.turtle_frame = pygame.image.load(TURTLE_IMAGE).convert_alpha()
        self.turtle_frame = pygame.transform.scale(self.turtle_frame, (self.tile_size, self.tile_size))

        sheet = pygame.image.load(TILE_SHEET).convert_alpha()
        self.tile_map:dict[TileType, pygame.Surface] = {}

        fw = TILE_SHEET_CELL_SIZE
        fh = TILE_SHEET_CELL_SIZE
        for t, index in TILE_SHEET_OFFSETS.items():
            frame_surf = pygame.Surface((fw, fh), pygame.SRCALPHA)
            frame_surf.blit(sheet, (0, 0), (index[0] * fw, index[1] * fh, fw, fh))
            self.tile_map[t] = pygame.transform.scale(frame_surf, (self.tile_size, self.tile_size))


    def GetWindowEvents(self) -> Iterable[WindowEvent]:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:  # X button or Alt+F4
                yield WindowEvent.QUIT
            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_RIGHT:
                    yield WindowEvent.RIGHT
                elif event.key == pygame.K_LEFT:
                    yield WindowEvent.LEFT
                elif event.key == pygame.K_UP:
                    yield WindowEvent.UP
                elif event.key == pygame.K_ESCAPE:
                    yield WindowEvent.QUIT


    def Draw(self):
        self.screen.fill(BG_COLOR)

        for c, col_tiles in enumerate(self.tiles):
            for r, t in enumerate(col_tiles):
                surf = self.tile_map[t]
                x = self.tile_size * c
                y = self.height - self.tile_size * (r + 1)
                self.screen.blit(surf, (x,y) , (0,0,self.tile_size,self.tile_size))

        rotated = pygame.transform.rotate(self.turtle_frame, self.turtle_pose.theta)
        rotated_rect = rotated.get_rect()
        # handle y starting at top and going down
        y = self.height - self.turtle_pose.y
        rotated_rect.center = (int(self.turtle_pose.x), int(y))
        self.screen.blit(rotated, rotated_rect)

        pygame.display.flip()

    def Stop(self):
        pygame.quit()

