# LSP-rust-analyzer

This is a helper package that starts the [rust-anallyzer](https://github.com/rust-analyzer/rust-analyzer) language server for you

To use this package, you must have:

- The [LSP](https://packagecontrol.io/packages/LSP) package.
- Rust syntax. Sublime Text 4 comes with one by default but for 3 and below use [RustEnhanced](https://packagecontrol.io/packages/Rust%20Enhanced)
- The rust analyzer binary installed (prefferably on path)

## Configuration

You can edit the global settings using:

```
Preferences: LSP-rust-analyzer Settings
```

You can also create a project specific configurations

## Installing Rust Analyzer

You can viw the rust analyzer Installation guide here: [Installation Guide](https://rust-analyzer.github.io/manual.html#rust-analyzer-language-server-binary)

Due to the frequent updates, this package does not manage the binary for you. Follow Instructions mentioned


## Applicable Selectors

This language server operates on views with the `source.rust` base scope.

