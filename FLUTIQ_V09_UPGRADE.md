# FlutIQ v0.9 — Multimodal Risk Analyst Upgrade

## The change in one sentence

Feed the Street View image directly to the risk analyst agent alongside
all the data, with reasoning mode on — so the chain-of-thought trace
weaves together what Gemma 4 *sees* in the photo with what the data says.

---

## Why this matters (the full argument)

### 1. The current weakness

Right now, the Street View agent and the risk analyst are separate:

```
Street View agent: sees photo → writes text findings → passes text to orchestrator
Risk analyst: reads text findings from ALL agents → reasons about text → outputs risk score
```

The risk analyst never sees the photo. It reasons about a *description* of
what another agent saw. This is like a doctor making a diagnosis from a
nurse's notes without ever examining the patient.

### 2. What Gemma 4 can actually do (from Google's own docs)

From the vLLM Gemma 4 recipe (docs.vllm.ai, May 2026):

> "Gemma 4 can combine vision understanding with tool calling — for example,
> identifying a city from an image and then looking up its weather."

> "Gemma 4 can combine thinking mode with tool calling — the model reasons
> about which tool to use before making the call."

From Google's model card (ai.google.dev):

> "Interleaved Multimodal Input — Freely mix text and images in any order
> within a single prompt."

From the HuggingFace launch blog:

> "We saw in our tests that Gemma 4 supports comprehensive multimodal
> capabilities out of the box... OCR, speech-to-text, object detection,
> or pointing. It also supports text-only and multimodal function calling,
> reasoning, code completion and correction."

The key insight: **vision + reasoning + structured output are not separate
features in Gemma 4 — they compose natively in a single inference pass.**
The model can see an image, think step-by-step about it, cross-reference
with text data in the same prompt, and output structured JSON — all in
one call.

### 3. What the hackathon judges want to see

From Google's Gemma 4 launch blog:

> "Purpose-built for advanced reasoning and agentic workflows... This new
> level of intelligence-per-parameter means achieving frontier-level
> capabilities with significantly less hardware overhead."

> "Beyond simple chat to handle complex logic and agentic workflows."

The judges (Google DevRel + Kaggle) will be looking for submissions that
showcase *compositions* of Gemma 4 capabilities, not individual checkboxes.
Every submission will check "used vision" and "used reasoning." The winning
submissions will fuse them into something that couldn't exist without both
being native to the same model.

### 4. Why this specific change is the highest-value thing to do before recording

The risk analyst's reasoning trace is the single most visible artifact in
the FlutIQ demo. It's the section judges will expand and read. Right now
it says things like:

> "Based on the Street View agent's findings, the property has below-grade
> entry points. Combined with the FEMA Zone X designation but 23 basement
> flooding complaints..."

After this change, it will say:

> "Looking at the property photo, I can see the lot sits approximately 12
> inches below street grade with no visible drainage infrastructure. The
> foundation has two basement-level window wells with no covers. The
> downspouts appear to connect directly to the ground, likely feeding into
> the combined sewer system.
>
> Cross-referencing with the data: FEMA designates this Zone X (minimal
> risk), but the Chicago 311 database shows 23 basement flooding reports
> within 500m since 2020..."

The difference: the model is *looking at the house and reasoning about it
alongside the data*. That's multimodal reasoning — not "vision agent wrote
some text that another agent read."

### 5. Why this is Gemma 4-native (and wouldn't work as well with other models)

Gemma 4 was specifically trained for:
- Variable-resolution image understanding (configurable token budget: 70-1120)
- Thinking mode with chain-of-thought traces
- Interleaved image + text in a single prompt
- All three composing in a single forward pass

If you swapped Gemma 4 for Llama 4 or Mistral, the vision quality, the
reasoning trace quality, and the composition would all degrade. This is
the kind of usage that makes a judge say "this project needed Gemma 4."

---

## Gemma 4 features this change exercises

