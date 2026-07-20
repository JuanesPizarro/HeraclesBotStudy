# Heracles Mobile

Expo client for the Heracles training API.

## Run

```bash
cd mobile
npm install
npm run start
```

Then open the QR code with Expo Go.

## API

Default API URL:

```text
https://gym.perritoemo.online
```

Override at build/runtime with:

```bash
EXPO_PUBLIC_API_URL=http://localhost:8001 npm run start
```

The app uses the versioned mobile endpoints documented in:

```text
../docs/MOBILE_API_V1.md
```

## Auth

For the MVP, mobile uses the same transitional `web_token` as the current web
app.

1. In Telegram, request `/webapp`.
2. Copy the `token` query parameter from the generated URL.
3. Open the mobile app.
4. Go to `Perfil`.
5. Paste the API URL and token.

The token is stored with `expo-secure-store`.

## Screens

- `Hoy`: today's plan, set logging, session finish and progression summary.
- `Coach`: compact chat against `/api/v1/agent/messages`.
- `Perfil`: profile readout, API URL and token management.

Telegram and the current web app continue to run in parallel. This client should
not change legacy `/api/session/*` behavior.
