# textpipe

Composable text-cleaning pipelines built from cooperative mixin stages. Each
stage class contributes one step name through `steps()` and calls `super()` so
stages can be mixed freely; `Pipeline.run()` applies the steps in order.

```
python3 -m textpipe list
python3 -m textpipe steps export
python3 -m textpipe run export "  Call me at 555-0100, call me at 555-0100  "
```

`steps <name>` prints the step names of a pipeline joined with ` > `.

Run the tests with `python3 -m unittest discover -s tests -v`.
