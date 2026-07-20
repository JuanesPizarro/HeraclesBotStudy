import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { useSession } from '@/lib/session';

type ChatItem = {
  role: 'user' | 'assistant';
  text: string;
};

export default function CoachScreen() {
  const { api, isReady } = useSession();
  const [message, setMessage] = useState('');
  const [items, setItems] = useState<ChatItem[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    const trimmed = message.trim();
    if (!api || !trimmed) {
      return;
    }
    setItems((current) => [...current, { role: 'user', text: trimmed }]);
    setMessage('');
    setSending(true);
    setError(null);
    try {
      const response = await api.sendAgentMessage(trimmed);
      setItems((current) => [...current, { role: 'assistant', text: response.message }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo enviar');
    } finally {
      setSending(false);
    }
  }

  if (!isReady) {
    return <Centered label="Cargando" />;
  }

  if (!api) {
    return <Centered label="Configura tu token en Perfil" />;
  }

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.select({ ios: 'padding', default: undefined })}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <Text style={styles.eyebrow}>Heracles</Text>
          <Text style={styles.title}>Coach</Text>
        </View>

        {items.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyText}>Pregúntame por tu entrenamiento de hoy.</Text>
          </View>
        ) : null}

        {items.map((item, index) => (
          <View
            key={`${item.role}-${index}`}
            style={[styles.bubble, item.role === 'user' ? styles.userBubble : styles.agentBubble]}>
            <Text style={item.role === 'user' ? styles.userText : styles.agentText}>{item.text}</Text>
          </View>
        ))}

        {sending ? <ActivityIndicator /> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </ScrollView>

      <View style={styles.composer}>
        <TextInput
          value={message}
          onChangeText={setMessage}
          placeholder="Mensaje"
          placeholderTextColor="#7b8494"
          multiline
          style={styles.input}
        />
        <Pressable style={styles.sendButton} onPress={send} disabled={sending || !message.trim()}>
          <Text style={styles.sendButtonText}>Enviar</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

function Centered({ label }: { label: string }) {
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
    gap: 12,
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
  empty: {
    backgroundColor: '#ffffff',
    borderColor: '#d9e0e8',
    borderWidth: 1,
    borderRadius: 8,
    padding: 16,
  },
  emptyText: {
    color: '#475569',
    fontSize: 15,
  },
  bubble: {
    maxWidth: '88%',
    borderRadius: 8,
    padding: 12,
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: '#172554',
  },
  agentBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#ffffff',
    borderColor: '#d9e0e8',
    borderWidth: 1,
  },
  userText: {
    color: '#ffffff',
    fontSize: 15,
    lineHeight: 21,
  },
  agentText: {
    color: '#1f2937',
    fontSize: 15,
    lineHeight: 21,
  },
  error: {
    color: '#be123c',
    fontSize: 14,
  },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 10,
    padding: 14,
    borderTopColor: '#d9e0e8',
    borderTopWidth: 1,
    backgroundColor: '#ffffff',
  },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 110,
    borderColor: '#cbd5e1',
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: '#151b23',
    backgroundColor: '#f8fafc',
    fontSize: 15,
  },
  sendButton: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#0f766e',
  },
  sendButtonText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '800',
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
