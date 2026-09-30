# installconfig's folder flags said they do not check a path leading out, which they refuse

**Front:** Documentation versus code, running the examples (round 53 confirmation) | **Severity:** Medium | **Resolution:** Direct | **Round:** 53

installconfig --folderadr said it does NOT check whether the value would escape a repository; since round 50 the schema refuses `..` on read, so `installconfig --folderadr ../x` answers config-folderadr-not-relative (run), and --folderlog left `..` out. Both now say so, and that a link leading out is checked by init. config's --folderadr names the code refusing the repository root (config-folderadr-folderlog-overlap), and the CHANGELOG says the new header comment is translated in each pack, not the same text in all.
