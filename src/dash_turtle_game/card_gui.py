import pygame
from enum import Enum, auto

from .constants import ASSET_DIR, CmdEvent

# --- Example card type enum (customize as needed) ---
class CardType(Enum):
    LEFT = auto()
    UP = auto()
    RIGHT = auto()


def event_to_card(cmd_event: CmdEvent) -> CardType:
    return {
        CmdEvent.LEFT: CardType.LEFT,
        CmdEvent.UP: CardType.UP,
        CmdEvent.RIGHT: CardType.RIGHT,
    }.get(cmd_event, CardType.LEFT)


def card_to_event(cmd_event: CardType) -> CmdEvent:
    return {
        CardType.LEFT: CmdEvent.LEFT,
        CardType.UP: CmdEvent.UP,
        CardType.RIGHT: CmdEvent.RIGHT,
    }.get(cmd_event, CmdEvent.NONE)


ARROW_IMAGE = ASSET_DIR / "images" / "arrow.png"


def _recolor_surface(surface: pygame.Surface, color: pygame.Color) -> pygame.Surface:
    colored = surface.copy()
    pixels = pygame.surfarray.pixels3d(colored)
    alpha = pygame.surfarray.pixels_alpha(colored)

    # Find white pixels (all RGB channels == 255)
    white_mask = (pixels[:, :, 0] == 255) & \
                (pixels[:, :, 1] == 255) & \
                (pixels[:, :, 2] == 255)

    pixels[white_mask] = color[:3]

    del pixels, alpha  # unlock surface
    return colored

# --- Card images registry: map CardType -> pygame.Surface ---
# Populate this with your actual images. Example uses colored placeholders.
def load_card_images(card_w, card_h):
    images = {}

    arrow_base = pygame.image.load(ARROW_IMAGE).convert_alpha()
    ratio = arrow_base.get_width() / arrow_base.get_height()
    h = card_h // 4
    w = int(h * ratio)
    arrow_base = pygame.transform.scale(arrow_base, (w, h))
    
    arrows = {
        CardType.LEFT: _recolor_surface(arrow_base, pygame.Color("green")),
        CardType.UP: _recolor_surface(pygame.transform.rotate(arrow_base, -90), pygame.Color("blue")),
        CardType.RIGHT: _recolor_surface(pygame.transform.rotate(arrow_base, 180), pygame.Color("red")),
    }

    for card_type, arrow in arrows.items():
        surf = pygame.Surface((card_w - 16, card_h - 16), pygame.SRCALPHA)
        surf.blit(arrow, arrow.get_rect(center=surf.get_rect().center))
        images[card_type] = surf
    return images


