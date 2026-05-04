# Generator Architecture Principles

## Separation of Concerns

Generators must maintain strict separation between parsing and code generation:

### ✓ ALLOWED: Access IR (Intermediate Representation)

Generators should **ONLY** access structured data through the `IRDocument` object:

```python
def generate_something(ir: IRDocument, output_dir: str) -> None:
    # ✓ Good: Access structured IR data
    for collection in ir.collections.values():
        name = collection.name
        fields = collection.fields

    # ✓ Good: Use IR properties
    if ir.has_ui:
        generate_frontend()

    # ✓ Good: Access nested IR objects
    mongo_db = ir.mongo.database
    deploy_port = ir.deploy.port if ir.deploy else 8000
```

### ✗ FORBIDDEN: Access Raw YAML

Generators must **NEVER** access raw YAML text or dictionaries:

```python
def generate_something(
    ir: IRDocument,
    raw_yaml_text: str,  # ✗ FORBIDDEN parameter
    output_dir: str
) -> None:
    # ✗ FORBIDDEN: Parsing raw YAML in generator
    if "mongo:" in raw_yaml_text:
        ...

    # ✗ FORBIDDEN: String matching on YAML
    if "ui:" in raw_yaml_text:
        ...

    # ✗ FORBIDDEN: Regex on raw YAML
    env_vars = re.findall(r'\$\{([A-Z_]+)\}', raw_yaml_text)
```

## Why This Matters

### 1. Single Source of Truth
The IR is the single source of truth for all code generation. Any logic that inspects YAML structure belongs in the parser, not the generator.

### 2. Maintainability
When YAML structure changes, only parsers need updating. Generators remain stable.

### 3. Testability
Generators can be tested with mock IR objects without needing YAML files.

### 4. Flexibility
The same IR can be generated from different sources (YAML, JSON, UI, API) without changing generators.

### 5. Type Safety
IR provides strong typing and validation. Raw YAML is unstructured and error-prone.

## How to Add New Generated Artifacts

If you need information that's not in the IR:

### Step 1: Add to IR Definition

```python
# src/yaml_api_generator/ir/api.py
@dataclass(frozen=True)
class IRDeploy:
    runtime: str
    env_vars: tuple[str, ...] = field(default_factory=tuple)  # ← Add here
```

### Step 2: Extract During Parsing

```python
# src/yaml_api_generator/parsers/transformers/v02/route_transformer.py
def build_deploy(self, deploy_data: dict, full_config: dict) -> IRDeploy:
    env_vars = self._extract_env_vars(full_config)  # ← Extract here
    return IRDeploy(
        runtime=deploy_data["runtime"],
        env_vars=tuple(env_vars),
    )
```

### Step 3: Use in Generator

```python
# src/yaml_api_generator/generators/deploy/context_builder.py
def build_deploy_context(ir: IRDocument) -> DeployContext:
    env_vars = list(ir.deploy.env_vars)  # ← Use structured data
```

## Examples

### ✓ Good: Environment Variables

```python
# In Parser (transformers/v02/route_transformer.py)
def _extract_env_vars(self, config: dict) -> list[str]:
    # Extract during parsing
    pattern = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)')
    vars_set = set()
    # ... extraction logic ...
    return sorted(vars_set)

# In IR (ir/api.py)
@dataclass(frozen=True)
class IRDeploy:
    env_vars: tuple[str, ...] = field(default_factory=tuple)

# In Generator (generators/deploy/context_builder.py)
def build_context(ir: IRDocument) -> DeployContext:
    return DeployContext(
        env_vars=list(ir.deploy.env_vars)  # Use IR data
    )
```

### ✗ Bad: String Matching in Generator

```python
# DON'T DO THIS
def build_context(ir: IRDocument, raw_yaml: str) -> DeployContext:
    # ✗ Generator parsing YAML - violates separation of concerns
    has_mongo = "mongo:" in raw_yaml
    env_vars = re.findall(r'\$\{([A-Z_]+)\}', raw_yaml)
```

### ✓ Good: Feature Detection

```python
# In IR (ir/api.py)
@dataclass(frozen=True)
class IRDocument:
    ui_config: dict | None = None

    @property
    def has_ui(self) -> bool:
        return self.ui_config is not None

# In Generator (generators/deploy/context_builder.py)
def build_context(ir: IRDocument) -> DeployContext:
    return DeployContext(
        has_frontend=ir.has_ui  # Use IR property
    )
```

### ✗ Bad: String Search in Generator

```python
# DON'T DO THIS
def build_context(ir: IRDocument, raw_yaml: str) -> DeployContext:
    # ✗ String matching on raw YAML
    has_frontend = "ui:" in raw_yaml or "frontend:" in raw_yaml
```

## Code Review Checklist

Before merging generator code, verify:

- [ ] No `raw_yaml`, `yaml_text`, or `yaml_str` parameters in generator functions
- [ ] No string operations on YAML content
- [ ] No regex patterns matching YAML structure
- [ ] All data comes from typed IR objects
- [ ] New features added to IR definition first
- [ ] Parser extracts data into IR
- [ ] Generator accesses only IR

## Historical Context

This principle was established after detecting the following antipattern:

```python
# Before (WRONG):
def build_deploy_context(ir: IRDocument, raw_yaml_text: str, ...) -> DeployContext:
    has_mongo_section = "mongo:" in raw_yaml_text  # ✗ String matching
    env_vars = sorted(set(_ENV_VAR_RE.findall(raw_yaml_text)))  # ✗ Regex on raw YAML

# After (CORRECT):
def build_deploy_context(ir: IRDocument, ...) -> DeployContext:
    mongo_local = ir.deploy.mongo_local  # ✓ Use IR data
    env_vars = list(ir.deploy.env_vars)  # ✓ Use IR data
```

## Enforcement

This architecture is enforced through:

1. **Type signatures**: Generator functions don't accept string/dict parameters that could be raw YAML
2. **Code review**: All PRs checked for YAML string operations in generators
3. **Documentation**: This file serves as the canonical reference

## Questions?

If you're unsure whether your code violates this principle, ask:

1. Am I parsing/searching/matching YAML structure?
2. Could this logic belong in the parser instead?
3. Is there an IR field that provides this information?

If yes to any of these, refactor to move the logic to the parser.
