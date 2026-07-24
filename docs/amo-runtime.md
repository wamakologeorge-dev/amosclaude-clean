# Amo Runtime

Amo Runtime is the agent-native language layer of Amosclaud. It is designed so an agent is not merely a model that receives prompts: its identity, goal, memory, permissions, actions, and execution history can be represented together in one readable `.amo` program.

## Core idea

```text
Agent identity + language + capability policy + memory + execution trace
                              =
                         Amo Runtime
```

An Amo program is both a description of an agent and an executable plan.

```amo
amo 1
agent "Workspace Guide"
goal "Help the owner understand the current workspace"
allow workspace.list
allow agent.respond
list "projects"
say "I inspected the project workspace."
```

## Why agent and language become one

Traditional programming languages execute instructions but do not understand goals. Traditional AI agents understand natural-language goals but often hide their action plan inside model output.

Amo Runtime combines both approaches:

- natural-language goals remain visible;
- executable actions are explicit;
- every capability must be declared;
- every instruction creates a trace entry;
- memory belongs to the program and runtime;
- the same `.amo` file can be inspected by a person, an agent, or an audit tool.

## Current language

Every program begins with a version header:

```amo
amo 1
```

### Identity

```amo
agent "Builder"
goal "Create a project note"
```

### Capabilities

```amo
allow workspace.read
allow workspace.write
allow workspace.list
allow memory.read
allow memory.write
allow agent.respond
```

Unknown capabilities are rejected. A program cannot perform an action unless its capability is declared.

### Memory and input

```amo
remember greeting "Hello"
say "{{greeting}}, {{input}}"
```

The caller's input is available as `{{input}}`.

### Workspace operations

```amo
list "projects"
read "notes/design.md" "design"
write "notes/result.txt" "{{design}}"
```

All paths are contained inside `AmosclaudWorkspace`. The runtime has no unrestricted shell command and cannot escape the configured workspace.

## API

Authenticated Amosclaud users can compile and execute programs through:

```text
POST /api/v1/amo/compile
POST /api/v1/amo/run
```

Compilation returns the parsed agent identity, goal, capabilities, memory, and instructions without executing them.

Execution returns:

- agent identity;
- goal;
- output;
- resulting memory;
- instruction-by-instruction trace;
- user identity associated with the run.

## Evolution model

The intended power-up loop is:

```text
Human goal
   ↓
Amosclaud agent proposes an Amo program
   ↓
Amo compiler validates syntax and capabilities
   ↓
Owner approves sensitive capabilities
   ↓
Amo Runtime executes inside the workspace
   ↓
Trace and result are stored
   ↓
Agent studies successful traces and improves future programs
```

The model does not receive unrestricted authority. The language is the control boundary between reasoning and action.

## Planned stages

### Stage 1 — Safe runtime

Implemented now:

- parser;
- agent identity;
- goals;
- declared capabilities;
- memory;
- safe workspace actions;
- output;
- execution trace;
- authenticated API;
- audit activity.

### Stage 2 — Model-assisted compilation

The local Amosclaud model converts a user's request into a proposed `.amo` program. The program is validated before execution and can be displayed for approval.

### Stage 3 — Typed tools

Add typed operations for projects, tasks, tests, repositories, backups, deployments, and service management rather than granting generic shell access.

### Stage 4 — Reversible execution

Actions declare rollback information. The runtime can preview a plan, execute it transactionally where possible, and reverse supported changes.

### Stage 5 — Learning from traces

Successful programs become reusable skills in the workspace. The agent retrieves, adapts, and composes approved skills while retaining an auditable program.

### Stage 6 — Visual agent-language interface

The Amosclaud dashboard presents the `.amo` program as both text and an execution graph showing goals, capabilities, memory, actions, approvals, and results.

## Safety principles

Amo Runtime follows these rules:

1. Capabilities are denied unless declared.
2. Unknown capabilities are rejected.
3. Workspace paths cannot escape the configured root.
4. The first runtime does not expose unrestricted shell execution.
5. Every executed instruction produces a trace.
6. Sensitive future tools must support owner approval.
7. Generated programs are treated as untrusted until validated.

Amo Lang is intended to make agent behavior more powerful **and** more understandable—not powerful by hiding what it does.
