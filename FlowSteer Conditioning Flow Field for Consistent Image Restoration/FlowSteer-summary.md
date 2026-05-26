# FlowSteer: Conditioning Flow Fields for Consistent Image Restoration

> **Paper**: FlowSteer — arXiv:2512.08125v1 (Purdue / HKUST / Texas A&M, Dec 2025)
> **Base Model**: FLUX-dev (Rectified Flow Transformer)
> **Key Claim**: Training-free, zero-shot image restoration using one model for all tasks

---

## The Problem — A Real-World Story

Meet **Alex**, a specialist at a museum archive. His job is to restore old, damaged photographs — things like:

- Black-and-white photos that need colorizing
- Blurry images that need sharpening
- Grainy, noisy scans that need cleaning up
- Tiny low-resolution thumbnails that need blowing up to full size

For years, Alex's team used **separate AI models** for each task. One model for colorizing. A different one for deblurring. Another for super-resolution. Each one took months to train on thousands of examples. And if they ever got a new type of damage — say, a specific kind of lens blur — they had to start from scratch.

Then a bigger problem appeared: the modern AI image models (like FLUX, Stable Diffusion) were *incredibly* good at generating photorealistic images from text — but nobody could figure out how to make them do restoration properly. When you tried to use them for restoration, they'd change the person's face, invent new details, or completely lose what made the original photo unique.

**The core tension**: Generative AI wants to "be creative." Restoration requires "be faithful to the original."

---

## The Solution — A Real-World Story

The FlowSteer team realized something nobody had noticed before:

> "Flow-based AI models are like a car traveling from noise to a finished image. In the early part of the trip, the road is too bumpy to steer — you'll veer off course. But in the middle of the trip, the road smooths out just enough that you can gently nudge the wheel without crashing."

So they built **FlowSteer** — a **scheduler** (a timing controller) that watches the model generate an image step by step, and only applies "reality checks" during a specific window (roughly steps 15–27 out of 30). 

At each of those scheduled steps, FlowSteer does this:
1. Peek at what the image looks like right now (decode latent → pixels)
2. Check: *"Does this still match the original degraded photo?"*
3. Apply a mathematical correction (pseudo-inverse operator A†) to pull it back toward faithfulness
4. Continue generating

The result: FLUX-dev produces its beautiful, rich, photorealistic quality — but the final image is **provably faithful** to the input. Same face. Same scene. Just sharp, colorized, and clean.

**One model. No retraining. Works for all four restoration tasks.**

---

## Architecture — ASCII Diagram

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                         INPUT: DEGRADED IMAGE (y)                           ║
║                    (blurry / noisy / B&W / low-resolution)                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │    VAE ENCODER      │  ← Compresses image
                          │   (FLUX built-in)   │    into latent space
                          └──────────┬──────────┘    (16× smaller)
                                     │
                        ┌────────────▼────────────┐
                        │                         │
              ┌─────────▼──────────┐   Source prompt C1:
              │   FLOW INVERSION   │   "A blurry image of a cat..."
              │                    │
              │   FLUX-dev Model   │◄── C1 (source description)
              │   (30 steps)       │
              │                    │
              │  inverts image     │
              │  → noise latent    │
              └─────────┬──────────┘
                        │           │
                        │    ┌──────▼──────────────────┐
                        │    │  CACHED ATTENTION MAPS  │
                        │    │  (layout / structure    │
                        │    │   guidance stored here) │
                        │    └──────┬──────────────────┘
                        │           │ fused back in (implicit conditioning)
                        ▼           │
              ┌──────────────────────────────────────┐
              │      FLOW RECONSTRUCTION PATH        │
              │                                      │
              │         FLUX-dev Model               │◄── C2 (target prompt)
              │         (30 steps)                   │    "A sharp image of a cat..."
              │                                      │
              │   Step i:  z_t = z_t + v_θ(z_t) dt  │
              └─────────────────┬────────────────────┘
                                │
                                │  at each step i, check FlowSteer schedule:
                                ▼
               ┌────────────────────────────────────┐
               │      FLOWSTEER SCHEDULER  {λᵢ}     │
               │                                    │
               │  Step  1–14  → λᵢ = 0  (skip)      │
               │  Step 15–27  → λᵢ > 0  (activate!) │
               │  Step 28–30  → λᵢ = 0  (skip)      │
               └──────────┬──────────────┬──────────┘
                          │ λᵢ = 0       │ λᵢ > 0
                          │ (free run)   │ (steer!)
                          │              ▼
                          │   ┌──────────────────────┐
                          │   │   VAE DECODER        │  ← latent → pixel space
                          │   │   (FLUX built-in)    │
                          │   └──────────┬───────────┘
                          │              │
                          │              ▼
                          │   ┌──────────────────────────────────────────┐
                          │   │   FIDELITY UPDATE (Pseudo-inverse A†)   │
                          │   │                                          │
                          │   │  Task        Operator A                 │
                          │   │  ─────────── ──────────────────────     │
                          │   │  Colorize  → grayscale averaging        │
                          │   │  Deblur    → Gaussian blur (61×61)      │
                          │   │  Denoise   → identity + noise           │
                          │   │  Super-res → 4× downsampling            │
                          │   │                                          │
                          │   │  update: x̂ = A†y + (I - A†A)x̂         │
                          │   │  "pull image back to match original y"  │
                          │   └──────────┬───────────────────────────────┘
                          │              │
                          │              ▼
                          │   ┌──────────────────────┐
                          │   │   VAE ENCODER        │  ← pixel → latent space
                          │   │   (FLUX built-in)    │    (back into flow path)
                          │   └──────────┬───────────┘
                          │              │
                          └──────────────┘
                                     │
                              (continue steps)
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │    VAE DECODER      │  ← final latent → pixels
                          │   (FLUX built-in)   │
                          └──────────┬──────────┘
                                     │
                                     ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                     OUTPUT: RESTORED IMAGE (x̂)                             ║
