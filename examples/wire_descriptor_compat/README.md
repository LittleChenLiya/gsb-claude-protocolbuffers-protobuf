# Binary FileDescriptorSet compatibility demo

These fixtures are serialized `FileDescriptorSet` messages, not `.proto`
source files. Regenerate them with:

```sh
python examples/wire_descriptor_compat/create_wire_compat_fixtures.py
```

Run the report with:

```sh
python examples/wire_descriptor_compat/demo.py
# or: bazel run //examples/wire_descriptor_compat:demo
```

Run the checker tests with:

```sh
bazel test //python:descriptor_compat_test
```

The report is intentionally limited to binary wire-read compatibility. It does
not claim JSON, generated-code, API, semantic, or business compatibility.
