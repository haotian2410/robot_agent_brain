"""Deterministic sampling of deployment-registered font outlines."""
import hashlib
import math
from io import BytesIO
from bisect import bisect_right
from pathlib import Path


def text_slots(text, count, font_path):
    try:
        from fontTools.ttLib import TTFont, TTLibError
        from fontTools.pens.basePen import BasePen
    except ImportError as exc:
        raise ValueError("scene_layout_text_requires_fonttools") from exc
    if not text or len(text) > 128 or not 1 <= count <= 1000:
        raise ValueError("scene_layout_text_invalid")
    path = Path(font_path)
    if not path.is_file():
        raise ValueError("scene_layout_font_unavailable")
    try:
        font_bytes = path.read_bytes()
    except OSError as exc:
        raise ValueError("scene_layout_font_unavailable") from exc
    fingerprint = hashlib.sha256(font_bytes).hexdigest()
    segments = []

    class OutlinePen(BasePen):
        def __init__(self, glyphs, offset):
            super().__init__(glyphs)
            self.offset = offset
            self.start = self.last = None

        def _moveTo(self, p):
            self.start = self.last = p

        def _lineTo(self, p):
            a = (self.last[0] + self.offset, self.last[1])
            b = (p[0] + self.offset, p[1])
            if a != b:
                segments.append((a, b))
            if len(segments) > 100000:
                raise ValueError("scene_layout_font_complexity_exceeded")
            self.last = p

        def _qCurveToOne(self, control, end):
            start = self.last
            for i in range(1, 33):
                t = i / 32
                self._lineTo(tuple((1-t)**2 * start[k] + 2*(1-t)*t*control[k] + t*t*end[k] for k in (0, 1)))

        def _curveToOne(self, c1, c2, end):
            start = self.last
            for i in range(1, 33):
                t = i / 32
                self._lineTo(tuple((1-t)**3*start[k] + 3*(1-t)**2*t*c1[k]
                                   + 3*(1-t)*t*t*c2[k] + t**3*end[k] for k in (0, 1)))

        def _closePath(self):
            self._lineTo(self.start)

        def _endPath(self):
            pass

    # Sample exactly the bytes that were fingerprinted, even if deployment
    # replaces the registered file during this request.
    try:
        loaded_font = TTFont(BytesIO(font_bytes), fontNumber=0)
    except (TTLibError, EOFError) as exc:
        raise ValueError("scene_layout_font_invalid") from exc
    with loaded_font as font:
        cmap, glyphs = font.getBestCmap(), font.getGlyphSet()
        offset = 0
        for character in text:
            name = cmap.get(ord(character))
            if name is None:
                raise ValueError("scene_layout_font_glyph_missing: " + character)
            glyphs[name].draw(OutlinePen(glyphs, offset))
            offset += font["hmtx"][name][0]
    if not segments:
        raise ValueError("scene_layout_text_empty_outline")
    low = [min(p[k] for segment in segments for p in segment) for k in (0, 1)]
    high = [max(p[k] for segment in segments for p in segment) for k in (0, 1)]
    scale = max(high[k] - low[k] for k in (0, 1))
    if scale <= 0:
        raise ValueError("scene_layout_text_empty_outline")
    lengths = [0.]
    for a, b in segments:
        lengths.append(lengths[-1] + math.dist(a, b))
    points = []
    # Midpoints avoid duplicating the start/end of closed contours; contour
    # breaks have zero traversal length, never imaginary connecting strokes.
    for i in range(count):
        distance = lengths[-1] * (i + .5) / count
        j = min(bisect_right(lengths, distance)-1, len(segments)-1)
        t = (distance-lengths[j]) / (lengths[j+1]-lengths[j])
        a, b = segments[j]
        points.append(tuple(.5 + .8 * (a[k] + t*(b[k]-a[k]) - (low[k]+high[k])/2) / scale for k in (0, 1)))
    return points, fingerprint
