"""Pilot LoRA fine-tune for *prompt extraction*, never antenna performance.

Run in a separate GPU training environment. The synthetic examples come from
prompt2cst.local_ai_dataset; faculty measurements are intentionally not used.
The script compares a held-out set before and after training, saves the LoRA
adapter, and exports merged Safetensors for an optional Ollama import.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

from prompt2cst.local_ai_dataset import SYSTEM_INSTRUCTION, ExtractionExample, build_pilot_dataset


def _prefix(prompt: str) -> str:
    return f"{SYSTEM_INSTRUCTION}\nUser request: {prompt}\nJSON: "


def _score(model, tokenizer, examples: list[ExtractionExample], torch) -> dict[str, object]:
    model.eval()
    correct = 0
    valid_json = 0
    errors: list[dict[str, object]] = []
    with torch.inference_mode():
        for example in examples:
            encoded = tokenizer(_prefix(example.prompt), return_tensors="pt").to("cuda")
            generated = model.generate(
                **encoded, max_new_tokens=72, do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
            response = tokenizer.decode(
                generated[0, encoded.input_ids.shape[1]:], skip_special_tokens=True
            ).strip()
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict) and set(parsed) == {
                "family", "frequency_hz", "target_s11_db",
            }:
                valid_json += 1
                if parsed == example.expected():
                    correct += 1
            if parsed != example.expected():
                errors.append({
                    "prompt": example.prompt,
                    "expected": example.expected(),
                    "response": response[:500],
                })
    return {
        "examples": len(examples),
        "valid_json": valid_json,
        "exact": correct,
        "exact_accuracy": correct / len(examples),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model-id", default="Qwen/Qwen3-0.6B")
    parser.add_argument("--steps", type=int, default=60)
    parser.add_argument("--gradient-accumulation", type=int, default=4)
    args = parser.parse_args()
    if args.steps < 1 or args.steps > 500:
        parser.error("--steps must be 1..500")
    if args.gradient_accumulation < 1 or args.gradient_accumulation > 16:
        parser.error("--gradient-accumulation must be 1..16")
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(root / "hf-cache"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for this bounded local pilot")
    torch.manual_seed(42)
    train, evaluation = build_pilot_dataset()
    (root / "dataset_manifest.json").write_text(json.dumps({
        "source": "synthetic_prompt_templates_from_prompt2cst",
        "faculty_dataset_used": False,
        "train_examples": len(train),
        "holdout_examples": len(evaluation),
        "purpose": "extract explicit antenna requirements only; no RF performance targets are labels",
        "model_id": args.model_id,
    }, indent=2) + "\n", encoding="utf-8")

    tokenizer = AutoTokenizer.from_pretrained(args.model_id)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model = AutoModelForCausalLM.from_pretrained(args.model_id, dtype=dtype)
    model.to("cuda")
    print(f"GPU: {torch.cuda.get_device_name(0)}; dtype: {dtype}; train={len(train)}; holdout={len(evaluation)}", flush=True)
    baseline = _score(model, tokenizer, evaluation, torch)
    print(f"Baseline exact: {baseline['exact']}/{baseline['examples']}", flush=True)

    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=8, lora_alpha=16, lora_dropout=0.05,
        target_modules=["q_proj", "v_proj"],
    ))
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=2e-4,
    )
    random.Random(42).shuffle(train)
    optimizer.zero_grad(set_to_none=True)
    losses: list[float] = []
    microsteps = args.steps * args.gradient_accumulation
    for microstep in range(microsteps):
        example = train[microstep % len(train)]
        prefix_ids = tokenizer(_prefix(example.prompt), add_special_tokens=False).input_ids
        answer_ids = tokenizer(
            example.completion() + tokenizer.eos_token, add_special_tokens=False
        ).input_ids
        token_ids = prefix_ids + answer_ids
        labels = [-100] * len(prefix_ids) + answer_ids
        inputs = torch.tensor([token_ids], dtype=torch.long, device="cuda")
        targets = torch.tensor([labels], dtype=torch.long, device="cuda")
        model.train()
        loss = model(input_ids=inputs, labels=targets).loss
        (loss / args.gradient_accumulation).backward()
        losses.append(float(loss.detach().cpu()))
        if (microstep + 1) % args.gradient_accumulation == 0:
            torch.nn.utils.clip_grad_norm_(
                (parameter for parameter in model.parameters() if parameter.requires_grad), 1.0
            )
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            step = (microstep + 1) // args.gradient_accumulation
            if step % 10 == 0 or step == args.steps:
                print(f"step {step}/{args.steps}: loss={sum(losses[-10:])/min(10, len(losses)):.4f}", flush=True)

    model.config.use_cache = True
    tuned = _score(model, tokenizer, evaluation, torch)
    print(f"Tuned exact: {tuned['exact']}/{tuned['examples']}", flush=True)
    accepted = (
        tuned["exact"] > baseline["exact"]
        and tuned["exact_accuracy"] >= 0.8
    )
    report = {
        "model_id": args.model_id,
        "steps": args.steps,
        "gradient_accumulation": args.gradient_accumulation,
        "baseline": baseline,
        "tuned": tuned,
        "pilot_only": True,
        "trained_on_faculty_data": False,
        "accepted_for_ollama_import": accepted,
    }
    (root / "evaluation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    adapter = root / "antenna-parser-lora"
    model.save_pretrained(adapter)
    tokenizer.save_pretrained(adapter)
    print(f"Saved adapter: {adapter}", flush=True)
    if not accepted:
        print("Pilot did not improve and reach 80% holdout accuracy; not exporting a deployable merged model.", flush=True)
        return 2
    model.gradient_checkpointing_disable()
    merged = model.merge_and_unload()
    merged_dir = root / "antenna-parser-merged"
    merged.save_pretrained(merged_dir, safe_serialization=True)
    tokenizer.save_pretrained(merged_dir)
    print(f"Saved merged model: {merged_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
