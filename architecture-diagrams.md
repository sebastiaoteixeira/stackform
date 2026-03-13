# Architecture Diagrams

## 1) Module/Container View

```mermaid
flowchart LR
    subgraph Transport["Transport Layer"]
        FASTAPI["FastAPI Adapter"]
        STAR["Starlette Adapter"]
        RAW["Raw ASGI Adapter"]
    end

    subgraph Core["Core Engine - Framework Agnostic"]
        CFG["Config Loader<br/>YAML and interpolation"]
        VAL["Schema Validator"]
        IR["IR Compiler<br/>Normalized ApiSpecIR"]
        PLAN["Runtime Plan Compiler<br/>Step Pipelines"]
        EXEC["Core Executor"]
        POL["Policy Engine"]
        ID["Identity and Auth Service"]
        QRY["Query and Expansion Planner"]
        LOGIC["Hooks and Logic Engine"]
        RT["Realtime Engine<br/>Subscriptions and Fanout"]
    end

    subgraph Adapters["Infrastructure Adapters"]
        PYM["Pydantic Model Factory<br/>Dynamic request and response models"]
        MONGO["Mongo Repository"]
        TOKEN["Token Provider"]
        BUS["Event Bus<br/>InMemory or Redis"]
        WEBHOOK["Webhook Dispatcher"]
    end

    FASTAPI --> EXEC
    STAR --> EXEC
    RAW --> EXEC

    CFG --> VAL --> IR --> PLAN --> EXEC
    PLAN --> PYM

    EXEC --> POL
    EXEC --> ID
    EXEC --> QRY
    EXEC --> LOGIC
    EXEC --> MONGO
    LOGIC --> RT
    EXEC --> RT

    ID --> TOKEN
    RT --> BUS
    RT --> WEBHOOK
```

## 2) Startup Flow (Runtime-Only MVP)

```mermaid
sequenceDiagram
    participant App as Runtime App
    participant Cfg as Config Loader
    participant Val as Validator
    participant Comp as Compiler
    participant PM as Pydantic Factory
    participant DB as Mongo Adapter
    participant Tx as Transport Adapter

    App->>Cfg: Load YAML and resolve env placeholders
    Cfg-->>App: Raw config
    App->>Val: Structural + semantic validation
    Val-->>App: Valid config
    App->>Comp: Compile to IR
    Comp-->>App: ApiSpecIR
    App->>Comp: Compile RuntimePlan (step pipelines)
    Comp-->>App: RuntimePlan
    App->>PM: Build dynamic models from RuntimePlan
    PM-->>App: Model registry
    App->>DB: Connect + init checks
    DB-->>App: Ready
    App->>Tx: Register routes/websockets from RuntimePlan
    Tx-->>App: Serving
```

## 3) HTTP Request Pipeline

```mermaid
sequenceDiagram
    participant Client
    participant Tx as Transport Adapter
    participant Exec as Core Executor
    participant Pipe as Compiled Step Pipeline
    participant Pol as Policy Engine
    participant Repo as Mongo Repository
    participant RT as Realtime Engine

    Client->>Tx: HTTP request
    Tx->>Exec: CoreRequest(route_id, params, body, headers)
    Exec->>Pipe: Run ordered steps
    Pipe->>Pipe: require_auth? -> require_role?
    Pipe->>Pipe: parse_body? -> validate_input?
    Pipe->>Pol: authorize + row filters + writable fields
    Pol-->>Pipe: allow/deny + filters
    Pipe->>Repo: Execute CRUD with effective filters
    Repo-->>Pipe: Result
    Pipe-->>Exec: CoreResponse
    Exec->>RT: Publish mutation event (if write)
    RT-->>Exec: ack
    Exec-->>Tx: CoreResponse
    Tx-->>Client: HTTP response
```

## 4) Realtime Flow

```mermaid
sequenceDiagram
    participant Client as WS Client
    participant Tx as WS Adapter
    participant Sub as Subscription Manager
    participant Pol as Policy Engine
    participant Bus as Event Bus
    participant Exec as Core Executor

    Client->>Tx: Connect + subscribe(collection, filters)
    Tx->>Pol: authorize subscription
    Pol-->>Tx: allow/deny
    Tx->>Sub: register subscriber + filters

    Exec->>Bus: publish(event)
    Bus->>Sub: event
    Sub->>Pol: per-event policy check
    Pol-->>Sub: allow/deny
    Sub-->>Tx: matched event payload
    Tx-->>Client: websocket message
```

## 5) Future Build-Time Compilation Path

```mermaid
flowchart LR
    YAML[YAML] --> V[Validate]
    V --> IR[Compile IR]
    IR --> ART[Emit Artifact\n(JSON/code)]
    ART --> BOOT[Runtime Boot]
    BOOT --> PLAN[Load RuntimePlan]
    PLAN --> SERVE[Serve Requests]
```
