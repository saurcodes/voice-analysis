from vocal_coach.transcription.fillers import count_fillers, per_min, words_per_min
from vocal_coach.transcription.schema import TranscriptWord

FILLERS = ["um", "uh", "like", "basically", "actually", "you know", "so"]


def _words(*tokens: str) -> list[TranscriptWord]:
    return [TranscriptWord(start_s=i * 0.3, end_s=i * 0.3 + 0.25, word=t, probability=0.9) for i, t in enumerate(tokens)]


def test_counts_single_and_multiword_fillers():
    words = _words(" Um,", "so", "I", "was,", "like,", "You", "know,", "basically", "done", "uh")
    counts = count_fillers(words, FILLERS)
    assert counts == {"um": 1, "uh": 1, "like": 1, "basically": 1, "actually": 0, "you know": 1, "so": 1}


def test_multiword_filler_across_segment_boundary_and_case():
    # "You" ends one whisper segment, "know." starts the next; tokens are still adjacent in the word list.
    words = _words("and", "You", "know.", "that")
    assert count_fillers(words, FILLERS)["you know"] == 1


def test_multiword_consumes_tokens_so_singles_do_not_double_count():
    words = _words("you", "know", "you")
    counts = count_fillers(words, ["you know", "you"])
    assert counts == {"you know": 1, "you": 1}


def test_all_keys_present_when_no_fillers():
    assert count_fillers(_words("clean", "speech"), FILLERS) == {f: 0 for f in FILLERS}


def test_rates():
    assert abs(words_per_min(120, 60.0) - 120.0) < 1e-9
    assert words_per_min(5, 0.0) == 0.0
    assert abs(per_min(3, 30.0) - 6.0) < 1e-9


def test_empty_filler_entry_never_matches_and_does_not_hang():
    words = _words("a", "b")
    assert count_fillers(words, ["", "   ", "a"]) == {"": 0, "   ": 0, "a": 1}
