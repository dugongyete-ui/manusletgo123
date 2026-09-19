---
name: slides
description: Build and export slide decks. Use when the user asks for a presentation, slide deck, pitch deck, or when an existing deck must be edited or converted — covers the html2pptx pipeline and slide export tools.
---

# Slides

## When to Use

- "Make me a presentation / deck / pitch" — any N-slide visual deliverable
- An existing .pptx must be edited, analyzed, or converted
- Diagrams must land inside slides (not as loose images)

## Pipeline (in priority order)

1. **PPTX skill first.** For new decks follow the `pptx` skill's html2pptx
   workflow (HTML slides → rendered pptx). Its pipeline is the quality bar:
   consistent 16:9 layout, one idea per slide, real content — never lorem ipsum.
2. **`manus-export-slides` registry tool** for export/rendition flows the
   tool supports; check its result and verify the output file exists and
   opens (slide count matches) before declaring done.
3. **`manus-render-diagram`** to turn Mermaid/structured definitions into
   diagram images you then place on slides — never hand-draw diagrams as ASCII
   art inside a slide.
4. **`manus-md-to-pdf`** when the user actually wants a document-style handout
   rather than a deck; ask nothing, pick the right artifact.

## Content Rules

- Title slide: title + one-line promise; Agenda only if >6 content slides.
- Per slide: one message in the title, ≤3 supporting points, real numbers/names
  from your research; cite sources on the slide where they are used.
- Consistent palette and font sizes across slides; charts follow the charts
  skill for color and labeling discipline.
- Final deck must open without missing fonts — embed or convert text where the
  pipeline supports it.

## Verification Before Delivery

- Open the produced file (python-pptx or the pipeline's own checker) and verify
  slide count, no empty slides, no overflowing text boxes.
- Say the file path and the slide count in your final message.
