import subprocess
import sys
from pathlib import Path

from tests import synth
from tests.conftest import requires_ffmpeg


def _speechlike():
    a = synth.am(synth.vowel(500, 1500, 120, 3.0), 4.0)
    b = synth.am(synth.vowel(300, 2300, 130, 3.0), 4.5)
    return synth.with_noise_floor(synth.concat(a, synth.silence(0.6), b, synth.silence(1.2), a))


@requires_ffmpeg
def test_two_runs_in_separate_processes_are_byte_identical(tmp_path: Path):
    src = synth.write_wav(tmp_path / "in.wav", _speechlike())
    outs = []
    for i in range(2):
        out = tmp_path / f"metrics_{i}.json"
        subprocess.run(
            [sys.executable, "-m", "vocal_coach.analysis.analyser", str(src), "--out", str(out),
             "--work-dir", str(tmp_path / f"work{i}")],
            check=True,
        )
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]
    assert len(outs[0]) > 1000
