# LSP-rust-analyzer

This is a helper package that starts the [rust-analyzer](https://github.com/rust-analyzer/rust-analyzer) language server for you
=======

Rust language server provided through [rust-analyzer](https://github.com/rust-analyzer/rust-analyzer).

## Installation

1. Install [LSP](https://packagecontrol.io/packages/LSP) and [LSP-rust-analyzer](https://packagecontrol.io/packages/LSP-rust-analyzer) via Package Control.
2. Make sure that you have the rust analyzer LSP server installed. Follow its [Installation Guide](https://rust-analyzer.github.io/manual.html#rust-analyzer-language-server-binary).
3. Optionally install the [RustEnhanced](https://packagecontrol.io/packages/Rust%20Enhanced) syntax. Sublime Text 4 ships with Rust syntax already so only install RustEnhanced if it provides additional benefit to you.

## Configuration

You can edit the global settings by opening the `Preferences: LSP-rust-analyzer Settings` from the Command Palette.

You can also have a project-specific configuration. Run the `Project: Edit Project` from the Command Palette and edit the following in the `settings` object.

```jsonc
{
    // folders: [
    //   ...
    // ]
    "settings": {
        "LSP": {
            "rust-analyzer": {
                "settings": {
                    //Setting-here
                }
            }
        }
    }
}
```

## Applicable Selectors

This language server operates on views with the `source.rust` base scope.

## Custom Command Palette Commands

### LSP-rust-analyzer: Open Docs Under Cursor

Opens the URL to documentation for the symbol under the cursor, if available.

### LSP-rust-analyzer: Reload Project

Reloads the project metadata, i.e. runs `cargo metadata` again.
