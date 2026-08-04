Information about the directory .aicode/index

- Index data now lives under:
  - "engines/<engineId>/segments/<segmentDir>/..." for engine artifacts (lexical, vector, symbol, feeder, ...).
  - "engines/<engineId>/manifest.json" which selects the active segment for each engine.
  - At any given time, only the segment referenced by "manifest.json" (or the initial placeholder "g000000" before the first commit) is kept as the long-term committed view for that engine; older segments are considered disposable.

- Do not modify any files here.
  - These artifacts are generated and are not checked against manual changes, for performance reasons.
  - Therefore manual edits are unsupported and may introduce hard-to-debug issues.

- After a crash, you may see orphan "segments/..." folders or temporary files.
  - Segments that are not referenced by "manifest.json" are ignored by the indexer.
  - They are automatically removed by the internal vacuum process after a successful commit or the next indexer restart.
  - You can still delete the whole ".aicode/index" directory if you prefer to restart from a clean index.

- If you updated a file by accident or need to force a rebuild:
  - Delete the entire ".aicode/index" directory.
  - Restart VS Code to trigger a clean re-index.

- Important performance requirement: You should include this directory into version control.
  - Otherwise, each branch switch will force an index rebuild.
