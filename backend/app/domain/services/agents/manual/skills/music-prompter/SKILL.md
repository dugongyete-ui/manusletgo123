---
name: music-prompter
description: Craft high-quality prompts and lyric sheets for AI music generation tools. Use when the user asks for song lyrics, a Suno/Udio-style generation prompt, jingle concepts, or music briefs — not for generating audio itself.
---

# Music Prompter

## When to Use

- The user wants a song written: lyrics, structure, theme, style tags
- The user asks for a generation-ready prompt for an AI music tool
- The user needs jingle/brand-audio concepts with art direction

## What This Sandbox Delivers

- The sandbox has **no audio generation tool**. The deliverable is the
  *prompt pack*: genre/style prompt, lyrics with section labels, and
  negative/constraint notes — the user pastes it into their music tool.
- Write the pack to a Markdown file; do not fabricate audio files.

## Craft Rules

1. **Structure first.** Label sections explicitly: `[Intro] [Verse 1]
   [Pre-Chorus] [Chorus] [Bridge] [Outro]` — generators follow them well.
2. **Style prompt is a sentence, not a tag cloud.** "Moody synth-pop at 100
   BPM, female vocal, analog warmth, 80s gated reverb drums" beats a pile of
   comma-separated words.
3. **Syllable discipline.** For a singable chorus keep lines within ±2
   syllables of each other; read it aloud before delivering.
4. **One emotional turn per song.** State it ("verses resign, chorus defies") —
   generators map emotional arcs better than thematic lists.
5. **Constraints block.** Add what to avoid: "no rap section, no key change in
   outro, vocals only in English".

## Delivery Checklist

- File contains: style prompt (1 paragraph), lyric sheet with section labels,
  constraint notes, and a 1-line "how to use" for the target tool.
- Offer 2 style variants when the user hasn't pinned a genre.
- Never promise a rendered audio file unless the user's own tool produced it.
