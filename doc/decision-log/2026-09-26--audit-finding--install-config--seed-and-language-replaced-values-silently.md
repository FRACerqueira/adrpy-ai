# installconfig --seed and --language replaced earlier values without saying so

**Front:** Round 47: first use from outside | **Severity:** Low | **Resolution:** Escalated | **Round:** 47

`installconfig --separator _` then `installconfig --language pt-br` left separator back at '-' with no warning; the documented example chains exactly those two. Both whole-file replaces now warn which fields changed value (names only, after the review found template reprs made it 5 KB), and the example says to set field flags after --language. Red then green (d3e900f).