| Feature | How it's used | Google's term |
|---------|---------------|---------------|
| Image understanding | Risk analyst receives the Street View photo as a base64 image_url content part | "Extended Multimodalities" |
| Thinking / reasoning mode | `reasoning: {enabled: true}` — model thinks step-by-step before answering | "Advanced reasoning" |
| Interleaved multimodal input | Single prompt contains: [image] + [FEMA data text] + [311 data text] + [weather text] + [news text] + [archive text] + [streetview findings text] | "Interleaved Multimodal Input" |
| Structured JSON output | Risk analyst returns a JSON object with risk_score, aep_estimate, key_risk_factors, etc. | "Structured JSON output" |
| Long context | The combined prompt with image + all agent data will be ~6-10K tokens + image tokens | "Longer context" |
| Variable image resolution | Use token budget 560 or 1120 for the risk analyst's image (higher detail for reasoning about physical features) | "Variable resolutions" |

This single change exercises **6 Gemma 4 capabilities simultaneously in one
inference call.** No other agent in FlutIQ (or likely any other hackathon
submission) does this.

---

## Implementation instructions

### What to change

Two files: `orchestrator.py` and `risk_agent.py`. Approximately 15-20 lines.

### Step 1: Pass Street View image through the orchestrator

In `orchestrator.py`, after the Street View agent completes, extract the
base64 image from its result and pass it to the risk analyst:

```python
# In orchestrator.py, after all data agents complete:

# Extract Street View image if available
streetview_image_b64 = None
if "streetview" in results:
    sv_result = results["streetview"]
    # The streetview agent should already store the base64 image
    # in its result dict — check your streetview_agent.py for the key name
    streetview_image_b64 = sv_result.get("image_b64") or sv_result.get("image_base64")

# Pass it to the risk analyst
risk_result = await run_risk_agent(
    results,
    lat, lon,
    display_name,
    streetview_image_b64=streetview_image_b64,  # NEW PARAMETER
)
```

### Step 2: Update risk_agent.py to accept and use the image

```python
async def run_risk_agent(
    all_data: dict,
    lat: float,
    lon: float,
    address: str,
    streetview_image_b64: str | None = None,  # NEW PARAMETER
) -> dict:

    # Build the user message content
    # Key Gemma 4 best practice from the model card:
    # "For optimal performance with multimodal inputs, place image
    #  and/or audio content BEFORE the text in your prompt."
    
    content_parts = []
    
    # Add the Street View image FIRST (before text) per Gemma 4 best practices
    if streetview_image_b64:
        content_parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{streetview_image_b64}"
            }
        })
    
    # Then add the text prompt with all agent data
    text_prompt = build_risk_prompt(all_data, lat, lon, address, has_image=bool(streetview_image_b64))
    content_parts.append({
        "type": "text",
        "text": text_prompt,
    })
    
    messages = [
        {"role": "system", "content": RISK_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": content_parts},
    ]
    
    # Call with reasoning mode ON
    response = await call_gemma4(
        messages=messages,
        reasoning=True,
        temperature=0.2,
        max_tokens=8192,
    )
    
    # ... rest of parsing unchanged
```

### Step 3: Update the risk analyst prompt to reference the image

```python
def build_risk_prompt(all_data, lat, lon, address, has_image=False):
    image_instruction = ""
    if has_image:
        image_instruction = """
## Property Photo (Street View)
A photo of the property is included above. Examine it carefully for
flood risk indicators:
- Lot elevation relative to street grade (above, level, or below)
- Basement-level windows or below-grade entries
- Downspout connections (to ground? to sewer? disconnected?)
- Visible drainage infrastructure (French drains, catch basins, swales)
- Ground-floor HVAC equipment, electrical panels, or utilities
- Evidence of prior water damage (staining, erosion, patching)
- Impervious surface coverage (concrete, asphalt vs. permeable ground)

Integrate your visual observations with the data below. When your visual
assessment contradicts or corroborates the data, say so explicitly.
"""

    return f"""You are analyzing flood risk for: {address} ({lat}, {lon})

{image_instruction}

## FEMA Expert Findings
{json.dumps(all_data.get('fema', {}), indent=2, default=str)}

## Local Infrastructure Findings (311 data, sewer type)
{json.dumps(all_data.get('local', {}), indent=2, default=str)}

## Street View Visual Analysis
{json.dumps(all_data.get('streetview', {}), indent=2, default=str)}

## Weather & Hydrology Findings
{json.dumps(all_data.get('weather', {}), indent=2, default=str)}

## Recent Local Flood News
{json.dumps(all_data.get('news', {}), indent=2, default=str)}

## Historical Flood Archive
{json.dumps(all_data.get('archive', {}), indent=2, default=str)}

---

TASK: Synthesize ALL of this data — including your own visual inspection
of the property photo — into a flood risk assessment.

IMPORTANT: You have both the raw photo AND the Street View agent's text
analysis. Use YOUR OWN eyes on the photo to verify, extend, or correct
the Street View agent's findings. If you see something the Street View
agent missed, say so. If you disagree with the agent's assessment, explain
why based on what YOU see in the image.

{AEP_INSTRUCTIONS}

Return a JSON object with:
{{
  "risk_score": <0-100>,
  "risk_level": "low" | "medium" | "high",
  "aep_estimate": <decimal>,
  "mortgage_30yr_probability": <decimal>,
  "fema_gap_explanation": "<2-3 sentences>",
  "visual_corroboration": "<what the photo confirms or contradicts vs the data>",
  "key_risk_factors": ["<ranked list>"],
  "mitigating_factors": ["<list>"],
  "summary": "<1 sentence>"
}}

Think step by step. Integrate visual and data evidence. Return ONLY the JSON at the end."""
```

