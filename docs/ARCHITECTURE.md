# Arquitectura de NEXUS-IA

```
backend/app/
  config.py            Settings (pydantic-settings, lee backend/.env; flags por funcion)
  logging_setup.py     logs a consola/archivo con secretos enmascarados
  personality.py       personalidad unica de NEXUS (charla, consejos por codigo, reacciones)
  analysis/analyzer.py riesgo emocional por reglas (prioridad absoluta)
  core/                memory (RAM), orchestrator (LLM + cupos), risk_guard (30 min), safety (compuerta)
  llm/                 LLMProvider, GroqProvider (cliente openai), budget (tokens globales/por usuario/cooldown)
  sources/             http (UA ASCII, cache TTL, reintentos), cheapshark, steam (cc=CO), epic, trm
  games/               budget (montos), filters, service (calculos y veredictos), pipeline (intenciones), render
  features/            mood (RAM 2 h), store (SQLite: XP/racha/cofre/logros/gustos), trivia, install
  voice/               tts (edge-tts, OGG/OPUS con ffmpeg o MP3), install (whisper + boton 🔊)
  bot/                 handlers, panel, cards, mascot, keyboard, callbacks, inline, persona, send, typing
  tools/last_result.py ultimo resultado por usuario/chat (30 min)
backend/config/        catalog.json (curado), trivia.json (30 preguntas, todas "revisar": true)
assets/mascot/         welcome|thinking|happy|sad|angry|sleepy|stressed|excited|relaxed|gift|trophy|quiz .mp4/.gif/.png/.jpg
```

Principios: el modelo solo redacta; precios, descuentos, presupuestos y conversiones los calcula el codigo;
si no hay dato se dice; cada funcion tiene su flag y degrada sin error visible; el riesgo emocional se evalua
antes que cualquier otra cosa (texto, voz, teclado, botones, inline).
