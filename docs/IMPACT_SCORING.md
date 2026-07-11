# Impact Scoring

Impact Engine uses a small, transparent heuristic layer to rank impact results
and explain how much confidence to place in a path. It does not replace the
graph, semantic resolver, or evidence model.

## Impact score

```text
ImpactScore(v) = Criticality(v) * Confidence(path) * Decay^distance
```

`Criticality` is a configurable priority for the node kind, `Confidence(path)`
is the confidence of the complete evidence path, `distance` is the traversal
distance from the changed node, and `Decay` is the configurable distance decay.
The default decay is `0.85`. It is a product configuration value, not a UI
constant.

## Chain confidence

```text
Confidence(path) = (product(Confidence(edge_i)))^(1/n)
```

The geometric mean avoids making every longer, well-supported chain look weak
only because it contains more edges. A path is still marked ambiguous or in
need of review when any edge carries those diagnostics.

The UI uses the labels `Подтверждена`, `Высокая вероятность`, `Требует
проверки`, and `Неоднозначна`. The detailed formula is available in the JSON
result and technical views rather than being repeated on every graph card.

## Context reduction

When both measurements are available:

```text
TokenSaving = 1 - Tokens_selected_context / Tokens_full_repository
```

CLI example:

```powershell
impact-engine impact graph.json --symbol OrderService.create_order `
  --full-context-tokens 128000 --selected-context-tokens 41000 --json
```

Without both measured values, the result reports only `Потенциальное
сокращение передаваемого контекста` and does not invent a percentage.

## Calibration note

Текущая модель скоринга является интерпретируемой эвристикой. Коэффициенты
могут калиброваться по историческим изменениям, тестовым результатам и
пользовательской обратной связи. До появления размеченного ground truth эти
коэффициенты не следует трактовать как научно доказанную вероятность риска.
