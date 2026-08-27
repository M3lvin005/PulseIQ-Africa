from __future__ import annotations

import math
import subprocess
import wave
from array import array
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from imageio_ffmpeg import get_ffmpeg_exe


ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1920, 1080
FPS = 30
DURATIONS = [8.5, 8.5, 8.0, 8.0, 11.0]
FADE = 0.8
TOTAL = sum(DURATIONS) - FADE * (len(DURATIONS) - 1)

FONT_BOLD = Path(r"C:\Windows\Fonts\segoeuib.ttf")
FONT_REGULAR = Path(r"C:\Windows\Fonts\segoeui.ttf")


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=size)


def centered(draw: ImageDraw.ImageDraw, text: str, y: int, fnt: ImageFont.FreeTypeFont,
             fill=(255, 255, 255, 255), stroke=0) -> None:
    box = draw.textbbox((0, 0), text, font=fnt, stroke_width=stroke)
    x = (WIDTH - (box[2] - box[0])) // 2
    draw.text((x, y), text, font=fnt, fill=fill, stroke_width=stroke,
              stroke_fill=(29, 18, 10, 220))


def make_overlays() -> None:
    gold = (229, 184, 91, 255)
    white = (255, 255, 255, 255)

    intro = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(intro)
    draw.rounded_rectangle((265, 48, 1655, 262), radius=36, fill=(24, 14, 9, 150),
                           outline=(229, 184, 91, 210), width=3)
    centered(draw, "KIKKIE WORLD'S COLLECTIONZ", 78, font(FONT_BOLD, 72), white, 1)
    centered(draw, "Bags  •  Accessories  •  Style", 174, font(FONT_REGULAR, 42), gold)
    draw.rounded_rectangle((480, 935, 1440, 1022), radius=28, fill=(24, 14, 9, 165))
    centered(draw, "Quality products at affordable prices", 952, font(FONT_REGULAR, 40), white)
    intro.save(ROOT / "overlay-intro.png")

    quality = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(quality)
    draw.rounded_rectangle((470, 900, 1450, 1000), radius=32, fill=(24, 14, 9, 175),
                           outline=(229, 184, 91, 220), width=3)
    centered(draw, "Quality products at affordable prices", 922,
             font(FONT_BOLD, 42), white)
    quality.save(ROOT / "overlay-quality.png")

    closing = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(closing)
    draw.rounded_rectangle((270, 48, 1650, 164), radius=34, fill=(24, 14, 9, 160),
                           outline=(229, 184, 91, 220), width=3)
    centered(draw, "KIKKIE WORLD'S COLLECTIONZ", 72, font(FONT_BOLD, 64), white, 1)
    draw.rounded_rectangle((590, 916, 1330, 1018), radius=32, fill=(24, 14, 9, 175))
    centered(draw, "Bags  •  Accessories  •  Style", 940,
             font(FONT_REGULAR, 42), gold)
    closing.save(ROOT / "overlay-closing.png")


