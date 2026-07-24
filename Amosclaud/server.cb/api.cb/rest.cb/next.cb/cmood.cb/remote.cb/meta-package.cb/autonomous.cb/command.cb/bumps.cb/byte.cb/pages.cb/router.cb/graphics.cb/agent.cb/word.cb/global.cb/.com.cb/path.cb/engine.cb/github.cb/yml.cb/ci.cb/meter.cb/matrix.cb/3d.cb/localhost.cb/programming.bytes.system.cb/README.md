# Amosclaud Programming Bytes System CB

This is the exact literal CB service path requested for Amosclaud. Every folder name is a stage
in the ordered pipeline recorded by `manifest.json`.

Because `.com.cb` and `3d.cb` are not valid Python identifiers, application code imports the
runtime through `Amosclaud.programming_bytes_system_cb`. The literal path remains the stable
filesystem and service-discovery contract.

The runtime validates REST methods, commands, repository identifiers, page paths, and byte size;
it does not execute a shell or perform remote/GitHub network calls. It returns an integrity-checked
`ByteFrame` with evidence from all 28 stages.
