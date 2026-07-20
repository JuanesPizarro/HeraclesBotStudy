import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { FinishSessionResponse, LoggedSet, SessionExercise, SessionPlan } from '@/lib/api';
import { useSession } from '@/lib/session';

type DraftSet = {
  reps: string;
  weight: string;
  rpe: string;
  notes: string;
};

const emptyDraft: DraftSet = { reps: '', weight: '', rpe: '', notes: '' };

function nextDraftForExercise(exercise: SessionExercise): DraftSet {
  return {
    reps: exercise.suggested_reps || exercise.target_reps || '',
    weight: exercise.suggested_weight ? String(exercise.suggested_weight) : '0',
    rpe: '',
    notes: '',
  };
}

export default function TodayScreen() {
  const { api, isReady } = useSession();
  const [plan, setPlan] = useState<SessionPlan | null>(null);
  const [sets, setSets] = useState<LoggedSet[]>([]);
  const [drafts, setDrafts] = useState<Record<string, DraftSet>>({});
  const [evaluation, setEvaluation] = useState<FinishSessionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingExercise, setSavingExercise] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!api) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [nextPlan, today] = await Promise.all([api.plan(), api.today()]);
      setPlan(nextPlan);
      setSets(today.sets);
      setDrafts((current) => {
        const next = { ...current };
        for (const exercise of nextPlan.exercises) {
          if (!next[exercise.name]) {
            next[exercise.name] = nextDraftForExercise(exercise);
          }
        }
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo cargar la sesión');
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    if (api) {
      load();
    }
  }, [api, load]);

  const groupedSets = useMemo(() => {
    const grouped: Record<string, LoggedSet[]> = {};
    for (const item of sets) {
      grouped[item.exercise] = [...(grouped[item.exercise] ?? []), item];
    }
    return grouped;
  }, [sets]);

  async function logSet(exercise: SessionExercise) {
    if (!api || !plan?.session_id) {
      return;
    }
    const draft = drafts[exercise.name] ?? emptyDraft;
    const reps = Number(draft.reps);
    const weight = Number(draft.weight || 0);
    const rpe = draft.rpe ? Number(draft.rpe) : null;
    if (!Number.isFinite(reps) || reps < 1) {
      setError('Reps inválidas');
      return;
    }
    setSavingExercise(exercise.name);
    setError(null);
    try {
      const saved = await api.logSet({
        session_id: plan.session_id,
        exercise: exercise.name,
        reps,
        weight_kg: Number.isFinite(weight) ? weight : 0,
        rpe,
        notes: draft.notes,
      });
      setSets((current) => [...current, saved]);
      setDrafts((current) => ({
        ...current,
        [exercise.name]: { ...current[exercise.name], rpe: '', notes: '' },
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo guardar la serie');
    } finally {
      setSavingExercise(null);
    }
  }

  async function finishSession() {
    if (!api || !plan?.session_id) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setEvaluation(await api.finishSession(plan.session_id));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo finalizar');
    } finally {
      setLoading(false);
    }
  }

  if (!isReady) {
    return <CenteredState label="Cargando" />;
  }

  if (!api) {
    return <CenteredState label="Configura tu token en Perfil" />;
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>{plan?.date ?? ''}</Text>
        <Text style={styles.title}>
          {plan?.is_rest_day ? 'Descanso' : plan?.day_name || 'Sesión de hoy'}
        </Text>
        {plan?.override ? <Text style={styles.override}>Override activo</Text> : null}
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {loading && !plan ? <ActivityIndicator /> : null}

      {plan?.is_rest_day ? (
        <View style={styles.panel}>
          <Text style={styles.panelTitle}>Próximo entrenamiento</Text>
          <Text style={styles.bodyText}>{plan.next_training_day || 'Sin día programado'}</Text>
        </View>
      ) : null}

      {plan?.exercises.map((exercise) => {
        const logged = groupedSets[exercise.name] ?? [];
        const draft = drafts[exercise.name] ?? nextDraftForExercise(exercise);
        const targetSets = exercise.target_sets ?? exercise.circuit_rounds ?? 0;
        return (
          <View key={exercise.name} style={styles.exercise}>
            <View style={styles.exerciseHeader}>
              <View style={styles.exerciseTitleWrap}>
                <Text style={styles.exerciseName}>{exercise.name}</Text>
                <Text style={styles.prescription}>
                  {targetSets ? `${targetSets}x` : ''}
                  {exercise.target_reps || exercise.suggested_reps || 'reps'}
                  {exercise.suggested_weight ? ` @ ${exercise.suggested_weight} kg` : ''}
                </Text>
              </View>
              <Text style={styles.counter}>
                {logged.length}/{targetSets || '-'}
              </Text>
            </View>

            {exercise.note ? <Text style={styles.note}>{exercise.note}</Text> : null}

            <View style={styles.inputs}>
              <Field
                label="Reps"
                value={draft.reps}
                keyboardType="numeric"
                onChangeText={(value) =>
                  setDrafts((current) => ({
                    ...current,
                    [exercise.name]: { ...draft, reps: value },
                  }))
                }
              />
              <Field
                label="Kg"
                value={draft.weight}
                keyboardType="decimal-pad"
                onChangeText={(value) =>
                  setDrafts((current) => ({
                    ...current,
                    [exercise.name]: { ...draft, weight: value },
                  }))
                }
              />
              <Field
                label="RPE"
                value={draft.rpe}
                keyboardType="numeric"
                onChangeText={(value) =>
                  setDrafts((current) => ({
                    ...current,
                    [exercise.name]: { ...draft, rpe: value },
                  }))
                }
              />
            </View>

            <TextInput
              value={draft.notes}
              onChangeText={(value) =>
                setDrafts((current) => ({
                  ...current,
                  [exercise.name]: { ...draft, notes: value },
                }))
              }
              placeholder="Notas"
              placeholderTextColor="#7b8494"
              style={styles.notesInput}
            />

            <Pressable
              style={[styles.primaryButton, savingExercise === exercise.name && styles.disabled]}
              disabled={savingExercise === exercise.name}
              onPress={() => logSet(exercise)}>
              <Text style={styles.primaryButtonText}>
                {savingExercise === exercise.name ? 'Guardando' : 'Guardar serie'}
              </Text>
            </Pressable>

            {logged.length ? (
              <View style={styles.loggedList}>
                {logged.map((item, index) => (
                  <Text key={item.id} style={styles.loggedSet}>
                    S{index + 1}: {item.reps} reps @ {item.weight_kg} kg
                    {item.rpe ? ` · RPE ${item.rpe}` : ''}
                  </Text>
                ))}
              </View>
            ) : null}
          </View>
        );
      })}

      {plan?.session_id && sets.length ? (
        <Pressable style={styles.finishButton} onPress={finishSession}>
          <Text style={styles.finishButtonText}>Finalizar sesión</Text>
        </Pressable>
      ) : null}

      {evaluation ? (
        <View style={styles.panel}>
          <Text style={styles.panelTitle}>Evaluación</Text>
          <Text style={styles.bodyText}>{evaluation.evaluation}</Text>
          {evaluation.suggestions.map((item) => (
            <Text key={item.exercise} style={styles.suggestion}>
              {item.exercise}: {item.next_sets}x{item.next_reps} @ {item.next_weight} kg
            </Text>
          ))}
        </View>
      ) : null}
    </ScrollView>
  );
}

function Field({
  label,
  value,
  keyboardType,
  onChangeText,
}: {
  label: string;
  value: string;
  keyboardType: 'numeric' | 'decimal-pad';
  onChangeText: (value: string) => void;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        keyboardType={keyboardType}
        placeholderTextColor="#7b8494"
        style={styles.input}
      />
    </View>
  );
}

function CenteredState({ label }: { label: string }) {
  return (
    <View style={styles.centered}>
      <Text style={styles.centeredText}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: '#f4f6f8',
  },
  content: {
    padding: 18,
    paddingTop: 64,
    gap: 14,
  },
  header: {
    gap: 5,
  },
  eyebrow: {
    color: '#607084',
    fontSize: 13,
    fontWeight: '700',
    textTransform: 'uppercase',
  },
  title: {
    color: '#151b23',
    fontSize: 26,
    fontWeight: '800',
    letterSpacing: 0,
  },
  override: {
    alignSelf: 'flex-start',
    backgroundColor: '#e3f6e8',
    color: '#166534',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 6,
    fontSize: 12,
    fontWeight: '700',
  },
  error: {
    backgroundColor: '#fff1f2',
    borderColor: '#fecdd3',
    borderWidth: 1,
    color: '#be123c',
    padding: 12,
    borderRadius: 8,
  },
  panel: {
    backgroundColor: '#ffffff',
    borderColor: '#d9e0e8',
    borderWidth: 1,
    borderRadius: 8,
    padding: 14,
    gap: 8,
  },
  panelTitle: {
    color: '#151b23',
    fontSize: 16,
    fontWeight: '800',
  },
  bodyText: {
    color: '#334155',
    fontSize: 15,
    lineHeight: 21,
  },
  exercise: {
    backgroundColor: '#ffffff',
    borderColor: '#d9e0e8',
    borderWidth: 1,
    borderRadius: 8,
    padding: 14,
    gap: 12,
  },
  exerciseHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  exerciseTitleWrap: {
    flex: 1,
    gap: 3,
  },
  exerciseName: {
    color: '#151b23',
    fontSize: 17,
    fontWeight: '800',
    letterSpacing: 0,
  },
  prescription: {
    color: '#516173',
    fontSize: 14,
    fontWeight: '600',
  },
  counter: {
    color: '#0f766e',
    fontSize: 18,
    fontWeight: '900',
  },
  note: {
    color: '#475569',
    fontSize: 13,
    lineHeight: 18,
  },
  inputs: {
    flexDirection: 'row',
    gap: 10,
  },
  field: {
    flex: 1,
    gap: 5,
  },
  fieldLabel: {
    color: '#64748b',
    fontSize: 12,
    fontWeight: '700',
  },
  input: {
    minHeight: 44,
    borderColor: '#cbd5e1',
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    color: '#151b23',
    backgroundColor: '#f8fafc',
    fontSize: 15,
  },
  notesInput: {
    minHeight: 44,
    borderColor: '#cbd5e1',
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    color: '#151b23',
    backgroundColor: '#f8fafc',
    fontSize: 15,
  },
  primaryButton: {
    minHeight: 46,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#0f766e',
  },
  primaryButtonText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '800',
  },
  disabled: {
    opacity: 0.65,
  },
  loggedList: {
    borderTopColor: '#e2e8f0',
    borderTopWidth: 1,
    paddingTop: 8,
    gap: 4,
  },
  loggedSet: {
    color: '#334155',
    fontSize: 13,
  },
  finishButton: {
    minHeight: 50,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#172554',
  },
  finishButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '900',
  },
  suggestion: {
    color: '#334155',
    fontSize: 14,
    lineHeight: 20,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    backgroundColor: '#f4f6f8',
  },
  centeredText: {
    color: '#334155',
    fontSize: 17,
    fontWeight: '700',
    textAlign: 'center',
  },
});
