from enum import Enum, auto
from queue import Queue
from typing import Iterable
import threading
from contextlib import contextmanager
from dataclasses import replace
import os

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame

from .constants import ASSET_DIR, CmdEvent, TileState, TileType, TurtlePose, Settings, DimType

BG_COLOR = pygame.Color("white")
WINDOW_TITLE = "TurtleBot"
TILE_SHEET = ASSET_DIR / "images" / "CC_Tileset.webp"
TILE_SHEET_CELL_SIZE = 32
TURTLE_IMAGE = ASSET_DIR / "images" / "turtle.png"
BUTTON_COLOR = pygame.Color("gray")
BUTTON_BORDER_COLOR = pygame.Color("white")
TEXT_COLOR = pygame.Color("white")
FOG_COLOR = pygame.Color(0, 0, 0, 100)


TILE_SHEET_OFFSETS = {
    TileType.UNKNOWN: (2, 13),
    TileType.EMPTY: (0, 0),
    TileType.BLOCKED: (0, 1),
    TileType.GOAL: (3, 2),
}

class ConnectionState(Enum):
    IDLE = auto()
    CONNECTING = auto()
    CONNECTED = auto()

class GameManager:
    def __init__(self, conf: Settings) -> None:
        self.conf = conf
        self._running = True
        self._map_lock = threading.Lock()
        self._map_lock.acquire_lock()
        self._map_thread = threading.Thread(target=self._game_loop, daemon=True)
        self._map_thread.start()
        self._clock = pygame.time.Clock()
        # Wait for GameMap init to complete
        with self._map_lock:
            pass 

    def _game_loop(self):
        self._map = GameMap(self.conf)
        # Signal init has completed
        self._map_lock.release_lock()
        while self._running:
            self._clock.tick(30)  # Limit to 30fps
            with self._map_lock:
                self._map.Draw()

    def get_window_events(self) -> Iterable[CmdEvent]:
        while self._map.event_queue.qsize() > 0:
            try:
                yield self._map.event_queue.get_nowait()
            except:
                break

    @contextmanager
    def get_map(self):
        with self._map_lock:
            yield self._map
    
    def get_tile(self, x, y) -> TileState:
        return self._map.tiles[x][y]

    def get_updated_settings(self):
        return self._map.get_updated_settings()

    def stop(self):
        # DON"T CALL STOP WHILE HOLDING MAP
        self._running = False
        self._map_thread.join()
        self._map.Stop()


