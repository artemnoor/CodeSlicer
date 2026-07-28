# C#/.NET plugin architecture

The C# implementation is local-first and split into one language provider plus
framework packs:

- `plugins/languages/csharp` parses `.cs` declarations, namespaces, usings,
  members, direct unique-name calls, project references, NuGet references and
  xUnit/NUnit/MSTest attributes. It emits stable `file:`, `class:`,
  `method:`, `test:` and `project:` IDs with source evidence.
- `framework.csharp.aspnetcore` owns MVC/minimal-API route rules.
- `framework.csharp.dotnet-di` owns explicit `AddSingleton`, `AddScoped`,
  `AddTransient` and service-provider uncertainty.
- `framework.csharp.mediatr` owns request/handler declarations.
- `framework.csharp.entityframework` owns `DbContext`/`DbSet<TEntity>`
  schema-boundary facts.
- `framework.csharp.dotnet-tests` owns feature-level test coverage metadata.

Each pack is selected only from local imports or `.csproj` package references.
Hooks run through the existing local-only process boundary. They may read the
project and return graph contributions, but no network, package restore, or
external telemetry is available.

The fallback parser intentionally reports `limited` coverage. Literal syntax,
unique local references and explicit project references can be `confirmed`;
heuristic framework bindings are `likely`; overload resolution, source
generators, reflection, dynamic route composition and compiler diagnostics are
not fabricated. `review` therefore keeps C# warnings/coverage visible and
does not turn missing Roslyn into a false LOW-risk result.
