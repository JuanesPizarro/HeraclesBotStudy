# Routine Change Policy

Heracles separates routine changes into two categories: direct calendar updates
and routine drafts.

## Direct Updates

Use a direct update when the user has explicitly confirmed a change and the
exercise prescription remains the same.

Direct update tools:

- `update_training_days`: changes only the active training weekdays.
- `update_training_schedule`: changes which existing routine block belongs to
  each weekday, while preserving the same exercise list.

Examples:

- "Domingo upper, lunes lower, martes descanso, miércoles push, jueves pull,
  viernes legs" with the same exercises.
- "Cambia mis días a lunes, miércoles y viernes" without changing the routine.

These updates do not create a routine draft because they do not replace the
training prescription.

## Routine Drafts

Create a routine draft when the requested change modifies the prescription.

Draft-triggering changes:

- new or removed exercises
- changed sets, reps, weights, tempo or rest rules
- a new routine split with different contents
- any full routine rewrite that cannot be proven to preserve the same exercises

The active routine is replaced only after explicit confirmation of the draft.

## Confirmation Handling

Short confirmations such as `si`, `ok`, `dale` or `confirmo` inherit the
previous routine-change intent if the previous assistant message asked for
calendar or routine confirmation. This prevents the model from saying "done"
without access to write tools.

## Current Production Behavior

As of the deployed fix, confirmed calendar-only changes update production data
directly and the session planner reads the updated weekdays immediately.