### Step 4: Make sure Street View agent preserves the base64 image

In `streetview_agent.py`, ensure the raw base64 image is included in the
agent's return dict so the orchestrator can forward it:

```python
# In streetview_agent.py, when returning results:
return {
    "findings": findings,
    "bounding_boxes": bounding_boxes,
    "image_b64": image_b64,  # KEEP THIS — orchestrator needs it
    "summary": summary,
}
```

### Step 5: Add "visual_corroboration" to the dossier frontend

In `index.html`, in the FEMA gap section or raw signals section, display
the `visual_corroboration` field from the risk analyst's output. This shows
the judge that the risk analyst didn't just read the Street View agent's
text — it looked at the photo itself and formed its own assessment.

---

## What NOT to change

- Don't remove the Street View agent. It still does bounding box detection
  (which the risk analyst doesn't do — different task).
- Don't change the advisor agent. It stays text-only and catalog-driven.
- Don't add more Street View images (multi-angle). One image is enough for
  this change and avoids 429 risk.
- Don't change the SSE event format or the orchestrator's agent ordering.

---

## Testing

After implementing, test with the Chicago address (4521 S Drexel Blvd):

1. Check that the risk analyst's reasoning trace references the photo
   directly ("I can see in the photo..." / "The image shows...")
2. Check that `visual_corroboration` is populated in the dossier JSON
3. Check that the risk score is consistent with v0.8 (should be similar,
   not wildly different — the same data is there, now with visual backup)
4. Check that the Street View section with bounding boxes still works
   independently

---

## What this gives you for the hackathon

### For the video demo
The reasoning trace panel now shows the model weaving together visual
evidence and data evidence in one chain of thought. When you expand it
in the demo and scroll through, the judge sees Gemma 4 doing something
no other model in the hackathon is doing: multimodal reasoning that
synthesizes a photo of the user's actual home with federal flood data,
local complaint records, weather forecasts, and news — all in one pass.

### For the Kaggle writeup
Add one paragraph:

"The risk analyst agent receives the Street View photograph directly
alongside all data-agent findings, with Gemma 4's reasoning mode
enabled. This allows the model to perform multimodal reasoning in a
single inference pass — cross-referencing what it sees in the property
photo (below-grade entries, downspout connections, lot grade) with what
the data says (FEMA zone, 311 complaint density, sewer type). The
chain-of-thought trace is preserved in the dossier, showing judges and
users exactly how visual and data evidence were integrated. This
composition of vision + reasoning + structured output in one call is
native to Gemma 4 and would degrade significantly with models that
bolt vision onto a text-only architecture."

### For the hackathon checklist
This change lets you honestly claim:
- [x] Multimodal vision (Street View agent + risk analyst)
- [x] Reasoning mode with chain-of-thought (risk analyst)
- [x] Interleaved multimodal input (image + text in one prompt)
- [x] Structured JSON output (risk analyst return format)
- [x] **Composed multimodal reasoning** (vision + thinking + data in one pass)

That last checkbox is the one nobody else will have.