class GameMap:
    def __init__(self, conf: Settings) -> None:
        pygame.init()
        pygame.display.set_caption(WINDOW_TITLE)

        self.event_queue: Queue[CmdEvent] = Queue()

        self.conf = conf
        num_map_tiles=conf.MAP_SIZE_TILES
        tile_size_pixels=conf.TILE_SIZE_PIXELS

        self.tile_size = tile_size_pixels
        self.map_width = self.tile_size * num_map_tiles[0]
        self.map_height = self.tile_size * num_map_tiles[1]
        self.font = pygame.font.SysFont(None, 36)

        self.tiles: list[list[TileState]] = []
        for _ in range(num_map_tiles[0]):
            col = [TileState(TileType.EMPTY) for _ in range(num_map_tiles[1])]
            self.tiles.append(col)

        # Extra tile is for buttons
        self.screen = pygame.display.set_mode((self.map_width, self.map_height + tile_size_pixels))

        self.turtle_pose = TurtlePose(
            conf.START_TILE[0] + 0.5,
            conf.START_TILE[1] + 0.5,
            conf.START_THETA,
        )
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
        self.fog_surface.fill(FOG_COLOR)

        # Button setup
        self.button_rect = pygame.Rect(10, self.map_height + 10, 120, self.tile_size - 20)
        self.connected_state = ConnectionState.IDLE
        self.frame_count = 0
        
        # Drag and drop state
        self.dragging = None  # None, 'turtle', or 'goal'
        self.drag_offset = (0, 0)

        self.tiles[conf.GOAL_TILE[0]][conf.GOAL_TILE[1]] = TileState(TileType.GOAL)

        # Set tiles to match alphabet mat
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        for x, col_tiles in enumerate(self.tiles):
            for y, t in enumerate(col_tiles):
                i = (
                    x
                    + (conf.MAP_SIZE_TILES[1] - y - 1)
                    * conf.MAP_SIZE_TILES[0]
                )
                self.tiles[x][y] = replace(t, text=letters[i])


    def set_all_tiles_unobserved(self):
        for x, col_tiles in enumerate(self.tiles):
            for y, t in enumerate(col_tiles):
                self.tiles[x][y] = replace(t, observed=False)


    def set_observed_tile(self, x: int, y: int, tile: TileType):
        if self.tiles[x][y].type != TileType.GOAL:
            self.tiles[x][y] = replace(self.tiles[x][y], observed=True, type=tile)
        else:
            self.tiles[x][y] = replace(self.tiles[x][y], observed=True)

    def _get_window_events(self) -> Iterable[CmdEvent]:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:  # X button or Alt+F4
                yield CmdEvent.QUIT
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if self.button_rect.collidepoint(event.pos):
                    yield CmdEvent.TOGGLE_CONNECT
                elif self.connected_state == ConnectionState.IDLE:
                    turtle_rect = self._get_turtle_rect()
                    goal_rect = self._get_goal_rect()
                    self.drag_offset = event.pos
                    if turtle_rect.collidepoint(event.pos):
                        self.dragging = 'turtle'
                    elif goal_rect.collidepoint(event.pos):
                        self.dragging = 'goal'
            elif event.type == pygame.MOUSEMOTION:
                if self.dragging and self.connected_state == ConnectionState.IDLE:
                    tile_x, tile_y = self._get_tile_from_pos(event.pos)
                    if self.dragging == 'turtle':
                        if self._is_valid_tile(tile_x, tile_y):
                            self.turtle_pose = replace(self.turtle_pose, x=tile_x + 0.5, y=tile_y + 0.5)
                    elif self.dragging == 'goal':
                        if self._is_valid_tile(tile_x, tile_y):
                            old_x, old_y = self._get_tile_from_pos(self.drag_offset)
                            self.drag_offset = event.pos
                            self.tiles[old_x][old_y] = replace(self.tiles[old_x][old_y], type=TileType.EMPTY)
                            self.tiles[tile_x][tile_y] = replace(self.tiles[tile_x][tile_y], type=TileType.GOAL)
            elif event.type == pygame.MOUSEBUTTONUP:
                # Rotate turtle if clicked and not dragged.
                if self.dragging == 'turtle':
                    if abs(event.pos[0] - self.drag_offset[0] <2) and abs(event.pos[1] - self.drag_offset[1] <2):
                        self.turtle_pose = replace(self.turtle_pose, theta=(self.turtle_pose.theta + 90) % 360)
                self.dragging = None
            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_RIGHT:
                    yield CmdEvent.RIGHT
                elif event.key == pygame.K_LEFT:
                    yield CmdEvent.LEFT
                elif event.key == pygame.K_UP:
                    yield CmdEvent.UP
                elif event.key == pygame.K_ESCAPE:
                    yield CmdEvent.QUIT

    def _get_turtle_rect(self) -> pygame.Rect:
        rotated = pygame.transform.rotate(self.turtle_frame, self.turtle_pose.theta)
        rotated_rect = rotated.get_rect()
        y = int(self.map_height - self.turtle_pose.y * self.tile_size)
        x = int(self.turtle_pose.x * self.tile_size)
        rotated_rect.center = (x, y)
        return rotated_rect

    def _get_goal_tile(self) -> DimType:
        for x, col_tiles in enumerate(self.tiles):
            for y, t in enumerate(col_tiles):
                if t.type == TileType.GOAL:
                    return x, y
        raise RuntimeError('No Goal Tile Set')

    def _get_goal_rect(self) -> pygame.Rect:
        x, y = self._get_goal_tile()
        goal_x = self.tile_size * x + self.tile_size // 2
        goal_y = self.map_height - self.tile_size * (y + 1) + self.tile_size // 2
        return pygame.Rect(goal_x - self.tile_size // 2, goal_y - self.tile_size // 2, self.tile_size, self.tile_size)

    def _get_tile_from_pos(self, pos: tuple) -> tuple:
        x = pos[0] // self.tile_size
        y = (self.map_height - pos[1]) // self.tile_size
        return (int(x), int(y))

    def _is_valid_tile(self, x: int, y: int) -> bool:
        num_x = len(self.tiles)
        num_y = len(self.tiles[0]) if self.tiles else 0
        return 0 <= x < num_x and 0 <= y < num_y

    def set_connection_state(self, new_state: ConnectionState):
        self.connected_state = new_state

    def get_updated_settings(self) -> Settings:
        return replace(self.conf,
                       START_TILE=(int(self.turtle_pose.x), int(self.turtle_pose.y)),
                       START_THETA=self.turtle_pose.theta,
                       GOAL_TILE=self._get_goal_tile())

    def Draw(self):
        for event in self._get_window_events():
            self.event_queue.put_nowait(event)

        self.screen.fill(BG_COLOR)

        for c, col_tiles in enumerate(self.tiles):
            for r, t in enumerate(col_tiles):
                surf = self.tile_map[t.type]
                x = self.tile_size * c
                y = self.map_height - self.tile_size * (r + 1)
                self.screen.blit(surf, (x, y), (0, 0, self.tile_size, self.tile_size))
                text_surface = self.font.render(t.text, True, TEXT_COLOR)
                rect = text_surface.get_rect(center=(x + self.tile_size/2.0, y+ self.tile_size/2.0))
                self.screen.blit(text_surface, rect)
                if not t.observed:
                    self.screen.blit(
                        self.fog_surface, (x, y), (0, 0, self.tile_size, self.tile_size)
                    )

        turtle_rect = self._get_turtle_rect()
        rotated = pygame.transform.rotate(self.turtle_frame, self.turtle_pose.theta)
        self.screen.blit(rotated, turtle_rect)

        # Draw button
        self.frame_count += 1
        dot_animation = (self.frame_count // 15) % 4  # Cycle through 0-3 every 15 frames
        
        button_str = {
            ConnectionState.IDLE: ('Connect', TEXT_COLOR),
            ConnectionState.CONNECTING: (f'Connecting{"." * dot_animation}', FOG_COLOR),
            ConnectionState.CONNECTED: ('Disconnect', TEXT_COLOR),
        }[self.connected_state]
        
        button_text = self.font.render(button_str[0], True, button_str[1])
        text_rect = button_text.get_rect()
        
        # Resize button rect based on text size with padding
        padding = 10
        self.button_rect.width = text_rect.width + padding * 2
        self.button_rect.height = text_rect.height + padding * 2
        
        pygame.draw.rect(self.screen, BUTTON_COLOR, self.button_rect)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self.button_rect, 2)
        
        text_rect.center = self.button_rect.center
        self.screen.blit(button_text, text_rect)

        pygame.display.flip()

    def Stop(self):
        pygame.quit()
