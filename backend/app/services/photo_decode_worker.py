"""Isolated photo decoder. No app imports, credentials, inherited FDs or environment."""
from __future__ import annotations

import json
from io import BytesIO
import resource
import sys

MEMORY_BYTES = 1024 * 1024 * 1024
CPU_SECONDS = 14
MAX_BYTES = 15 * 1024 * 1024
LONG_EDGE = 4096
FORMATS = {"image/jpeg": {"JPEG", "MPO"}, "image/png": {"PNG"},
           "image/webp": {"WEBP"}, "image/heic": {"HEIF"}, "image/heif": {"HEIF"}}


def main() -> None:
    # Install limits before loading native decoders. macOS rejects memory
    # rlimits; the parent enforces RSS there. Linux uses a hard address limit.
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    from PIL import Image, ImageOps
    from pillow_heif import register_heif_opener
    register_heif_opener(thumbnails=False, decode_threads=1)
    Image.MAX_IMAGE_PIXELS = None  # Resource limits cover panoramas and hostile sizes.
    mime = sys.argv[1]
    source_bytes = sys.stdin.buffer.read(MAX_BYTES + 1)
    if mime not in FORMATS or not source_bytes or len(source_bytes) > MAX_BYTES:
        raise ValueError("Invalid photo")
    with Image.open(BytesIO(source_bytes)) as source:
        if source.format not in FORMATS[mime]:
            raise ValueError("Unexpected format")
        if source.format != "HEIF":
            source.seek(0)  # HEIF opener already selects its declared primary image.
        resized = max(source.size) > LONG_EDGE
        icc = source.info.get("icc_profile")
        had_metadata = bool(source.getexif() or any(source.info.get(k) for k in
                            ("exif", "xmp", "XML:com.adobe.xmp")) or getattr(source, "n_frames", 1) > 1)
        # JPEG draft decoding reduces large panoramas before full pixel allocation.
        source.draft("RGB", (LONG_EDGE, LONG_EDGE))
        source.thumbnail((LONG_EDGE, LONG_EDGE), Image.Resampling.LANCZOS)
        oriented = ImageOps.exif_transpose(source)
        output_mime = "image/jpeg" if mime in ("image/jpeg", "image/heic", "image/heif") else mime
        mode = "RGBA" if output_mime != "image/jpeg" and (
            "A" in oriented.getbands() or "transparency" in oriented.info) else "RGB"
        if output_mime == "image/jpeg" and oriented.mode in ("L", "CMYK"):
            mode = oriented.mode  # Keep pixels compatible with their Gray/CMYK ICC.
        elif output_mime == "image/png" and oriented.mode in ("L", "LA"):
            mode = "LA" if "transparency" in oriented.info else oriented.mode
        with oriented.convert(mode) as pixels:
            clean = Image.new(mode, pixels.size)
            clean.paste(pixels)  # No EXIF, XMP, thumbnails, or secondary frames.
        fmt = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[output_mime]
        quality = 90
        while True:
            output = BytesIO()
            clean.save(output, format=fmt, icc_profile=icc, **({"quality": quality} if fmt != "PNG" else {}))
            content = output.getvalue()
            if len(content) <= MAX_BYTES:
                break
            if fmt != "PNG" and quality > 66:
                quality -= 8
            else:
                if min(clean.size) <= 1:
                    raise ValueError("Image cannot fit")
                resized = True
                smaller = clean.resize((max(1, int(clean.width * .8)), max(1, int(clean.height * .8))), Image.Resampling.LANCZOS)
                clean.close()
                clean = smaller
        header = {"width": clean.width, "height": clean.height, "mime_type": output_mime,
                  "had_metadata": had_metadata, "resized": resized, "decode_limits": {
                      "cpu_seconds": resource.getrlimit(resource.RLIMIT_CPU)[0],
                      "memory_bytes": MEMORY_BYTES if sys.platform == "darwin" else resource.getrlimit(resource.RLIMIT_AS)[0],
                      "memory_kind": "parent_rss_watchdog" if sys.platform == "darwin" else "address_space"}}
        sys.stdout.buffer.write(json.dumps(header).encode() + b"\n" + content)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Decoder text is untrusted and may include metadata. The parent receives
        # only an exit code; no provider or rider content is logged.
        raise SystemExit(1) from None
