# Progression Architecture

Heracles uses a hybrid progression model:

1. The agent proposes the next prescription as a coach.
2. The backend validates the proposal with strict guardrails.
3. Invalid or missing decisions fall back to deterministic double progression.
4. Only validated suggestions are persisted in `progression_targets`.

## Agent Responsibility

The agent may use:

- user profile and goal
- training experience
- available equipment
- completed sets, reps, weight and RPE
- notes such as pain, fatigue or technical issues
- recent exercise history

The agent may propose increasing weight, reducing weight, adding or reducing
sets, adjusting reps, consolidating, or marking data as insufficient.

## Backend Responsibility

The backend owns safety, validity and persistence. It validates:

- exercise names must match exercises completed in the session
- exercise names must use the canonical name already known for that movement
- duplicate decisions are ignored
- weights must use available increments
- pain reports block load or volume increases
- high RPE or reps below target block weight increases
- weight increases are limited to one configured increment
- bodyweight exercises do not automatically gain external load
- excessive weight reductions are rejected

If a decision fails validation, that exercise uses the deterministic fallback.

Exercise names are persistence keys in `progression_targets` and `workouts`.
The agent must not rename an exercise casually. When it refers to a known
movement, it should reuse the canonical name from the active routine,
temporary override, progression target or workout history. See
`docs/EXERCISE_IDENTITY.md`.

## Deterministic Fallback

The fallback keeps the previous double-progression policy:

- insufficient data -> keep current target
- reps below minimum -> consolidate
- RPE 9 or higher -> consolidate
- below rep ceiling -> build reps
- rep ceiling reached and more volume allowed -> add one set
- max sets reached and rep ceiling reached -> add 2.5 kg
- bodyweight exercises keep `next_weight = 0`

This fallback is not the primary coaching brain. It exists so session completion
remains reliable when the model is unavailable or unsafe.
