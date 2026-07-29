import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

private let defaultBaseURL = "https://www.amosclaud.com"
private let maximumSelectionCharacters = 16_000
private let maximumTaskCharacters = 12_000

private enum CompanionError: Error, CustomStringConvertible {
    case message(String)

    var description: String {
        switch self {
        case .message(let value):
            return value
        }
    }
}

private struct Arguments {
    let values: [String]

    var command: String? { values.first }

    func option(_ name: String) -> String? {
        guard let index = values.firstIndex(of: name), values.indices.contains(index + 1) else {
            return nil
        }
        return values[index + 1]
    }

    func flag(_ name: String) -> Bool {
        values.contains(name)
    }

    var positionalTask: String? {
        guard values.count > 1, !values[1].hasPrefix("--") else { return nil }
        return values[1]
    }
}

private func normalizeBaseURL(_ value: String?) throws -> URL {
    var raw = (value?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
        ? value!
        : defaultBaseURL)
        .trimmingCharacters(in: .whitespacesAndNewlines)
    while raw.hasSuffix("/") && !raw.hasSuffix("://") {
        raw.removeLast()
    }
    guard let components = URLComponents(string: raw),
          let scheme = components.scheme?.lowercased(),
          let host = components.host?.lowercased() else {
        throw CompanionError.message("AMOSCLAUD_URL is invalid")
    }
    let secureRemote = scheme == "https"
    let localDevelopment = scheme == "http"
        && ["localhost", "127.0.0.1", "::1"].contains(host)
    guard secureRemote || localDevelopment, let url = URL(string: raw) else {
        throw CompanionError.message(
            "AMOSCLAUD_URL must use HTTPS, except for exact localhost development hosts"
        )
    }
    return url
}

private func normalizedRelativePath(_ value: String?) throws -> String? {
    guard let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        return nil
    }
    let normalized = value.replacingOccurrences(of: "\\", with: "/")
    let parts = normalized.split(separator: "/", omittingEmptySubsequences: false)
    guard !normalized.hasPrefix("/"), !parts.contains("..") else {
        throw CompanionError.message(
            "Editor file paths must be repository-relative and cannot contain '..'"
        )
    }
    return normalized
}

private func isSensitivePath(_ value: String?) -> Bool {
    guard let value else { return false }
    let normalized = value.lowercased().replacingOccurrences(of: "\\", with: "/")
    let parts = normalized.split(separator: "/").map(String.init)
    let name = parts.last ?? ""
    let blockedNames: Set<String> = [
        ".env", "id_rsa", "id_ed25519", "credentials", "credentials.json", "secrets.json"
    ]
    let blockedSuffixes = [".key", ".pem", ".p12", ".pfx"]
    return blockedNames.contains(name)
        || name.hasPrefix(".env.")
        || blockedSuffixes.contains(where: { name.hasSuffix($0) })
        || parts.contains("secrets")
        || parts.contains(".secrets")
}

private func readSelectionFile(_ value: String?) throws -> String? {
    guard let value else { return nil }
    let url = URL(fileURLWithPath: NSString(string: value).expandingTildeInPath)
    guard FileManager.default.fileExists(atPath: url.path) else {
        throw CompanionError.message("Selection file does not exist: \(url.path)")
    }
    guard !isSensitivePath(url.path) else {
        throw CompanionError.message("Sensitive files cannot be read as editor selections")
    }
    let text = try String(contentsOf: url, encoding: .utf8)
    return String(text.prefix(maximumSelectionCharacters))
}

private func keychainToken() -> String? {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/security")
    process.arguments = [
        "find-generic-password",
        "-a", NSUserName(),
        "-s", "amosclaud-autonomous",
        "-w"
    ]
    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = Pipe()
    do {
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
    } catch {
        return nil
    }
}

private func resolvedToken() -> String? {
    let environment = ProcessInfo.processInfo.environment
    return environment["AMOSCLAUD_AUTONOMOUS_KEY"]
        ?? environment["AMOSCLAUD_TOKEN"]
        ?? keychainToken()
}

private struct AmosclaudClient {
    let baseURL: URL
    let token: String?

