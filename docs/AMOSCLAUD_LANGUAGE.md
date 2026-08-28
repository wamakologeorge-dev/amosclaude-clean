# Amosclaud Programming Language

## Status

The Amosclaud Programming Language is an active language-design and implementation project within Amosclaud. This document defines the target contract. A feature is not considered implemented merely because it appears in this specification.

## Purpose

Amosclaud is intended to be a programming language for both deterministic software and governed agentic software engineering. Source files use the `.amos` extension.

The language should be usable without an AI model for ordinary deterministic constructs. Agent features are an additional standard capability, not a replacement for normal language semantics.

## Design principles

1. Readable source code with a small, consistent grammar.
2. Deterministic core semantics.
3. First-class modules, functions, data, errors, tests, processes, files, networking, and concurrency.
4. Explicit authority for agent, repository, terminal, network, credential, and deployment operations.
5. Verification as a language/runtime concept rather than an afterthought.
6. Interoperability with existing software ecosystems.
7. Useful diagnostics and tooling from the first implementation stages.

## Source identity

```text
hello.amos
server.amos
tests/server_test.amos
```

## Representative target syntax

```text
program Hello

let name: String = "Amosclaud"

fn greet(value: String) -> String {
    return "Hello, " + value
}

print(greet(name))
```

Collections and control flow are expected to follow similarly readable forms:

```text
let services = ["api", "agent", "runtime"]

for service in services {
    print(service)
}

if services.length > 0 {
    print("ready")
}
```

## Agent programming

Agent blocks are intended to express governed engineering work rather than unrestricted model execution.

```text
agent programmer {
    objective "Repair the failing authentication tests"
    workspace "."
    allow read, edit, terminal
    verify tests
}
```

An implementation must translate requested authority into concrete runtime permissions. A source program cannot grant itself authority that the invoking user, organization, workspace, or execution environment does not possess.

## Verification

Verification is a first-class Amosclaud concept:

```text
verify {
    run "pytest -q"
    require exit_code == 0
}
```

A future runtime may expose structured verification APIs rather than relying only on shell commands.

## Language architecture

The implementation roadmap is:

```text
.amos source
   ↓
lexer
   ↓
parser
   ↓
AST
   ↓
semantic analysis
   ↓
Amosclaud runtime / intermediate representation
   ↓
standard library + host interoperability
   ↓
program result + diagnostics + verification evidence
```

## Runtime roadmap

The initial implementation should establish:

- `amos run file.amos`
- `amos check file.amos`
- `amos fmt file.amos`
- lexical tokens and source locations
- parser and AST
- variables, literals and expressions
- functions and scopes
- conditionals and loops
- lists/maps and structured data
- errors and exit codes
- modules/imports
- tests

Later stages should add a type system, package manager, async/concurrency model, process APIs, filesystem APIs, HTTP/network APIs, language server, debugger, formatter stability, package registry, compiled or bytecode execution where justified, and governed agent primitives.

## Standard library direction

Proposed namespaces include:

```text
amos::io
amos::fs
amos::process
amos::http
amos::json
amos::time
amos::test
amos::repo
amos::workspace
amos::verify
amos::agent
```

Agent and repository namespaces must enforce platform authority at runtime.

## Interoperability

Amosclaud should coexist with existing languages. The platform already works with Python-centric services and broader execution tooling; the language runtime should eventually support deliberate interoperability boundaries rather than forcing projects to be rewritten in `.amos`.

## Toolchain target

The complete language toolchain is expected to include a CLI, parser/runtime, formatter, test runner, package/module system, language server, editor integration, debugger, documentation generator, package registry, sandbox execution contract, and SpaceCodeMe integration.

## Definition of complete

Amosclaud should only be called a complete general-purpose programming language when the implemented toolchain can reliably parse and execute real `.amos` programs, provide stable semantics and diagnostics, support reusable modules/packages, test programs, integrate with development tools, and maintain compatibility through a documented versioning process.
