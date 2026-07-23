"""BMP -> Spectrum format conversions: full-screen bitmaps, sprite sheets, and fonts.

Three converters live here, but they split along a real seam, not an arbitrary one:

``convert_bitmap`` targets the *hardware screen file* -- a full 256x192 image, which
the real Spectrum only knows how to display as an interleaved bitmap plane plus one
8x8-cell attribute (a shared ink/paper/bright colour per cell, the source of the
platform's famous "colour clash"). That hardware quirk is why this converter has to
choose two colours per cell and warn when a cell can't be represented losslessly.

``convert_sprite_sheet``/``convert_sprite_sequence`` target *standalone* 1bpp data --
a sprite sitting in ordinary RAM has no attribute cells and no interleaving; it is
whatever shape the game's own draw routine expects. Both converge on one
:class:`~zxemu_core.assets.manifest.FrameSequence` shape (see that module for why),
through a single packer, so "one sheet sliced into frames" and "N individual frame
images" are just two ways of arriving at identical output.

``convert_font`` is a thin, friendlier wrapper over the sheet slicer: fonts are almost
always a regular, gap-free 8x8 grid, so unlike a general sprite sheet its layout can be
inferred rather than demanded.
"""

from __future__ import annotations

from dataclasses import dataclass

from zxemu_core.assets.bmp import BmpImage
from zxemu_core.assets.manifest import FrameSequence
from zxemu_core.assets.palette import (
    BRIGHT_RGB,
    NORMAL_RGB,
    SCREEN_ATTR_BYTES,
    SCREEN_BITMAP_BYTES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    attribute_offset,
    bitmap_offset,
    nearest_index,
)

# --------------------------------------------------------------------------------
# Full-screen bitmap
# --------------------------------------------------------------------------------


@dataclass
class ClashWarning:
    """One 8x8 cell that needed more than two colours -- lossy, but never fatal."""

    cell_x: int
    cell_y: int
    color_count: int

    def __str__(self) -> str:
        return f"cell ({self.cell_x}, {self.cell_y}) has {self.color_count} colours, only 2 fit"


