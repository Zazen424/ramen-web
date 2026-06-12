from pendant_server.sentence_chunker import SentenceChunker, split_sentences


def test_fires_on_sentence_boundary():
    c = SentenceChunker()
    assert c.push("Hello there") == []          # no terminator yet
    out = c.push(". How are you?")
    assert out == ["Hello there.", "How are you?"]


def test_holds_abbreviation_until_space():
    # A dot immediately followed by a letter is NOT a boundary.
    c = SentenceChunker()
    out = c.push("The meeting is at 9 a.m. today.")
    # Only one real sentence ends here (the final period with end-of-buffer).
    assert out == ["The meeting is at 9 a.m. today."]


def test_flush_emits_unterminated_tail():
    c = SentenceChunker()
    assert c.push("no period here") == []
    assert c.flush() == ["no period here"]


def test_streaming_token_by_token():
    c = SentenceChunker()
    sentences = []
    for tok in "One. Two! Three?".split(" "):
        sentences += c.push(tok + " ")
    sentences += c.flush()
    assert sentences == ["One.", "Two!", "Three?"]


def test_split_helper():
    assert list(split_sentences("A. B. C.")) == ["A.", "B.", "C."]
