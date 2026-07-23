$ErrorActionPreference = "Stop"

# Backwards-compatible entry point for existing Prompt2CST users.
& (Join-Path $PSScriptRoot "setup.ps1") @args
