# Local Paper Library

These papers are open-access copies downloaded from arXiv on 2026-10-16. The arXiv abstract page remains the canonical source for versions and metadata.

| File | Paper | Canonical page | Used on | SHA-256 |
|---|---|---|---|---|
| `lora-2106.09685.pdf` | LoRA: Low-Rank Adaptation of Large Language Models | https://arxiv.org/abs/2106.09685 | Day 2 | `E9A0D3128767DB616085DC0F4E6E455E672E89AF823E8ED1282793682787395A` |
| `pets-2203.04810.pdf` | PetS: A Unified Framework for Parameter-Efficient Transformers Serving | https://arxiv.org/abs/2203.04810 | Days 2–3 | `4B4A110F816AF925AB8ED920D6F2FE6F8FE3F7343C6F6DAF8CE8B42B49B730B2` |
| `punica-2310.18547.pdf` | Punica: Multi-Tenant LoRA Serving | https://arxiv.org/abs/2310.18547 | Days 3–4 | `1D015550E7C3C13FC2574FD2CDFA48B343A5B6D02F2BF8607C2E568D7A619944` |
| `s-lora-2311.03285.pdf` | S-LoRA: Serving Thousands of Concurrent LoRA Adapters | https://arxiv.org/abs/2311.03285 | Days 3–4 | `C8D93E5A2525D3139D4994740A0057A8F447A568C5A31613976C9FD254867DB7` |

## Integrity check

From PowerShell:

```powershell
Get-FileHash .\curriculum\papers\*.pdf -Algorithm SHA256
```

If a canonical paper receives a new revision, add the revision date and new checksum rather than silently replacing evidence used for a prior decision.