    func request(
        path: String,
        method: String = "GET",
        payload: [String: Any]? = nil,
        authenticated: Bool = false
    ) async throws -> Any {
        if authenticated && (token?.isEmpty != false) {
            throw CompanionError.message(
                "Set AMOSCLAUD_AUTONOMOUS_KEY or store a token in macOS Keychain"
            )
        }
        guard let url = URL(string: baseURL.absoluteString + path) else {
            throw CompanionError.message("Invalid Amosclaud endpoint")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("amosclaud-xcode/0.1", forHTTPHeaderField: "User-Agent")
        if let token, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let payload {
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw CompanionError.message("Amosclaud returned an invalid HTTP response")
        }
        let body = try JSONSerialization.jsonObject(with: data.isEmpty ? Data("{}".utf8) : data)
        guard (200..<300).contains(http.statusCode) else {
            let rendered = String(data: data, encoding: .utf8) ?? String(describing: body)
            throw CompanionError.message("Amosclaud returned HTTP \(http.statusCode): \(rendered)")
        }
        return body
    }
}

private func context(from arguments: Arguments, source: String) throws -> [String: Any] {
    let environment = ProcessInfo.processInfo.environment
    let filePath = try normalizedRelativePath(arguments.option("--file"))
    if isSensitivePath(filePath) {
        throw CompanionError.message("Sensitive files cannot be sent as Xcode context")
    }
    var value: [String: Any] = [
        "branch": arguments.option("--branch")
            ?? environment["AMOSCLAUD_BRANCH"]
            ?? "main",
        "source": source
    ]
    if let repository = arguments.option("--repository") ?? environment["AMOSCLAUD_REPOSITORY"],
       !repository.isEmpty {
        value["repository"] = repository
    }
    if let filePath { value["file_path"] = filePath }
    if let language = arguments.option("--language"), !language.isEmpty {
        value["language"] = String(language.prefix(64))
    }
    if let selection = try readSelectionFile(arguments.option("--selection-file")) {
        value["selection"] = selection
    }
    return value
}

private func payload(
    task: String,
    agent: String?,
    context: [String: Any]
) throws -> [String: Any] {
    let clean = task.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !clean.isEmpty else {
        throw CompanionError.message("A task is required")
    }
    guard clean.count <= maximumTaskCharacters else {
        throw CompanionError.message("Tasks are limited to \(maximumTaskCharacters) characters")
    }
    var value: [String: Any] = ["task": clean, "context": context]
    if let agent, !agent.isEmpty { value["requested_agent"] = agent }
    return value
}

private func printJSON(_ value: Any) throws {
    let data = try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
    guard let output = String(data: data, encoding: .utf8) else {
        throw CompanionError.message("Could not render Amosclaud response")
    }
    print(output)
}

private func usage() {
    print("""
    Amosclaud Autonomous Xcode companion

    Usage:
      amosclaud-xcode doctor
      amosclaud-xcode agents
      amosclaud-xcode plan --task "Explain this code" [context options]
      amosclaud-xcode run --task "Fix and verify this test" [context options]
      amosclaud-xcode chat [--execute] [--agent fixer]

    Context options:
      --repository owner/name
      --branch branch-name
      --file repository/relative/path.swift
      --language swift
      --selection-file /temporary/selected-text.txt
      --agent fixer|action|security|clean|codex|autonomous|ai
    """)
}

private func interactiveChat(
    client: AmosclaudClient,
    arguments: Arguments
) async throws {
    var execute = arguments.flag("--execute")
    var agent = arguments.option("--agent")
    print("Amosclaud Autonomous Xcode chat. Commands: /agent NAME, /plan, /run, /quit")
    while true {
        print("amosclaud> ", terminator: "")
        guard let input = readLine()?.trimmingCharacters(in: .whitespacesAndNewlines) else {
            return
        }
        if input.isEmpty { continue }
        if input == "/quit" || input == "/exit" { return }
        if input == "/plan" {
            execute = false
            print("Chat mode: plan only")
            continue
        }
        if input == "/run" {
            execute = true
            print("Chat mode: authorized execution")
            continue
        }
        if input.hasPrefix("/agent ") {
            agent = String(input.dropFirst(7)).trimmingCharacters(in: .whitespacesAndNewlines)
            print("Internal capability preference: \(agent?.isEmpty == false ? agent! : "automatic")")
            continue
        }
        let requestPayload = try payload(
            task: input,
            agent: agent,
            context: try context(from: arguments, source: "xcode-chat")
        )
        let result = try await client.request(
            path: execute ? "/api/v1/copilot/run" : "/api/v1/copilot/plan",
            method: "POST",
            payload: requestPayload,
            authenticated: true
        )
        try printJSON(result)
    }
}

@main
private struct AmosclaudXcodeMain {
    static func main() async {
        let arguments = Arguments(values: Array(CommandLine.arguments.dropFirst()))
        guard let command = arguments.command else {
            usage()
            Foundation.exit(2)
        }
        do {
            let environment = ProcessInfo.processInfo.environment
            let baseURL = try normalizeBaseURL(arguments.option("--url") ?? environment["AMOSCLAUD_URL"])
            let client = AmosclaudClient(baseURL: baseURL, token: resolvedToken())
            switch command {
            case "doctor":
                try printJSON(try await client.request(path: "/api/v1/copilot"))
            case "agents":
                try printJSON(try await client.request(path: "/api/v1/copilot/agents"))
            case "plan", "run":
                guard let task = arguments.option("--task") ?? arguments.positionalTask else {
                    throw CompanionError.message("Provide the task with --task")
                }
                let requestPayload = try payload(
                    task: task,
                    agent: arguments.option("--agent"),
                    context: try context(from: arguments, source: "xcode-\(command)")
                )
                let result = try await client.request(
                    path: "/api/v1/copilot/\(command)",
                    method: "POST",
                    payload: requestPayload,
                    authenticated: true
                )
                try printJSON(result)
            case "chat":
                try await interactiveChat(client: client, arguments: arguments)
            default:
                usage()
                throw CompanionError.message("Unknown command: \(command)")
            }
        } catch {
            fputs("amosclaud-xcode: \(error)\n", stderr)
            Foundation.exit(1)
        }
    }
}
