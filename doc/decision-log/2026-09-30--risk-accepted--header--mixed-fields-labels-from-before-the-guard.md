# A repository whose headertablefields changed before the field was guarded does not validate

Before headertablefields was guarded, config could change it with decisions present, leaving headers whose fields rows hold different labels. The parser now needs the configured label in that row, so such a repository fails check, and the guard refuses the change back. The repair is editing line 2 of the odd files by hand.

Accepted by the project owner: no version was tagged or published before the guard, so no user repository can be in that state.