def convert_bitmap(image: BmpImage) -> tuple[bytes, list[ClashWarning]]:
    """Full-screen 256x192 BMP -> (6144-byte bitmap + 768-byte attributes), clash warnings.

    The output is laid out exactly as the hardware screen file is (interleaved
    thirds -- see ``palette.bitmap_offset``), so it can be ``incbin``'d straight into
    display memory ($4000) or copied there at runtime.
    """
    if image.width != SCREEN_WIDTH or image.height != SCREEN_HEIGHT:
        raise ValueError(
            f"bitmap asset must be exactly {SCREEN_WIDTH}x{SCREEN_HEIGHT}, got {image.width}x{image.height}"
        )

    bitmap = bytearray(SCREEN_BITMAP_BYTES)
    attrs = bytearray(SCREEN_ATTR_BYTES)
    warnings: list[ClashWarning] = []

    for cell_y in range(SCREEN_HEIGHT // 8):
        for cell_x in range(SCREEN_WIDTH // 8):
            cell_pixels = [
                image.get_pixel(cell_x * 8 + dx, cell_y * 8 + dy) for dy in range(8) for dx in range(8)
            ]
            attr_byte, ink_rgb, paper_rgb, clash_count = _quantize_cell(cell_pixels)
            if clash_count > 2:
                warnings.append(ClashWarning(cell_x, cell_y, clash_count))
            attrs[attribute_offset(cell_y * 8, cell_x)] = attr_byte

            for dy in range(8):
                y = cell_y * 8 + dy
                byte = 0
                for dx in range(8):
                    rgb = image.get_pixel(cell_x * 8 + dx, y)
                    is_ink = _sq_dist(rgb, ink_rgb) <= _sq_dist(rgb, paper_rgb)
                    if is_ink:
                        byte |= 0x80 >> dx
                bitmap[bitmap_offset(y, cell_x)] = byte

    return bytes(bitmap) + bytes(attrs), warnings


def _sq_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _dominant_two(pixels: list[tuple[int, int, int]]) -> tuple[tuple[int, int, int], tuple[int, int, int], int]:
    """The two most frequent colours in ``pixels`` (paper = most frequent), and how many distinct colours existed."""
    counts: dict[tuple[int, int, int], int] = {}
    for rgb in pixels:
        counts[rgb] = counts.get(rgb, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    paper = ranked[0][0]
    ink = ranked[1][0] if len(ranked) > 1 else ranked[0][0]
    return ink, paper, len(ranked)


def _best_attr(ink_rgb, paper_rgb) -> tuple[int, int, int]:
    """Choose bright vs normal palette, whichever represents (ink, paper) with less error."""
    normal_ink, normal_ink_err = nearest_index(ink_rgb, bright=False)
    normal_paper, normal_paper_err = nearest_index(paper_rgb, bright=False)
    bright_ink, bright_ink_err = nearest_index(ink_rgb, bright=True)
    bright_paper, bright_paper_err = nearest_index(paper_rgb, bright=True)
    if (bright_ink_err + bright_paper_err) < (normal_ink_err + normal_paper_err):
        return 1, bright_ink, bright_paper
    return 0, normal_ink, normal_paper


def _quantize_cell(cell_pixels: list[tuple[int, int, int]]) -> tuple[int, tuple, tuple, int]:
    """One 8x8 cell's pixels -> (attr_byte, ink_rgb, paper_rgb, distinct_colour_count).

    Shared by the full-screen ``bitmap`` path and attributed sprite frames -- the
    colour-clash quantization is identical either way; only the resulting pixel
    plane's *byte layout* differs (interleaved for the live screen, plain row-major
    for standalone sprite data), so that part stays separate in each caller.
    """
    ink_rgb, paper_rgb, clash_count = _dominant_two(cell_pixels)
    bright, ink_index, paper_index = _best_attr(ink_rgb, paper_rgb)
    attr_byte = (bright << 6) | (paper_index << 3) | ink_index
    return attr_byte, ink_rgb, paper_rgb, clash_count


# --------------------------------------------------------------------------------
# Sprite sheets / sequences / fonts -> FrameSequence
# --------------------------------------------------------------------------------

_LUMA_INK_THRESHOLD = 128  # a pixel darker than this counts as "ink" (foreground)


def _luma(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return (299 * r + 587 * g + 114 * b) // 1000


def _frame_origins(layout: dict, frame_width: int, frame_height: int, image: BmpImage) -> list[tuple[int, int]]:
    if "grid" in layout:
        cols, rows = layout["grid"]["cols"], layout["grid"]["rows"]
        origins = [(col * frame_width, row * frame_height) for row in range(rows) for col in range(cols)]
    elif "strip" in layout:
        axis, count = layout["strip"]["axis"], layout["strip"]["count"]
        if axis == "horizontal":
            origins = [(i * frame_width, 0) for i in range(count)]
        elif axis == "vertical":
            origins = [(0, i * frame_height) for i in range(count)]
        else:
            raise ValueError(f"strip axis must be 'horizontal' or 'vertical', got {axis!r}")
    else:
        raise ValueError("layout must have a 'grid' or 'strip' key")

    for ox, oy in origins:
        if ox + frame_width > image.width or oy + frame_height > image.height:
            raise ValueError(
                f"frame at ({ox},{oy}) size {frame_width}x{frame_height} doesn't fit "
                f"in a {image.width}x{image.height} image"
            )
    return origins


def _pack_plane(image: BmpImage, ox: int, oy: int, frame_width: int, frame_height: int, is_set) -> bytes:
    """Pack one 1bpp plane for the frame at (ox, oy): ``is_set(rgb) -> bool`` decides each bit."""
    bytes_per_row = frame_width // 8
    plane = bytearray(bytes_per_row * frame_height)
    for row in range(frame_height):
        y = oy + row
        for byte_col in range(bytes_per_row):
            byte = 0
            for bit in range(8):
                x = ox + byte_col * 8 + bit
                if is_set(image.get_pixel(x, y)):
                    byte |= 0x80 >> bit
            plane[row * bytes_per_row + byte_col] = byte
    return bytes(plane)


def _pack_frame(image: BmpImage, ox: int, oy: int, frame_width: int, frame_height: int, mask_color) -> bytes:
    pixel_plane = _pack_plane(
        image, ox, oy, frame_width, frame_height, lambda rgb: _luma(rgb) < _LUMA_INK_THRESHOLD
    )
    if mask_color is None:
        return pixel_plane
    mask_plane = _pack_plane(image, ox, oy, frame_width, frame_height, lambda rgb: rgb != mask_color)
    return pixel_plane + mask_plane


def _pack_frame_attrs(
    image: BmpImage, ox: int, oy: int, frame_width: int, frame_height: int
) -> tuple[bytes, bytes, list[ClashWarning]]:
    """A frame's (pixel plane, attribute plane, clash warnings) -- real per-cell colour, not one global ink/paper.

    Same colour-clash quantization as ``convert_bitmap`` (via ``_quantize_cell``), but
    the pixel plane is plain row-major here, matching every other sprite's layout --
    only the *live screen* interleaves.
    """
    bytes_per_row = frame_width // 8
    attr_cols, attr_rows = frame_width // 8, frame_height // 8
    pixel_plane = bytearray(bytes_per_row * frame_height)
    attr_plane = bytearray(attr_cols * attr_rows)
    warnings: list[ClashWarning] = []

    for cell_y in range(attr_rows):
        for cell_x in range(attr_cols):
            cx, cy = ox + cell_x * 8, oy + cell_y * 8
            cell_pixels = [image.get_pixel(cx + dx, cy + dy) for dy in range(8) for dx in range(8)]
            attr_byte, ink_rgb, paper_rgb, clash_count = _quantize_cell(cell_pixels)
            if clash_count > 2:
                warnings.append(ClashWarning(cell_x, cell_y, clash_count))
            attr_plane[cell_y * attr_cols + cell_x] = attr_byte

            for dy in range(8):
                byte = 0
                for dx in range(8):
                    rgb = image.get_pixel(cx + dx, cy + dy)
                    if _sq_dist(rgb, ink_rgb) <= _sq_dist(rgb, paper_rgb):
                        byte |= 0x80 >> dx
                pixel_plane[(cell_y * 8 + dy) * bytes_per_row + cell_x] = byte

    return bytes(pixel_plane), bytes(attr_plane), warnings


def _assemble_attrs_data(
    frames: list[tuple[BmpImage, int, int]], frame_width: int, frame_height: int,
    generate_mask: bool, mask_color, warnings: list[ClashWarning] | None,
) -> bytes:
    """Pack every ``(image, ox, oy)`` frame's (pixel + optional mask + attribute) planes back to back.

    Shared by ``convert_sprite_sheet`` (all frames from one image, different origins)
    and ``convert_sprite_sequence`` (each frame its own image, origin always (0, 0)).
    """
    parts = []
    for image, ox, oy in frames:
        pixel_bytes, attr_bytes, frame_warnings = _pack_frame_attrs(image, ox, oy, frame_width, frame_height)
        if warnings is not None:
            warnings.extend(frame_warnings)
        mask_bytes = (
            _pack_plane(image, ox, oy, frame_width, frame_height, lambda rgb: rgb != mask_color)
            if generate_mask
            else b""
        )
        parts.append(pixel_bytes + mask_bytes + attr_bytes)
    return b"".join(parts)


def convert_sprite_sheet(
    image: BmpImage,
    frame_width: int,
    frame_height: int,
    layout: dict,
    generate_mask: bool = False,
    mask_color: tuple[int, int, int] | None = None,
    generate_attrs: bool = False,
    warnings: list[ClashWarning] | None = None,
) -> FrameSequence:
    """A grid or strip of equal-sized frames in one BMP -> a :class:`FrameSequence`.

    ``generate_attrs`` gives each frame real per-8x8-cell colour (ink/paper/bright)
    instead of being plotted in one colour chosen at draw time -- the same
    colour-clash quantization ``bitmap`` uses for the full screen, scoped to each
    frame. Requires ``frame_height`` to also be a multiple of 8. Clash warnings (a
    cell needing more than 2 colours) are appended to ``warnings`` if given.
    """
    if frame_width % 8 != 0:
        raise ValueError(f"frame_width must be a multiple of 8, got {frame_width}")
    if generate_attrs and frame_height % 8 != 0:
        raise ValueError(f"frame_height must be a multiple of 8 for attributes, got {frame_height}")
    origins = _frame_origins(layout, frame_width, frame_height, image)
    if generate_mask and mask_color is None:
        raise ValueError("generate_mask requires a mask_color")

    if generate_attrs:
        frames = [(image, ox, oy) for ox, oy in origins]
        data = _assemble_attrs_data(frames, frame_width, frame_height, generate_mask, mask_color, warnings)
        return FrameSequence(frame_width, frame_height, len(origins), generate_mask, data, has_attrs=True)

    color = mask_color if generate_mask else None
    data = b"".join(_pack_frame(image, ox, oy, frame_width, frame_height, color) for ox, oy in origins)
    return FrameSequence(frame_width, frame_height, len(origins), generate_mask, data)


def convert_sprite_sequence(
    images: list[BmpImage],
    generate_mask: bool = False,
    mask_color: tuple[int, int, int] | None = None,
    generate_attrs: bool = False,
    warnings: list[ClashWarning] | None = None,
) -> FrameSequence:
    """An ordered list of same-sized whole-image frames -> a :class:`FrameSequence`.

    Unlike ``convert_sprite_sheet``, there is no slicing: each image *is* one frame, so
    dimensions come from the images themselves (and must all agree) rather than being
    typed in. ``generate_attrs`` works the same as on ``convert_sprite_sheet``.
    """
    if not images:
        raise ValueError("sprite_sequence needs at least one image")
    frame_width, frame_height = images[0].width, images[0].height
    if frame_width % 8 != 0:
        raise ValueError(f"frame width must be a multiple of 8, got {frame_width} (from the first image)")
    if generate_attrs and frame_height % 8 != 0:
        raise ValueError(f"frame_height must be a multiple of 8 for attributes, got {frame_height} (from the first image)")
    for i, image in enumerate(images):
        if image.width != frame_width or image.height != frame_height:
            raise ValueError(
                f"frame {i} is {image.width}x{image.height}, expected {frame_width}x{frame_height} "
                "(all frames in a sprite_sequence must be the same size)"
            )
    if generate_mask and mask_color is None:
        raise ValueError("generate_mask requires a mask_color")

    if generate_attrs:
        frames = [(image, 0, 0) for image in images]
        data = _assemble_attrs_data(frames, frame_width, frame_height, generate_mask, mask_color, warnings)
        return FrameSequence(frame_width, frame_height, len(images), generate_mask, data, has_attrs=True)

    color = mask_color if generate_mask else None
    data = b"".join(_pack_frame(image, 0, 0, frame_width, frame_height, color) for image in images)
    return FrameSequence(frame_width, frame_height, len(images), generate_mask, data)


def convert_font(
    image: BmpImage,
    frame_width: int = 8,
    frame_height: int = 8,
    layout: dict | None = None,
) -> FrameSequence:
    """A BMP charset grid -> a glyph :class:`FrameSequence`. No mask: glyphs are OR/XOR-plotted.

    Unlike a general sprite sheet, a font's layout defaults to "however many
    ``frame_width``x``frame_height`` cells evenly tile the image" -- fonts are
    conventionally a dense, gap-free grid, so this is an unambiguous default rather
    than a guess.
    """
    if layout is None:
        if image.width % frame_width or image.height % frame_height:
            raise ValueError(
                f"image {image.width}x{image.height} isn't evenly divisible into "
                f"{frame_width}x{frame_height} glyphs; pass an explicit layout"
            )
        layout = {"grid": {"cols": image.width // frame_width, "rows": image.height // frame_height}}
    return convert_sprite_sheet(image, frame_width, frame_height, layout, generate_mask=False)
