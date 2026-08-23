# ALI Voice Architecture

## Goal

ALI should feel present in the house without continuously streaming household audio to a cloud provider.

## What works today

- A short push-to-talk recording is transcribed only after the resident finishes speaking.
- ALI uses one fixed natural synthesized voice; the browser voice picker is intentionally not used.
- Recordings stop automatically after eight seconds and the backend records the clip's measured duration for its local cost estimate.
- A conversation stays open briefly so its context can continue, and explicit memories are stored only after “ALI, recuerda que …”.

## Production home design

```text
Room microphone + speaker
        |
        | local rolling buffer only (RAM)
        v
Local wake-word detector: "ALI"
        |
        | only after detection
        v
Voice activity detection + 5–8 second command
        |
        | local network
        v
ALI hub on the home mini-PC
  ├─ conversation and consented memory
  ├─ Home Assistant actions and verified states
  ├─ optional speech-to-text / reasoning provider
  └─ chooses one nearby speaker for ALI's answer
        |
        v
Fixed ALI voice in the originating room
```

## Non-negotiable safeguards

- Wake-word detection runs on the room device; audio before the wake word is never uploaded or stored.
- Every room device has a physical microphone-mute control and a visible listening indicator.
- Only one room responds to a command, chosen from the detecting device.
- After an answer, ALI may listen for a short 10–15 second follow-up window before sleeping again.
- Door locks, alarms, garage controls, purchases, and any action affecting security require an explicit confirmation.
- Voice identity is optional and never sufficient for a sensitive action by itself.

## Why not use Realtime for always-on listening

Realtime is useful for a live conversation after activation, but sending continuous room audio to it would cost more, weaken privacy, and make cloud availability a requirement. The wake word and silence detection belong locally; a Realtime mode can later be used only for the active conversation window if it proves worthwhile.

## Hardware rollout

1. Run ALI and Home Assistant on the home mini-PC.
2. Install one microphone/speaker satellite in the kitchen/living room and validate wake-word accuracy with normal TV and music noise.
3. Add the entrance and bedroom only after the first satellite is reliable.
4. Tune the "ALI" detector threshold in the real house. If false positives are too common, use “Oye ALI” internally while keeping ALI's spoken identity unchanged.
