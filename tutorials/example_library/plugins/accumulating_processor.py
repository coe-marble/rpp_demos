"""A running total with typed lifecycle handover between native instances."""

from __future__ import annotations

import math

from rpp_plugin_types.example_library import ScalarAccumulator
from rpp_schema.example_library import AccumulatorState
from rpp_py.lifecycle import CallbackResult, DeactivationResult


class AccumulatingProcessor(ScalarAccumulator):
    def __init__(self):
        super().__init__()
        self._total = 0.0
        self._configured = False
        self._active = False

    def on_configure(self, context):
        self._total = 0.0
        self._active = False
        self._configured = True
        return CallbackResult()

    def on_activate(self, state: AccumulatorState | None = None) -> CallbackResult:
        if not self._configured:
            return CallbackResult.failure("configure the accumulator before activation")
        if state is not None:
            if not math.isfinite(state.total):
                return CallbackResult.failure("handover total must be finite")
            self._total = state.total
        self._active = True
        return CallbackResult()

    def on_deactivate(self) -> DeactivationResult[AccumulatorState]:
        self._active = False
        # Export an owned application value rather than a runtime/context object.
        return DeactivationResult(state=AccumulatorState(total=self._total))

    def on_cleanup(self):
        self._active = False
        self._configured = False
        self._total = 0.0
        return CallbackResult()

    def process(self, value: float) -> float:
        if not self._active:
            raise RuntimeError("accumulator is inactive")
        if not math.isfinite(value):
            raise ValueError("value must be finite")
        total = self._total + value
        if not math.isfinite(total):
            raise ValueError("total must be finite")
        self._total = total
        return total