║           (sharp / colorized / denoised / super-resolved)                   ║
║           faithful to original + rich FLUX generative quality               ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## Why the Timing Window Matters

```
TIMING OF FLOWSTEER — WHY IT MATTERS:
──────────────────────────────────────────────────────────────► reconstruction steps (1 → 30)

 FLUX is freely         FlowSteer ACTIVE        Clean finish
 forming the image      (reality checks)        no correction
 ┌──────────────────┐  ┌───────────────────┐   ┌───────────┐
 │ colors form      │  │ fidelity updates  │   │ smooth    │
 │ layout settles   │  │ keep subject      │   │ out noise │
 │ NO correction    │  │ identity intact   │   │ artifacts │
 │ (too noisy)      │  │                   │   │           │
 └──────────────────┘  └───────────────────┘   └───────────┘
  steps 1–14            steps 15–27             steps 28–30
  λᵢ = 0                λᵢ > 0                  λᵢ = 0

  TOO EARLY → image has no structure yet, correction destroys quality
  TOO LATE  → FLUX already hallucinated wrong details, too late to fix
  JUST RIGHT → rich details formed, then gently steered back to be faithful ✓
```

---

## Named Models & Components

| Component | Model / Tool | Role |
|---|---|---|
| Flow backbone | **FLUX-dev** (Rectified Flow Transformer) | Generates/restores the image |
| Encoder / Decoder | **VAE** (built into FLUX, 16× compression) | Moves between pixel ↔ latent space |
| Attention caching | **DiT single-block layers** (inside FLUX) | Stores structural guidance from inversion path |
| Fidelity operator | **Pseudo-inverse A†** (task-specific math) | Pulls restored image back toward input |
| Timing controller | **FlowSteer Scheduler {λᵢ}** | The paper's key contribution — controls WHEN to steer |
| Implicit guidance | **CFG** (Classifier-Free Guidance, γ=4) + feature sharing (ζ=4) | Keeps identity consistent during reconstruction |

---

## Task-Specific Degradation Operators

| Task | Degradation A | Pseudo-inverse A† |
|---|---|---|
| **Colorization** | RGB → grayscale (channel averaging) | Replicate grayscale to 3 channels |
| **Deblurring** | Gaussian convolution (61×61 kernel) | Wiener deconvolution (λ=0.1) |
| **Denoising** | Identity + Gaussian noise (σ=25/255) | Identity (no inversion needed) |
| **Super-resolution (4×)** | Average pooling 4×4 | Nearest-neighbor 4× upsampling |

---

## Key Results

| Task | Dataset | Metric | FlowSteer Score |
|---|---|---|---|
| Colorization | ImageNet val | PSNR / SSIM | State-of-the-art (training-free) |
| Deblurring | FFHQ / ImageNet | LPIPS | Competitive with trained models |
| Denoising | FFHQ | PSNR | Matches diffusion-based methods |
| Super-resolution 4× | DIV2K | PSNR / SSIM | Competitive zero-shot |

**Key advantage**: All four tasks use the exact same FLUX-dev model with no fine-tuning. Only the operator A changes per task.
