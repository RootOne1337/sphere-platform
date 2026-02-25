# ADR-005 — Use Hilt for Android Agent Dependency Injection

**Status:** Accepted  
**Date:** 2024-03-20  
**Deciders:** Android Team Lead  

---

## Context

The Sphere Android Agent is a long-lived background service that manages:
- WebSocket client connection
- ADB command execution
- VPN tunnel management (AmneziaWG)
- H.264 screen capture and streaming pipeline
- OTA update mechanism

Multiple components depend on shared services (WebSocket client, configuration,
device info). Wiring these manually leads to spaghetti initialization code and
makes testing difficult.

---

## Decision Drivers

- **Testability**: components must be mockable in unit/integration tests
- **Lifecycle management**: Android components have complex lifecycles (Activity,
  Service, ViewModel) — DI framework must handle scope correctly
- **Google-recommended**: the chosen solution should follow Android Jetpack guidance
  to ease onboarding
- **Build-time safety**: prefer compile-time validation over runtime injection failures

---

## Considered Options

### Option A — Manual dependency injection (constructor injection)

Pass dependencies via constructors. No framework.

**Pros:**
- Zero framework overhead
- Trivially understood

**Cons:**
- `SphereAgentService` constructor would need 10+ parameters
- No lifecycle awareness — must manually scope dependencies
- `Application`-level singletons require boilerplate `companion object` factories
- Painful to refactor as dependency graph grows

### Option B — Dagger 2

The annotation-processor-based DI framework that Hilt is built on.

**Pros:**
- Compile-time validation
- Maximum performance (generated code, no reflection)
- Highly configurable

**Cons:**
- Extremely verbose — requires manually defining `@Component`, `@Subcomponent`,
  `@Module` for every scope
- Steep learning curve
- High boilerplate-to-value ratio for a focused background service app

### Option C — Hilt (Dagger wrapper for Android)

Hilt is Google's opinionated Dagger wrapper, standardizing DI in Android apps.
It provides:
- `@HiltAndroidApp` → application-level component
- `@AndroidEntryPoint` → automatic injection in Services, Activities, Fragments
- Standard scopes: `@Singleton`, `@ActivityScoped`, `@ServiceScoped`
- `@InstallIn(SingletonComponent::class)` modules

**Pros:**
- Compile-time validation (inherits from Dagger)
- Minimal boilerplate — no manual Component definitions
- `@HiltViewModel` integrates with Jetpack ViewModel lifecycle
- `@TestInstallIn` makes test overrides straightforward
- Officially recommended by Google / Android Jetpack

**Cons:**
- Requires `kapt` (or `ksp`) annotation processing — adds to build time
- Hilt abstracts some Dagger details, making it harder to debug exotic scope issues
- Requires `@HiltAndroidApp` on Application class (minor coupling)

### Option D — Koin

Kotlin-based service locator / DI framework.

**Pros:**
- No annotation processing — pure Kotlin DSL
- Fast setup

**Cons:**
- Runtime failures (not compile-time) if bindings are misconfigured
- Service-locator semantics make dependencies implicit (not injected via constructor)
- Less integrated with Android lifecycle than Hilt

---

## Decision

**Chosen: Option C — Hilt**

Hilt provides the right trade-off: compile-time safety, Android lifecycle integration,
minimal boilerplate, and official Google support. The annotation processing build-time
cost is acceptable for a project with a relatively small Kotlin codebase.

The agent's dependency graph is straightforward:
- `WebSocketClient` → `@Singleton`
- `AdbBridge` → `@Singleton`
- `VpnManager` → `@Singleton`
- `StreamingPipeline` → `@ServiceScoped` (exists only while streaming)
- `ConfigRepository` → `@Singleton`

---

## Consequences

### Positive

- `SphereAgentService` is annotated `@AndroidEntryPoint` — fields injected automatically
- Adding a new dependency requires only `@Inject constructor(...)` — no manual wiring
- Test overrides via `@TestInstallIn` + `@ReplaceWith` replace real implementations cleanly
- Compile-time component graph validation catches missing bindings before runtime

### Negative / Trade-offs

- `kapt` (or `ksp`) annotation processors add ~15–20 seconds to clean builds
- Hilt wraps Dagger; advanced Dagger patterns require understanding both layers
- All Android entry points must be annotated with `@AndroidEntryPoint` — easy to forget

### Module Organization

```
di/
  AppModule.kt          — Application singletons (WebSocketClient, ConfigRepository)
  AdbModule.kt          — ADB bridge and device enumeration
  VpnModule.kt          — AmneziaWG manager and config provider
  StreamingModule.kt    — MediaProjection, MediaCodec encoder (ServiceScoped)
  NetworkModule.kt      — OkHttp client, Retrofit (for OTA API)
```

---

## Links

- [android/app/src/main/java/.../di/](../../android/app/)
- [Hilt documentation](https://dagger.dev/hilt/)
- [docs/android-agent.md](../android-agent.md)
- [ADR-001: FastAPI choice](ADR-001-fastapi-over-django.md)
