# Progreso de NEXUS-IA

Reconstrucción del bot (la carpeta original se perdió; `app/`, `tests/` y `docs/` se rehicieron).

| Fase | Estado |
|------|--------|
| 0 – Base (Telegram + Groq + orquestador + memoria RAM) | ✅ |
| 1 – Núcleo de videojuegos | ✅ |
| 2 – Riesgo y robustez | ✅ |
| 3 – Diseño e interacción | ✅ |
| 4 – Personalización y gamificación | ✅ |
| 5 – Voz | ✅ |
| 6 – Inline y extras | ✅ |
| 7 – La mascota habla | ⏳ |

## Notas
- Los tests async corren con un hook propio en `tests/conftest.py` (sin pytest-asyncio).
- Los tests HTTP pasan por httpx real con `MockTransport`.
