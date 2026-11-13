# Tutorial 6 Lifecycle management

The runtime owns transitions; the plugin owns its coefficients and active flag.
[run.py](run.py) uses the public runtime handle to exercise both.

Use the [shared prerequisites](../../README.md#prerequisites-and-execution):

```bash
python3 tutorials/06_lifecycle/run.py
```

The successful path is:

```text
UNCONFIGURED -> configure -> INACTIVE -> activate -> ACTIVE
ACTIVE -> deactivate -> INACTIVE -> activate -> ACTIVE
ACTIVE -> deactivate -> INACTIVE -> cleanup -> UNCONFIGURED
```

Each transition prints its result and `context.is_active()`. Look for
`active = 7` and `reactivated = 7`. This processor is stateless: reactivation
retains configured coefficients and carries no estimate or history. Calls
before activation and after deactivation fail with `processor is inactive`,
including through a retained native reference.

Activation before configuration is rejected. Another component fails
configuration because of an invalid gain and enters `ERROR`; activation is
rejected there too. Cleanup returns it to `UNCONFIGURED`. The driver closes it,
corrects the saved settings, and constructs a new runtime to read them.
Look for `recovered = 7`.

Finally, a non-finite input causes an invocation error. A `finally` block
closes the recovered runtime, deactivating it and clearing its configuration.
The retained plugin reference then rejects calls. Invocation failure does not
automatically imply a lifecycle transition: the application owns shutdown.
All remaining runtimes and temporary data are cleaned up on exit.
