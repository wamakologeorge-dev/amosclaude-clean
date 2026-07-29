# Amosclaud Autonomous for Xcode

This Swift package is a native macOS/Xcode companion for the existing Amosclaud Copilot and governed Autonomous pipeline. It does not create a second autonomous brain.

## Open in Xcode

Open `Package.swift` in Xcode, select the `amosclaud-xcode` executable scheme, and build or run it. The same executable can be used from Terminal or an Xcode custom behavior.

## Store the token securely

```bash
chmod +x store-token.sh
./store-token.sh
```

The helper stores the token in macOS Keychain under service `amosclaud-autonomous` and the current macOS account. The token is not written into the repository or an Xcode scheme.

Environment variables `AMOSCLAUD_AUTONOMOUS_KEY` or `AMOSCLAUD_TOKEN` take precedence when present.

## Commands

```bash
swift run amosclaud-xcode doctor
swift run amosclaud-xcode agents
swift run amosclaud-xcode plan --task "Explain this view model"
swift run amosclaud-xcode run --task "Fix and verify the failing test"
swift run amosclaud-xcode chat
```

Optional context:

```bash
swift run amosclaud-xcode plan \
  --task "Review this selected function" \
  --repository wamakologeorge-dev/amosclaude-clean \
  --branch feature/example \
  --file Sources/App/ViewModel.swift \
  --language swift \
  --selection-file /tmp/amosclaud-selection.txt \
  --agent security
```

Only explicitly supplied selected text is sent. The companion rejects `.env`, private-key, certificate, credential, and `secrets/` paths and caps selected text at 16,000 characters.

## Xcode behavior launcher

`xcode-behavior.sh` can be assigned to an Xcode behavior or invoked from a Run Script action:

```bash
chmod +x xcode-behavior.sh
./xcode-behavior.sh plan
./xcode-behavior.sh run
```

When `AMOSCLAUD_TASK` is absent, the launcher opens a macOS prompt. It uses `SRCROOT` and `SCRIPT_INPUT_FILE_0` when Xcode provides them, so only a repository-relative active file path is sent. Set `AMOSCLAUD_SELECTION_FILE` only when you intentionally exported selected text to a temporary file.

`plan` previews routing. `run` enters the same branch, approval, verification, and Results controls used by Amosclaud Autonomous.
