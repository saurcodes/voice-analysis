import warnings
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.io.wavfile import WavFileWarning

from tests import synth
from tests.conftest import requires_ffmpeg
from vocal_coach.analysis.audio import AudioInfo, extract_wav, sha256_file


def _read_wav(path: Path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", WavFileWarning)
        return wavfile.read(path)


@requires_ffmpeg
def test_extract_stereo_44k_to_mono_16k(tmp_path: Path):
    t = np.arange(int(2.0 * 44100)) / 44100
    left = 0.3 * np.sin(2 * np.pi * 220 * t)
    right = 0.3 * np.sin(2 * np.pi * 330 * t)
    stereo = np.stack([left, right], axis=1)
    src = tmp_path / "in.wav"
    wavfile.write(src, 44100, (stereo * 32767).astype(np.int16))
    dst = tmp_path / "out.wav"

    info = extract_wav(src, dst)

    sr, data = _read_wav(dst)
    assert sr == 16000
    assert data.ndim == 1
    assert isinstance(info, AudioInfo)
    assert info.original_channels == 2
    assert info.original_sample_rate == 44100
    assert abs(info.duration_s - 2.0) < 0.05
    assert info.content_sha256 == sha256_file(dst)


@requires_ffmpeg
def test_extract_from_mp4_container(tmp_path: Path):
    # Build an mp4 with a silent video track and a stereo audio track using ffmpeg itself.
    import subprocess

    audio = tmp_path / "a.wav"
    synth.write_wav(audio, synth.tone(200, 1.0))  # mono in; ffmpeg upmixes to stereo below
    mp4 = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
         "-i", str(audio), "-ac", "2", "-ar", "44100", "-shortest", str(mp4)],
        check=True,
    )
    dst = tmp_path / "out.wav"

    info = extract_wav(mp4, dst)

    sr, data = _read_wav(dst)
    assert sr == 16000 and data.ndim == 1
    assert info.original_channels == 2
    assert info.original_sample_rate == 44100


@requires_ffmpeg
def test_extract_is_byte_deterministic(tmp_path: Path):
    src = synth.write_wav(tmp_path / "in.wav", synth.tone(150, 1.0))
    a = extract_wav(src, tmp_path / "a.wav")
    b = extract_wav(src, tmp_path / "b.wav")
    assert a.content_sha256 == b.content_sha256
