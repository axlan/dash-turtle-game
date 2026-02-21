from enum import Enum, auto
from typing import Iterable
from dataclasses import dataclass

import pygame


from .constants import ASSET_DIR, CmdEvent

BG_COLOR = pygame.Color("white")
WINDOW_TITLE = "TurtleBot"
TILE_SHEET = ASSET_DIR / "images" / "CC_Tileset.webp"
TILE_SHEET_CELL_SIZE = 32
TURTLE_IMAGE = ASSET_DIR / "images" / "turtle.png"

DimType = tuple[int, int]

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


@dataclass(frozen=False)
class TileState:
    type: TileType
    observed: bool = False
    text: str = ''


TILE_SHEET_OFFSETS = {
    TileType.UNKNOWN: (2, 13),
    TileType.EMPTY: (0, 0),
    TileType.BLOCKED: (0, 1),
    TileType.GOAL: (3, 2),
}


class GameMap:
    def __init__(self, num_map_tiles: DimType, tile_size_pixels: int) -> None:
        pygame.init()
        pygame.display.set_caption(WINDOW_TITLE)

        self.tile_size = tile_size_pixels
        self.width = self.tile_size * num_map_tiles[0]
        self.height = self.tile_size * num_map_tiles[1]
        self.font = pygame.font.SysFont(None, 36)

        self.tiles: list[list[TileState]] = []
        for _ in range(num_map_tiles[0]):
            col = [TileState(TileType.EMPTY) for _ in range(num_map_tiles[1])]
            self.tiles.append(col)

        self.screen = pygame.display.set_mode((self.width, self.height))

        self.turtle_pose = TurtlePose()
        self.turtle_frame = pygame.image.load(TURTLE_IMAGE).convert_alpha()
        self.turtle_frame = pygame.transform.scale(
            self.turtle_frame, (self.tile_size, self.tile_size)
        )

        sheet = pygame.image.load(TILE_SHEET).convert_alpha()
        self.tile_map: dict[TileType, pygame.Surface] = {}

        fw = TILE_SHEET_CELL_SIZE
        fh = TILE_SHEET_CELL_SIZE
        for t, index in TILE_SHEET_OFFSETS.items():
            frame_surf = pygame.Surface((fw, fh), pygame.SRCALPHA)
            frame_surf.blit(sheet, (0, 0), (index[0] * fw, index[1] * fh, fw, fh))
            self.tile_map[t] = pygame.transform.scale(
                frame_surf, (self.tile_size, self.tile_size)
            )

        self.fog_surface = pygame.Surface((self.tile_size, self.tile_size), pygame.SRCALPHA)
        self.fog_surface.fill((0, 0, 0, 100))  # Black with ~40% opacity

    def GetAllTiles(self) -> Iterable[TileState]:
        for tiles in self.tiles:
            for t in tiles: 
                yield t

    def GetWindowEvents(self) -> Iterable[CmdEvent]:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:  # X button or Alt+F4
                yield CmdEvent.QUIT
            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_RIGHT:
                    yield CmdEvent.RIGHT
                elif event.key == pygame.K_LEFT:
                    yield CmdEvent.LEFT
                elif event.key == pygame.K_UP:
                    yield CmdEvent.UP
                elif event.key == pygame.K_ESCAPE:
                    yield CmdEvent.QUIT

    def Draw(self):
        self.screen.fill(BG_COLOR)

        for c, col_tiles in enumerate(self.tiles):
            for r, t in enumerate(col_tiles):
                surf = self.tile_map[t.type]
                x = self.tile_size * c
                y = self.height - self.tile_size * (r + 1)
                self.screen.blit(surf, (x, y), (0, 0, self.tile_size, self.tile_size))
                text_surface = self.font.render(t.text, True, (255, 255, 255))
                rect = text_surface.get_rect(center=(x + self.tile_size/2.0, y+ self.tile_size/2.0))
                self.screen.blit(text_surface, rect)
                if not t.observed:
                    self.screen.blit(
                        self.fog_surface, (x, y), (0, 0, self.tile_size, self.tile_size)
                    )

        rotated = pygame.transform.rotate(self.turtle_frame, self.turtle_pose.theta)
        rotated_rect = rotated.get_rect()
        # handle y starting at top and going down
        # Convert turtle position to pixels
        y = int(self.height - self.turtle_pose.y * self.tile_size)
        x = int(self.turtle_pose.x * self.tile_size)
        rotated_rect.center = (x, y)
        self.screen.blit(rotated, rotated_rect)

        pygame.display.flip()

    def Stop(self):
        pygame.quit()
