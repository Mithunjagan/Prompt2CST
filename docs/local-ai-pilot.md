# Local Ollama and LoRA pilot (2026-09-24)

Ollama 0.34.3 and its `qwen3:0.6b` model are installed under `D:\Prompt2CST-LocalAI` on the audited Windows laptop. The Ollama server was configured for `127.0.0.1:11434` with cloud access disabled and model storage on D:. A short API inference returned the expected reply with `options.num_gpu=0`. The default Ollama GPU inference path stalled on this machine, so GPU serving is **not** validated. The desktop app now has an opt-in, advisory-only local model check and can start the configured local executable when needed; the rejected fine-tuned adapter remains disconnected.

A separate Python 3.11 environment on D: has CUDA PyTorch 2.8.0, Transformers 4.57.6, PEFT 0.21.0, and Accelerate 1.15.0. PyTorch detected the RTX 3050 and completed a 60-step LoRA fine-tune of `Qwen/Qwen3-0.6B`. The adapter and full evaluation report are outside the repository under `D:\Prompt2CST-LocalAI\pilot`; no faculty measurements were used as language-model answers.

| Pilot measure | Untuned base | LoRA pilot |
| --- | ---: | ---: |
| Exact JSON requirements on 33 held-out synthetic prompts | 0 | 11 |
| Valid JSON with expected keys | 0 | 33 |

The tuned model failed the predeclared acceptance gate of at least 80% exact match and improvement over baseline. It was **not** merged, imported into Ollama, or connected to the antenna-design path. Twenty of its 22 errors were 10× mistakes converting held-out 470/920 MHz requests into hertz. The remaining two were unsupported-family/unspecified-family errors. These are reasons to keep numerical unit conversion and capability validation deterministic; they are not RF simulation results.

The repository's deterministic prompt parser now handles MHz/megahertz and GHz/gigahertz explicitly, including ranges. It also rejects known research-only antenna families and ambiguous named families before project creation. The optional Ollama check asks the base model for a family label and verbatim quote, accepts only an independently recognizable quote for the same supported family, and never changes numeric requirements or geometry. A live 868 MHz PIFA CLI dry-run confirmed localhost inference while retaining 868,000,000 Hz and a PIFA plan; it did not run an EM solver. A second isolated-port test confirmed the app can start the configured Ollama executable itself; that model reply was invalid and safely ignored. Before considering a new fine-tune, evaluate on substantially more diverse independent prompts. Validated DesignIR, solver results, approval, and human review remain separate gates.