class CardQueueWidget:
    """
    A Pygame widget that displays a scrollable queue of cards.

    Parameters
    ----------
    x, y        : Top-left position on screen
    width       : Total widget width in pixels
    height      : Total widget height in pixels
    card_width  : Width of each card in pixels  (default: height - 10)
    card_gap    : Gap between cards in pixels   (default: 6)
    bg_color    : Widget background color
    border_color: Default card border color
    active_color: Border color for the active card
    """

    def __init__(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        card_width: int | None = None,
        card_gap: int = 6,
        bg_color=(30, 30, 40),
        border_color=(200, 200, 200),
        active_color=(220, 50, 50),
        border_width: int = 3,
        corner_radius: int = 6,
    ):
        self.rect = pygame.Rect(x, y, width, height)
        self.card_h = height - 12  # cards fill height with small padding
        self.card_w = card_width if card_width else self.card_h - 10
        self.card_gap = card_gap
        self.bg_color = bg_color
        self.border_color = border_color
        self.active_color = active_color
        self.border_width = border_width
        self.corner_radius = corner_radius

        self.cards: list[CardType] = []   # ordered list of card types
        self.scroll_offset: int = 0       # index of first visible card
        self.active_index: int = -1       # index of highlighted card (-1 = none)

        self._images: dict = load_card_images(self.card_w, self.card_h)
        self._font = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def set_images(self, images: dict):
        """Provide a dict mapping CardType -> pygame.Surface."""
        self._images = images

    # ------------------------------------------------------------------
    # Card management
    # ------------------------------------------------------------------

    def add_card(self, card_type: CardType):
        """Append a card to the queue."""
        self.cards.append(card_type)

    def remove_card(self, index: int):
        """Remove card at the given index."""
        if 0 <= index < len(self.cards):
            self.cards.pop(index)
            if self.active_index >= len(self.cards):
                self.active_index = len(self.cards) - 1
            self.scroll_offset = min(self.scroll_offset, max(0, len(self.cards) - self._visible_count()))

    def set_cards(self, card_types: list):
        """Replace the entire card list."""
        self.cards = list(card_types)
        self.scroll_offset = 0
        self.active_index = -1

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------

    def scroll_left(self, steps: int = 1):
        """Scroll the view left (show earlier cards)."""
        self.scroll_offset = max(0, self.scroll_offset - steps)

    def scroll_right(self, steps: int = 1):
        """Scroll the view right (show later cards)."""
        max_offset = max(0, len(self.cards) - self._visible_count())
        self.scroll_offset = min(max_offset, self.scroll_offset + steps)

    def scroll_to(self, index: int):
        """Scroll so that card at index is visible."""
        index = max(0, min(index, len(self.cards) - 1))
        visible = self._visible_count()
        if index < self.scroll_offset:
            self.scroll_offset = index
        elif index >= self.scroll_offset + visible:
            self.scroll_offset = index - visible + 1

    # ------------------------------------------------------------------
    # Active card
    # ------------------------------------------------------------------

    def set_active(self, index: int):
        """Mark card at index as active (highlighted in red)."""
        self.active_index = index
        self.scroll_to(index)

    def clear_active(self):
        self.active_index = -1

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface):
        # Background
        pygame.draw.rect(surface, self.bg_color, self.rect, border_radius=self.corner_radius)

        # Clip drawing to widget bounds
        old_clip = surface.get_clip()
        surface.set_clip(self.rect)

        visible_count = self._visible_count()
        start = self.scroll_offset
        end = min(start + visible_count + 1, len(self.cards))  # +1 for partial card peek

        for i, card_idx in enumerate(range(start, end)):
            card_type = self.cards[card_idx]
            cx = self.rect.x + 6 + i * (self.card_w + self.card_gap)
            cy = self.rect.y + 6

            card_rect = pygame.Rect(cx, cy, self.card_w, self.card_h)

            # Card background
            pygame.draw.rect(surface, (50, 50, 65), card_rect, border_radius=4)

            # Card image
            img = self._images.get(card_type)
            if img:
                img_rect = img.get_rect(center=card_rect.center)
                surface.blit(img, img_rect)

            # Card border (red if active)
            is_active = (card_idx == self.active_index)
            color = self.active_color if is_active else self.border_color
            pygame.draw.rect(surface, color, card_rect, self.border_width, border_radius=4)

        # Scroll indicators
        self._draw_scroll_arrows(surface)

        surface.set_clip(old_clip)

        # Outer widget border
        pygame.draw.rect(surface, (80, 80, 100), self.rect, 2, border_radius=self.corner_radius)

    def _draw_scroll_arrows(self, surface):
        arrow_color = pygame.Color("orange")
        mid_y = self.rect.centery

        if self.scroll_offset > 0:
            # Left arrow
            ax = self.rect.x + 4
            pts = [(ax + 16, mid_y - 14), (ax + 16, mid_y + 14), (ax, mid_y)]
            pygame.draw.polygon(surface, arrow_color, pts)

        if self.scroll_offset + self._visible_count() < len(self.cards):
            # Right arrow
            ax = self.rect.right - 20
            pts = [(ax, mid_y - 14), (ax, mid_y + 14), (ax + 16, mid_y)]
            pygame.draw.polygon(surface, arrow_color, pts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _visible_count(self) -> int:
        """How many full cards fit in the widget width."""
        usable = self.rect.width - 12
        return max(1, usable // (self.card_w + self.card_gap))


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    pygame.init()
    screen = pygame.display.set_mode((700, 200))
    pygame.display.set_caption("CardQueueWidget Demo")
    clock = pygame.time.Clock()

    widget = CardQueueWidget(x=20, y=40, width=660, height=120, card_width=80)
    images = load_card_images(widget.card_w, widget.card_h)
    widget.set_images(images)

    # Add some cards
    import random
    for _ in range(12):
        widget.add_card(random.choice(list(CardType)))

    widget.set_active(0)

    font = pygame.font.SysFont("monospace", 13)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RIGHT:
                    widget.scroll_right()
                elif event.key == pygame.K_LEFT:
                    widget.scroll_left()
                elif event.key == pygame.K_d:
                    # Move active card right
                    new_idx = min(widget.active_index + 1, len(widget.cards) - 1)
                    widget.set_active(new_idx)
                elif event.key == pygame.K_a:
                    # Move active card left
                    new_idx = max(widget.active_index - 1, 0)
                    widget.set_active(new_idx)
                elif event.key == pygame.K_SPACE:
                    widget.add_card(random.choice(list(CardType)))
                elif event.key == pygame.K_x:
                    widget.remove_card(widget.active_index)

        screen.fill((20, 20, 30))
        widget.draw(screen)

        hints = font.render(
            "← → scroll  |  A D select  |  SPACE add card  |  X remove active",
            True, (120, 120, 140)
        )
        screen.blit(hints, (20, 170))
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()