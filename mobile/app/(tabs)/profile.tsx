import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { UserProfile } from '@/lib/api';
import { useSession } from '@/lib/session';

export default function ProfileScreen() {
  const { api, apiUrl, token, saveSettings, clearToken, isReady } = useSession();
  const [draftUrl, setDraftUrl] = useState(apiUrl);
  const [draftToken, setDraftToken] = useState(token);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    setDraftUrl(apiUrl);
    setDraftToken(token);
  }, [apiUrl, token]);

  useEffect(() => {
    if (!api) {
      setProfile(null);
      return;
    }
    const client = api;
    let mounted = true;
    async function load() {
      setLoading(true);
      setStatus(null);
      try {
        const next = await client.me();
        if (mounted) {
          setProfile(next);
        }
      } catch (err) {
        if (mounted) {
          setStatus(err instanceof Error ? err.message : 'Token inválido');
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      mounted = false;
    };
  }, [api]);

  async function save() {
    setLoading(true);
    setStatus(null);
    try {
      await saveSettings({ apiUrl: draftUrl, token: draftToken });
      setStatus('Guardado');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'No se pudo guardar');
    } finally {
      setLoading(false);
    }
  }

  async function disconnect() {
    await clearToken();
    setDraftToken('');
    setProfile(null);
  }

  if (!isReady) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>Cuenta</Text>
        <Text style={styles.title}>Perfil</Text>
      </View>

      {profile ? (
        <View style={styles.panel}>
          <Text style={styles.name}>{profile.name}</Text>
          <Text style={styles.goal}>{profile.goal}</Text>
          <View style={styles.metaGrid}>
            <Meta label="Días" value={profile.training_days.join(', ') || '-'} />
            <Meta label="Sesión" value={`${profile.session_minutes} min`} />
            <Meta label="Nivel" value={profile.experience_level || '-'} />
            <Meta label="Equipo" value={profile.equipment || '-'} />
          </View>
        </View>
      ) : null}

      <View style={styles.panel}>
        <Text style={styles.panelTitle}>Conexión</Text>
        <Text style={styles.label}>API</Text>
        <TextInput
          value={draftUrl}
          onChangeText={setDraftUrl}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="https://gym.perritoemo.online"
          placeholderTextColor="#7b8494"
          style={styles.input}
        />
        <Text style={styles.label}>Token</Text>
        <TextInput
          value={draftToken}
          onChangeText={setDraftToken}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
          placeholder="web_token"
          placeholderTextColor="#7b8494"
          style={styles.input}
        />

        {status ? <Text style={styles.status}>{status}</Text> : null}

        <Pressable style={styles.primaryButton} onPress={save} disabled={loading}>
          <Text style={styles.primaryButtonText}>{loading ? 'Guardando' : 'Guardar'}</Text>
        </Pressable>
        {token ? (
          <Pressable style={styles.secondaryButton} onPress={disconnect}>
            <Text style={styles.secondaryButtonText}>Desconectar</Text>
          </Pressable>
        ) : null}
      </View>
    </ScrollView>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.meta}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue}>{value}</Text>
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
    fontSize: 28,
    fontWeight: '900',
    letterSpacing: 0,
  },
  panel: {
    backgroundColor: '#ffffff',
    borderColor: '#d9e0e8',
    borderWidth: 1,
    borderRadius: 8,
    padding: 14,
    gap: 10,
  },
  name: {
    color: '#151b23',
    fontSize: 20,
    fontWeight: '900',
  },
  goal: {
    color: '#475569',
    fontSize: 15,
    lineHeight: 21,
  },
  panelTitle: {
    color: '#151b23',
    fontSize: 17,
    fontWeight: '900',
  },
  metaGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  meta: {
    minWidth: '47%',
    backgroundColor: '#f8fafc',
    borderColor: '#e2e8f0',
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
    gap: 3,
  },
  metaLabel: {
    color: '#64748b',
    fontSize: 12,
    fontWeight: '700',
  },
  metaValue: {
    color: '#151b23',
    fontSize: 14,
    fontWeight: '700',
  },
  label: {
    color: '#64748b',
    fontSize: 12,
    fontWeight: '800',
  },
  input: {
    minHeight: 46,
    borderColor: '#cbd5e1',
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    color: '#151b23',
    backgroundColor: '#f8fafc',
    fontSize: 15,
  },
  status: {
    color: '#334155',
    fontSize: 14,
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
    fontWeight: '900',
  },
  secondaryButton: {
    minHeight: 46,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#e2e8f0',
  },
  secondaryButtonText: {
    color: '#172554',
    fontSize: 15,
    fontWeight: '900',
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f4f6f8',
  },
});
