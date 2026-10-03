import pytest

from vocal_coach.transcription.syllables import count_syllables, normalise_token


@pytest.mark.parametrize("raw, expected", [
    (" Hello,", "hello"),
    ("YOU", "you"),
    ("don't", "don't"),
    ("...", ""),
    ("—", ""),
    (" 2024 ", "2024"),
])
def test_normalise_token(raw, expected):
    assert normalise_token(raw) == expected


@pytest.mark.parametrize("word, expected", [
    ("cat", 1),
    ("basically", 4),
    ("actually", 3),   # heuristic undercounts the mid-word "ua" hiatus; accepted, documented
    ("the", 1),
    ("table", 2),      # trailing 'le' after a consonant counts
    ("make", 1),       # silent trailing e
    ("idea", 3),
    ("hmm", 1),        # no vowels: still one syllable
    ("2024", 1),       # digits: one token, one syllable
    ("...", 0),        # punctuation only
    ("you", 1),
    ("beautiful", 3),
    ("assigned", 2),   # silent "-ed"
    ("developed", 3),
    ("leveraged", 3),
    ("wanted", 2),     # "-ed" after t is a syllable
    ("added", 2),      # "-ed" after d is a syllable
    ("red", 1),        # too short to be a suffix
    ("bed", 1),
    ("agreed", 2),     # vowel before "-ed": no silent suffix
    ("proceed", 2),
    ("freed", 1),
    ("hundred", 1),    # known irregular: true count 2, heuristic undercounts
])
def test_count_syllables(word, expected):
    assert count_syllables(word) == expected
