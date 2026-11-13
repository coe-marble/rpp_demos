"""A stateless transform with explicit lifecycle and instance configuration."""

from __future__ import annotations

import math

from rpp_plugin_types.example_library import ScalarProcessor
from rpp_py.lifecycle import CallbackResult
from rpp_py.plugin import ParameterDescription


class AffineProcessor(ScalarProcessor):
    PARAMETERS = [
        ParameterDescription("gain", 1.0),
        ParameterDescription("offset", 0.0),
    ]

    def __init__(self):
        super().__init__()
        self._coefficients = None
        self._active = False

    def on_configure(self, context):
        self._active = False
        self._coefficients = None
        values = []
        for name in ("gain", "offset"):
            value = context.get_parameter(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return CallbackResult.failure(f"{name} must be a finite number")
            try:
                value = float(value)
            except (OverflowError, ValueError):
                return CallbackResult.failure(f"{name} must be a finite number")
            if not math.isfinite(value):
                return CallbackResult.failure(f"{name} must be a finite number")
            values.append(value)
        # Commit only after both parameters have been validated.
        self._coefficients = tuple(values)
        return CallbackResult()

    def on_activate(self):
        if self._coefficients is None:
            return CallbackResult.failure("configure the processor before activation")
        self._active = True
        return CallbackResult()

    def on_deactivate(self):
        self._active = False
        return CallbackResult()

    def on_cleanup(self):
        self._active = False
        self._coefficients = None
        return CallbackResult()

    def process(self, value: float) -> float:
        # A native instance reference does not itself enforce the manager's
        # call gate. This plugin also protects calls through retained references.
        if not self._active:
            raise RuntimeError("processor is inactive")
        if not math.isfinite(value):
            raise ValueError("value must be finite")
        gain, offset = self._coefficients
        result = gain * value + offset
        if not math.isfinite(result):
            raise ValueError("result must be finite")
        return result
