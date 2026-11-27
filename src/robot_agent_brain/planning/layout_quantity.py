"""Bounded quantity alternatives; never infer authorization or asset ratios."""
from ..contracts.arrangement import ArrangementSpec


def quantity_candidates(spec):
    yield spec
    items = spec.items
    if (items.count_mode != "auto" or not items.auto_count
            or items.min_count is None or spec.operation not in {"create", "append"}):
        return
    # Explicit per-asset totals and a literal sequence must remain unchanged.
    # Only a single repeated asset or explicitly cycling pattern can vary.
    if items.mode != "single" and not (
            items.mode == "sequence" and spec.pattern.kind in {"alternating", "checker"}):
        return
    counts = sorted(range(items.min_count, items.max_count + 1),
                    key=lambda count: (abs(count - items.requested_count), count))
    for count in counts:
        if count == items.requested_count:
            continue
        if (spec.pattern.kind in {"grid", "checker"} and spec.pattern.rows and spec.pattern.cols
                and count > spec.pattern.rows * spec.pattern.cols):
            continue
        data = spec.model_dump(mode="json")
        data["items"]["requested_count"] = count
        if items.mode == "single":
            data["items"]["assets"][0]["count"] = count
        yield ArrangementSpec.model_validate(data)
