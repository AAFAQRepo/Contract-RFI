#!/usr/bin/env python3
"""Apply docling patches for Falcon-OCR compatibility with transformers v5+."""

import sys

filepath = (
    "/opt/venv/lib/python3.12/site-packages/docling/models/"
    "inference_engines/vlm/transformers_engine.py"
)

with open(filepath, "r") as f:
    content = f.read()

# Patch 1: eager attention for Falcon-OCR
old_attn = '''            _attn_implementation=(
                "flash_attention_2"
                if self.device.startswith("cuda")  # type: ignore[union-attr]
                and self.accelerator_options.cuda_use_flash_attention2
                else "sdpa"
            ),'''

new_attn = '''            _attn_implementation=(
                "flash_attention_2"
                if self.device.startswith("cuda")  # type: ignore[union-attr]
                and self.accelerator_options.cuda_use_flash_attention2
                else "eager" if "falcon" in repo_id.lower() else "sdpa"
            ),'''

if old_attn not in content:
    print("ERROR: Could not find attention implementation block to patch")
    sys.exit(1)

content = content.replace(old_attn, new_attn)
print("Patch 1 applied: eager attention for Falcon-OCR")

# Patch 2: handle missing generation_config.json
old_gen = '''        # Load generation config
        self.generation_config = GenerationConfig.from_pretrained(
            artifacts_path, revision=revision
        )'''

new_gen = '''        # Load generation config
        try:
            self.generation_config = GenerationConfig.from_pretrained(
                artifacts_path, revision=revision
            )
        except OSError:
            _log.warning(f"No generation_config.json found for {repo_id}, using default generation config")
            self.generation_config = GenerationConfig()'''

if old_gen not in content:
    print("ERROR: Could not find generation config block to patch")
    sys.exit(1)

content = content.replace(old_gen, new_gen)
print("Patch 2 applied: graceful handling of missing generation_config.json")

with open(filepath, "w") as f:
    f.write(content)

print("All docling Falcon-OCR patches applied successfully")
