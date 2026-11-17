"""Script slot declarations and application logic for a scalar pipeline."""


class ScalarPipeline:
    # Slots declare contracts, not concrete plugin implementations.
    COMPONENTS = {
        "processor": "example_library::ScalarProcessor",
        "accumulator": "example_library::ScalarAccumulator",
    }

    def run(self, context, values):
        # The caller supplies a configured script context with active components.
        processor = context.get_subcomponent_instance("processor")
        accumulator = context.get_subcomponent_instance("accumulator")
        totals = []
        for value in values:
            transformed = processor.process(value)
            total = accumulator.process(transformed)
            print(f"input={value:g}, transformed={transformed:g}, total={total:g}")
            totals.append(total)
        return totals
