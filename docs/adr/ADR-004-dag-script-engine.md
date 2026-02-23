# ADR-004 — DAG-Based Automation Script Engine

**Status:** Accepted  
**Date:** 2024-03-10  
**Deciders:** Backend Team Lead, Product  

---

## Context

Sphere Platform needs an automation engine that allows users to define and execute
multi-step workflows across device fleets. Requirements:

1. Scripts must run across large device fleets (100–10,000 devices)
2. Steps within a script can have dependencies on other steps
3. Independent steps should execute in parallel (wave batches)
4. Execution must be fault-tolerant: a failure on some devices should not block others
5. Users need real-time progress visibility

---

## Decision Drivers

- **Parallelism**: independent steps on different devices should run simultaneously
- **Dependency management**: step B should only run after step A completes
- **Fleet scale**: batch execution across thousands of devices efficiently
- **Observability**: per-step, per-device execution results
- **Simplicity of definition**: non-developers should understand the schema

---

## Considered Options

### Option A — Sequential script (step list)

Simple ordered list of steps executed one after another on each device.

**Pros:**
- Very simple to implement and understand

**Cons:**
- No parallelism — a 10-step script takes 10× longer than necessary
- Cannot model "run step C only if step A and step B succeed"
- Inefficient for fleet-wide operations

### Option B — DAG (Directed Acyclic Graph) schema

Scripts are defined as a DAG where nodes are steps and edges represent dependencies.

Each node specifies:
- `id`: unique step identifier
- `action`: command type (adb_exec, screenshot, vpn_connect, etc.)
- `params`: action-specific parameters
- `depends_on`: list of step IDs that must complete before this step runs
- `on_failure`: `continue` | `abort` | `retry`

Execution proceeds in **waves**: all steps with no unmet dependencies form a wave
and execute in parallel. After a wave completes, the next wave is formed.

**Example DAG:**
```
install_app  ──┐
               ├─► verify_install ──► launch_app
take_screenshot─┘
```

**Pros:**
- Natural parallelism: independent steps run concurrently
- Explicit dependency modeling
- Wave-batch execution maps well to Celery `group()` + `chord()`
- Fan-out to devices within each wave uses Celery `group()` for parallel execution

**Cons:**
- More complex schema validation (must detect cycles)
- Harder to debug when DAG topology is wrong
- Users need to understand the DAG concept

### Option C — YAML-defined workflow (n8n / Airflow style)

Import industry-standard workflow format.

**Pros:**
- Familiar to DevOps engineers
- Many existing tools for editing

**Cons:**
- Overkill for our use case — our "steps" are simple device commands, not general compute
- Integration complexity with our RBAC and multi-tenant model
- Vendor lock-in risk (n8n integration is already a separate layer above scripts)

---

## Decision

**Chosen: Option B — DAG-based script engine**

The DAG model maps directly onto our Celery execution model using `group()` for
parallel wave execution and `chord()` for synchronization. The schema is
expressive enough for real use cases while remaining approachable:
most scripts are simple linear chains or simple fan-out patterns.

Cycle detection is implemented using Kahn's algorithm at script-save time,
preventing invalid scripts from entering the execution queue.

---

## Consequences

### Positive

- A 5-step linear script runs in the time of 1 step (if all steps can parallelize)
- Fleet execution: a wave can dispatch to 1,000 devices simultaneously via Celery `group()`
- Step isolation: a failure in one branch does not abort independent branches
  (configurable via `on_failure: continue`)
- Results stored per-step, per-device — fine-grained progress reporting
- Real-time progress delivered to frontend via SSE (Server-Sent Events)

### Negative / Trade-offs

- Script definition is more complex than a simple ordered list
- Users must understand `depends_on` semantics
- Wave execution adds scheduling overhead (Celery chord synchronization barrier)
- Cycle detection must run on every script save/update

### Wave Batch Execution

```
Script DAG
  Wave 1: [step_a, step_b]   → dispatch to all devices in parallel
                └─ [step_c]  → dispatch after wave 1 completes
  Wave 2: [step_c, step_d]   → dispatch to all devices in parallel
```

Each device-step pair creates one Celery task. For 100 devices × 10 steps = 1,000
Celery tasks per script execution.

---

## Links

- [backend/services/script_engine.py](../../backend/services/script_engine.py)
- [docs/architecture.md — Script Engine / DAG](../architecture.md#script-engine--dag-execution)
- [TZ-04-Script-Engine/SPLIT-1-DAG-Schema.md](../../TZ-04-Script-Engine/SPLIT-1-DAG-Schema.md)
- [TZ-04-Script-Engine/SPLIT-4-Wave-Batch.md](../../TZ-04-Script-Engine/SPLIT-4-Wave-Batch.md)
