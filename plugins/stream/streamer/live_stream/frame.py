"""
The picture's sizes, worked out once for an ffmpeg command: the whole picture's, each square's, the borders', and the
stream's own colour.
"""
from __future__ import annotations

from dataclasses import dataclass

from .constants import BORDER_WIDTH, DEFAULT_BACKGROUND, DEFAULT_BORDER, DEFAULT_RESOLUTION, FPS, RESOLUTIONS


@dataclass(frozen=True)
class Frame:
    width: int  # the whole picture, px
    height: int
    kbps: int  # the video's bitrate
    tw: int  # each square, px (even)
    th: int
    scale: float  # the words and borders grow with the picture: 1 on the 720-high picture
    back: str  # the stream's own colour, RRGGBB
    border_color: str  # RRGGBB

    @classmethod
    def of(cls, resolution: str, cols: int, rows: int, background: str | None, border_color: str | None) -> "Frame":
        width, height, kbps = RESOLUTIONS.get(resolution, RESOLUTIONS[DEFAULT_RESOLUTION])
        return cls(width=width, height=height, kbps=kbps, tw=(width // cols) // 2 * 2, th=(height // rows) // 2 * 2,
                   scale=height / 720, back=(background or DEFAULT_BACKGROUND).lstrip("#"),
                   border_color=(border_color or DEFAULT_BORDER).lstrip("#"))

    def px(self, v: float) -> int:
        """`v` px of the 720-high picture, on this one (at least 1)."""
        return max(1, round(v * self.scale))

    @property
    def edge(self) -> int:
        """The border round each square, px."""
        return self.px(BORDER_WIDTH)

    @property
    def border(self) -> str:
        """The filter that draws a square's border."""
        return f"drawbox=x=0:y=0:w=iw:h=ih:color=0x{self.border_color}:t={self.edge}"

    @property
    def full_size(self) -> str:
        """The filter that fits a picture to the whole stream, the stream's colour round it."""
        w, h = self.width, self.height
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x{self.back},setsar=1"

    def plain(self, colour: str | None = None) -> str:
        """A square of one colour (RRGGBB; None: the stream's), as a source filter."""
        return f"color=c=0x{colour or self.back}:s={self.tw}x{self.th}:r={FPS},setsar=1"
