# Local installation by platform

Prompt2CST's Python app and planning path are designed for CPython 3.11 on
Windows, Linux and macOS. **Only Windows 11 x64 was exercised with a real
openEMS solver in this repository's acceptance runs.** The new Linux/macOS
scripts and Qt UI load path need validation on those hosts before they can be
called supported solver deployments. CST Studio 2026 automation remains
Windows-only because it uses COM.

| Task | Windows | Linux | macOS |
|---|---|---|---|
| Install Python app | `setup.bat` | `./setup.sh` | `./setup.sh` |
| Launch desktop UI | `Prompt2CST.bat` | `./launch.sh` | `./launch.sh` |
| Check modes | `.\.venv\Scripts\python.exe -m prompt2cst doctor` | `./.venv/bin/python -m prompt2cst doctor` | Same as Linux |
| Install native openEMS | Separate official package + matching Python bindings | Separate official build/package + bindings | Separate official source build + bindings |
| Build in CST | Approval-gated, with CST 2026 installed | Not available | Not available |

The app setup scripts do not install native openEMS or claim simulated results.
`doctor` checks the solver executable, both Python modules, and a separate
binding-import process. It does **not** run FDTD or test a CST licence. A
`READY` solver means you may attempt a simulation, not that any antenna will
pass its RF criteria.

## Windows

Install CPython 3.11 x64 and run `setup.bat`. For local simulation, follow the
[official Windows openEMS package and Python-interface instructions](https://docs.openems.de/en/latest/python/manual_install.html#windows)
and the [repository's Windows example](../README.md#free-local-openems-solver-setup).
Use wheels matching this app's CPython 3.11 virtual environment. Reopen the
app after changing environment variables, then use **Check setup**.

## Linux

Install CPython 3.11, `venv`, Bash and the OS packages needed by Qt. From a
terminal in the extracted repository:

```bash
./setup.sh
./launch.sh
```

For real FDTD, follow the [official openEMS build/install guide](https://docs.openems.de/en/latest/install/index.html)
and [Python binding installation guide](https://docs.openems.de/en/latest/python/install.html).
Install the bindings into Prompt2CST's `.venv`, or use a compatible environment
that contains this app, both bindings and the native solver. Confirm with
`./.venv/bin/python -m prompt2cst doctor` before simulation. Installing only
the Python app leaves planning and geometry generation available.

## macOS

Use CPython 3.11 and run `./setup.sh`, then `./launch.sh`. The
[official openEMS package guidance](https://docs.openems.de/en/latest/install/package.html#macos)
currently says its former Homebrew formula is broken/unmaintained; follow the
[official source-build and Python-binding instructions](https://docs.openems.de/en/latest/install/clone-build-install.html)
for a compatible native installation. That step is not automated or verified
by this repository. Run `doctor` afterward and only use the simulate action
when it reports solver readiness.

## Common first run

1. In the desktop app, enter a frequency, antenna family or use case, and an
   S11 target in the Requirements box.
2. Choose **Plan antenna · no key** for an artifact-backed plan, or
   **Generate openEMS geometry** for an inspectable solver input without a
   simulation.
3. Choose **Design + simulate · free openEMS** only when the readiness card
   says openEMS is ready. The result report must still pass its target and
   numerical checks; far-field and physical verification remain separate.
4. If setup fails, run `doctor --json` and keep that diagnostic with the
   platform, Python version and error message when reporting the issue.
