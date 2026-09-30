# Two body streams consumed interleaved flagged each other's encoding repair

**Front:** Comment sweep of core, which flagged the stream as not reentrant; reproduced before the fix | **Severity:** Low | **Resolution:** Direct | **Round:** 50

stream_normalized_body_chunks registered a codec error handler by one fixed, process-global name on every call, closing over that call's report. With two streams consumed interleaved, the handler registered last received the other stream's decode errors: a dirty body reported encoding_repaired False and a clean one True. No caller interleaves today (every caller consumes one stream fully before the next), so the defect was latent.

Fix: no registered handler. The decoder uses the standard "replace" handler, and a repair is detected as more U+FFFD in the output than valid EF BF BD sequences in the input, counted in the raw bytes with two bytes carried across a chunk boundary (EF never occurs inside another sequence). The output bytes are unchanged.

Red: tests/test_lifecycle.py::test_interleaved_body_streams_each_report_their_own_repair failed with the reports swapped. Green after the fix. Positive controls: a valid U+FFFD in the body, including one cut across chunks at every chunk size, is not a repair. Class: register_error, getincrementaldecoder and decoder.decode have no other use in src.
