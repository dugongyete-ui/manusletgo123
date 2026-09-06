# INSTRUCTIONS.md

Operational instructions — how a task actually runs, in order.

## 1. Orient
- Read AGENTS.md once per fresh workspace (you are doing that now).
- Skim the task. Is it research, a build, data work, or a conversation?
  TASKS.md tells you what each type expects. If it clearly matches a skill
  in the index (`project/SKILLS.md` — identical copy at
  `project/skills/SKILLS.md`), open that skill's
  `project/skills/<name>/SKILL.md` before writing anything.

## 2. Open the work
- One short opening line to the user: what you look at first and why.
  No promises, no restating the request, no template.
- Locate the user's inputs: `upload/` holds files they attached. Read them
  before asking anything the files might already answer.

## 3. Execute in honest loops
- Narrate intent BEFORE a tool group; interpret AFTER a notable result.
- Verify side effects of your own actions (page changed? file listed? exit
  code 0?) before building on them.
- Prefer fewer, well-chosen calls. Fix forward rather than re-running blind.

## 4. Verify before claiming
- Run the checklist in the execution prompt: every requirement in the goal,
  checked against what you actually observed, with gaps named.

## 5. Package and deliver
- Document task → one well-formed file (see CONTENT.md).
- Build task → project folder complete and self-contained, then ONE .zip
  (see DEPLOYMENT.md). Attach only the archive (+ the summary document if
  one exists). List the archive path in your final attachments.

## 6. Close
- Final summary: what was made, where it is, what to know (limits, how to
  run it), in the user's language. No invented detail, no filler.
