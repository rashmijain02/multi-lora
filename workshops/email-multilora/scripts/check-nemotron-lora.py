import json

import mlx.core as mx
import mlx.optimizers as optim
from huggingface_hub import hf_hub_download
from mlx import nn
from mlx.utils import tree_flatten
from mlx_lm.models.nemotron_h import Model, ModelArgs
from mlx_lm.tuner.utils import linear_to_lora_layers

config_path = hf_hub_download(
    "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16",
    "config.json",
    local_files_only=True,
)
with open(config_path) as config_file:
    config = json.load(config_file)
config.update(
    vocab_size=128,
    hidden_size=64,
    intermediate_size=128,
    num_hidden_layers=4,
    num_attention_heads=4,
    num_key_value_heads=2,
    head_dim=16,
    mamba_num_heads=4,
    mamba_head_dim=16,
    ssm_state_size=16,
    n_groups=1,
    hybrid_override_pattern=["M", "*", "-", "M"],
)
mx.random.seed(0)
model = Model(ModelArgs.from_dict(config))
model.set_dtype(mx.bfloat16)
model.freeze()
linear_to_lora_layers(model, 4, {"rank": 4, "scale": 8.0, "dropout": 0.0})
tokens = mx.array([[1, 2, 3, 4]])
targets = mx.array([[2, 3, 4, 5]])


def loss_function(current_model):
    return nn.losses.cross_entropy(current_model(tokens), targets, reduction="mean")


loss, gradients = nn.value_and_grad(model, loss_function)(model)
mx.eval(loss, gradients)
gradient_values = [value for _, value in tree_flatten(gradients)]
if not gradient_values or not all(bool(mx.all(mx.isfinite(value))) for value in gradient_values):
    raise SystemExit("FAIL: missing or nonfinite LoRA gradients")
if not any(bool(mx.any(value != 0)) for value in gradient_values):
    raise SystemExit("FAIL: all LoRA gradients are zero")
optimizer = optim.Adam(learning_rate=1e-4)
optimizer.update(model, gradients)
mx.eval(model.parameters(), optimizer.state)
print(json.dumps({
    "status": "ok",
    "check": "tiny random Nemotron-H BF16 LoRA backward and optimizer step",
    "loss": float(loss),
    "trainable_tensors": len(gradient_values),
    "full_checkpoint_training_verified": False,
}, indent=2))