def make_music() -> None:
    sample_rate = 44100
    total_samples = int(TOTAL * sample_rate)
    chords = [
        (220.00, 261.63, 329.63),
        (174.61, 220.00, 261.63),
        (261.63, 329.63, 392.00),
        (196.00, 246.94, 293.66),
    ]
    out = array("h")
    beat = 60.0 / 96.0
    for i in range(total_samples):
        t = i / sample_rate
        chord = chords[int(t / (beat * 4)) % len(chords)]
        pad = sum(math.sin(2 * math.pi * f * t) for f in chord) / 3.0
        local = t % beat
        pluck_env = math.exp(-5.2 * local / beat)
        pluck_note = chord[int(t / beat) % 3] * 2.0
        pluck = math.sin(2 * math.pi * pluck_note * t) * pluck_env
        shimmer = math.sin(2 * math.pi * chord[2] * 4 * t) * 0.08
        fade_in = min(1.0, t / 1.6)
        fade_out = min(1.0, max(0.0, (TOTAL - t) / 2.0))
        sample = (0.14 * pad + 0.10 * pluck + 0.03 * shimmer) * fade_in * fade_out
        left = int(max(-1.0, min(1.0, sample * 0.96)) * 32767)
        right = int(max(-1.0, min(1.0, sample * 1.04)) * 32767)
        out.append(left)
        out.append(right)
    with wave.open(str(ROOT / "music-bed.wav"), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(out.tobytes())


def make_video() -> None:
    ffmpeg = get_ffmpeg_exe()
    images = [
        "scene-01-reference.png",
        "scene-02-handbag.png",
        "scene-03-products.png",
        "scene-04-customer.png",
        "scene-05-closing.png",
    ]
    segment_paths = []
    lengths = [int(d * FPS) for d in DURATIONS]
    for i, (image_name, duration, frames) in enumerate(zip(images, DURATIONS, lengths)):
        segment_path = ROOT / f"segment-{i + 1:02d}.mp4"
        segment_paths.append(segment_path)
        if segment_path.exists() and segment_path.stat().st_size > 10_000:
            continue
        if i == 2:
            zoom = "1.065"
            x = f"(iw-iw/zoom)*on/{max(1, frames - 1)}"
        elif i == 3:
            zoom = "min(zoom+0.00020,1.045)"
            x = "iw/2-(iw/zoom/2)"
        else:
            zoom = "min(zoom+0.00024,1.055)"
            x = "iw/2-(iw/zoom/2)"
        video_filter = (
            f"scale=2200:1238:force_original_aspect_ratio=increase,"
            f"crop=2200:1238,zoompan=z='{zoom}':x='{x}':"
            f"y='ih/2-(ih/zoom/2)':d=1:s={WIDTH}x{HEIGHT}:fps={FPS},"
            f"trim=duration={duration},setpts=N/({FPS}*TB),format=yuv420p"
        )
        subprocess.run([
            ffmpeg, "-y", "-loop", "1", "-framerate", str(FPS),
            "-i", str(ROOT / image_name), "-vf", video_filter,
            "-t", str(duration), "-r", str(FPS), "-an", "-c:v", "libx264",
            "-preset", "medium", "-crf", "18", "-video_track_timescale", "90000",
            str(segment_path),
        ], check=True)

    cmd = [ffmpeg, "-y"]
    for segment_path in segment_paths:
        cmd += ["-i", str(segment_path)]
    for overlay_name in ("overlay-intro.png", "overlay-quality.png", "overlay-closing.png"):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", str(TOTAL),
                "-i", str(ROOT / overlay_name)]
    cmd += ["-i", str(ROOT / "voiceover.wav"), "-i", str(ROOT / "music-bed.wav")]

    filters = [f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={TOTAL}[canvas]"]
    starts = [0.0]
    for duration in DURATIONS[:-1]:
        starts.append(starts[-1] + duration - FADE)
    for i, (start, duration) in enumerate(zip(starts, DURATIONS)):
        fades = []
        if i > 0:
            fades.append(f"fade=t=in:st=0:d={FADE}:alpha=1")
        if i < len(DURATIONS) - 1:
            fades.append(f"fade=t=out:st={duration - FADE}:d={FADE}:alpha=1")
        fade_chain = ",".join(fades)
        if fade_chain:
            fade_chain += ","
        filters.append(
            f"[{i}:v]fps={FPS},format=rgba,{fade_chain}"
            f"setpts=PTS-STARTPTS+{start}/TB[s{i}]"
        )
    previous = "canvas"
    for i, (start, duration) in enumerate(zip(starts, DURATIONS)):
        output = "base" if i == len(DURATIONS) - 1 else f"c{i}"
        filters.append(
            f"[{previous}][s{i}]overlay=0:0:eof_action=pass:repeatlast=0:"
            f"shortest=0:enable='between(t,{start},{start + duration})'[{output}]"
        )
        previous = output
    filters += [
        "[5:v]format=rgba,fade=t=in:st=0.35:d=0.55:alpha=1,"
        "fade=t=out:st=6.0:d=0.55:alpha=1[oi]",
        "[base][oi]overlay=0:0:enable='between(t,0.35,6.55)'[t1]",
        "[6:v]format=rgba,fade=t=in:st=15.7:d=0.5:alpha=1,"
        "fade=t=out:st=22.3:d=0.5:alpha=1[oq]",
        "[t1][oq]overlay=0:0:enable='between(t,15.7,22.8)'[t2]",
        "[7:v]format=rgba,fade=t=in:st=30.4:d=0.6:alpha=1,"
        "fade=t=out:st=39.7:d=0.7:alpha=1[oc]",
        "[t2][oc]overlay=0:0:enable='between(t,30.4,40.4)',"
        "fade=t=out:st=40.1:d=0.7,format=yuv420p[vout]",
        "[8:a]adelay=800|800,volume=1.0,apad=pad_dur=2.6[voice]",
        "[9:a]volume=0.34[music]",
        "[voice][music]amix=inputs=2:duration=longest:dropout_transition=1.5,"
        f"atrim=duration={TOTAL},afade=t=out:st={TOTAL - 1.2}:d=1.2[aout]",
    ]
    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-t", str(TOTAL),
        str(ROOT / "kikkie-worlds-collectionz-promo.mp4"),
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    make_overlays()
    make_music()
    make_video()
