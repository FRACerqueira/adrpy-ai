# A body ending in a truncated UTF-8 sequence then a lone CR was streamed with its U+FFFD after the terminator

**Front:** Randomized comparison with the whole-file reference read, run to verify the interleaved-streams fix | **Severity:** Low | **Resolution:** Direct | **Round:** 50

At the end of the body, stream_normalized_body_chunks emitted the held-back CR before flushing the decoder, so the bytes of a truncated sequence came out after it: b'ab\xe2\x82\r' became 'ab' CRLF U+FFFD instead of 'ab' U+FFFD CRLF, and the rewritten file no longer ended with a terminator. It diverged from ADR0006V01's reference read, and it was already there before the interleaved-streams fix: 3000 random bodies at six chunk sizes gave the same 306 mismatches with the old and the new repair detection.

Fix: the decoder is flushed before the held CR is emitted.

Red: three bodies added to tests/test_lifecycle.py's reference matrix failed with the U+FFFD after the CRLF. Green after the fix, and the randomized comparison gives 0 mismatches in 18000 runs. Class: the only other streamer, migrate's _stream_migrated_candidate, copies bytes without decoding or normalizing terminators; every other read decodes a whole file at once.
