# LaunchLine (PyPI wrapper)

A lightweight launcher for interactive CLI tools.

This package is a **thin wrapper** that downloads and runs the pre-built native
binary from [GitHub Releases](https://github.com/mikejhill/launchline/releases).
The actual application is written in Rust for near-instant startup.

## Installation

```bash
pip install launchline
```

On first run, the native binary is downloaded and cached automatically.

## Usage

```bash
launchline
```

See the [main repository](https://github.com/mikejhill/launchline) for full
documentation, configuration, and development instructions.

## Supported Platforms

| OS      | Architecture |
| ------- | ------------ |
| Linux   | x64, ARM64   |
| macOS   | x64, ARM64   |
| Windows | x64, ARM64   |

## License

[MIT](https://github.com/mikejhill/launchline/blob/main/LICENSE)
