from __future__ import annotations

import math
import subprocess
import wave
from array import array
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe


ROOT = Path(__file__).resolve().parent
DURATION = 40.8
SAMPLE_RATE = 44100
BPM = 102.0
BEAT = 60.0 / BPM


def since_event(position: float, events: tuple[float, ...], cycle: float) -> float:
    return min((position - event) % cycle for event in events)


def make_afropop_music() -> Path:
    target = ROOT / "music-bed-v2.wav"
    chords = [
        (261.63, 329.63, 392.00, 493.88),  # Cmaj7
        (220.00, 261.63, 329.63, 392.00),  # Am7
        (174.61, 220.00, 261.63, 329.63),  # Fmaj7
        (196.00, 246.94, 293.66, 392.00),  # G
    ]
    kick_pattern = (0.0, 1.5, 2.5, 3.25)
    clap_pattern = (1.0, 3.0)
    samples = array("h")
    noise_state = 0x1234ABCD
    previous_noise = 0.0

    total_samples = int(DURATION * SAMPLE_RATE)
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        position = (t / BEAT) % 4.0
        bar = int(t / (BEAT * 4.0))
        chord = chords[bar % len(chords)]

        pad = sum(math.sin(2.0 * math.pi * f * t) for f in chord) / len(chord)
        root = chord[0] / 2.0
        bass_phase = (t % BEAT)
        bass_env = math.exp(-2.6 * bass_phase / BEAT)
        bass = math.sin(2.0 * math.pi * root * t) * bass_env

        eighth = BEAT / 2.0
        pluck_age = t % eighth
        pluck_index = int(t / eighth) % 8
        pluck_note = chord[(pluck_index * 3) % len(chord)] * 2.0
        pluck_env = math.exp(-7.5 * pluck_age / eighth)
        pluck = (
            math.sin(2.0 * math.pi * pluck_note * t)
            + 0.35 * math.sin(4.0 * math.pi * pluck_note * t)
        ) * pluck_env

        kick_age = since_event(position, kick_pattern, 4.0) * BEAT
        kick = 0.0
        if kick_age < 0.24:
            kick_freq = 78.0 - 28.0 * (kick_age / 0.24)
            kick = math.sin(2.0 * math.pi * kick_freq * kick_age) * math.exp(-16.0 * kick_age)

        noise_state = (1664525 * noise_state + 1013904223) & 0xFFFFFFFF
        raw_noise = ((noise_state / 0xFFFFFFFF) * 2.0) - 1.0
        bright_noise = raw_noise - 0.82 * previous_noise
        previous_noise = raw_noise

        clap_age = since_event(position, clap_pattern, 4.0) * BEAT
        clap = bright_noise * math.exp(-26.0 * clap_age) if clap_age < 0.16 else 0.0

        shaker_age = (position % 0.5) * BEAT
        shaker = bright_noise * math.exp(-58.0 * shaker_age) if shaker_age < 0.07 else 0.0

        # Gentle side-chain dip on each kick keeps the groove open and commercial.
        duck = 0.72 + 0.28 * min(1.0, kick_age / 0.16)
        musical = (0.13 * pad + 0.16 * bass + 0.12 * pluck) * duck
        percussion = 0.24 * kick + 0.075 * clap + 0.027 * shaker

        fade_in = min(1.0, t / 1.2)
        fade_out = min(1.0, max(0.0, (DURATION - t) / 1.8))
        mix = (musical + percussion) * fade_in * fade_out
        left = max(-1.0, min(1.0, mix * (0.98 + 0.04 * math.sin(2 * math.pi * 0.12 * t))))
        right = max(-1.0, min(1.0, mix * (1.02 - 0.04 * math.sin(2 * math.pi * 0.12 * t))))
        samples.append(int(left * 32767))
        samples.append(int(right * 32767))

    with wave.open(str(target), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(samples.tobytes())
    return target


def mix_revision(music: Path) -> Path:
    ffmpeg = get_ffmpeg_exe()
    source = ROOT / "kikkie-worlds-collectionz-promo.mp4"
    voice = ROOT / "voiceover-v2.mp3"
    target = ROOT / "kikkie-worlds-collectionz-promo-v2.mp4"
    audio_filter = (
        "[1:a]adelay=900|900,volume=1.12,highpass=f=90,"
        "acompressor=threshold=0.11:ratio=2.4:attack=12:release=180,"
        "apad=pad_dur=5[voice];"
        "[2:a]volume=0.48,lowpass=f=14500[music];"
        "[voice][music]amix=inputs=2:duration=longest:dropout_transition=1.8:normalize=0,"
        "volume=1.15,alimiter=limit=0.94,atrim=duration=40.8,"
        "afade=t=out:st=39.5:d=1.3[aout]"
    )
    subprocess.run([
        ffmpeg, "-y", "-i", str(source), "-i", str(voice), "-i", str(music),
        "-filter_complex", audio_filter,
        "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "224k", "-ar", "48000",
        "-movflags", "+faststart", "-t", "40.8", str(target),
    ], check=True)
    return target


if __name__ == "__main__":
    print(mix_revision(make_afropop_music()))
