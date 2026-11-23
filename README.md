# NEXUS-IA

Bot de Telegram de recomendación de videojuegos. La lógica vive en un orquestador que usa un LLM (Groq, vía cliente OpenAI-compatible) por una interfaz de proveedor intercambiable; los precios y cuentas los calcula el código, el modelo solo redacta.

**Estado:** reconstrucción por fases, ver [docs/PROGRESS.md](docs/PROGRESS.md).

## Requisitos
- Windows + PowerShell
- Python 3.15.2 (probado con esta versión)

## Instalación (PowerShell, desde la raíz del proyecto)
```powershell
python -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements-dev.txt
```
Si PowerShell bloquea el script de activación: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
Para reproducir exactamente el entorno probado: `pip install -r backend\requirements.lock.txt`.

## Configuración
```powershell
Copy-Item backend\.env.example backend\.env
notepad backend\.env   # completa TELEGRAM_BOT_TOKEN, GROQ_API_KEY y GROQ_MODEL
```
`backend\.env` está en `.gitignore`. Nunca compartas ni subas tokens.

## Pruebas
```powershell
cd backend; .venv\Scripts\python -m pytest -q
```

## Ejecución
```powershell
cd backend
.venv\Scripts\python -m app.main
```

## Estructura
`backend/app/` (config, llm, core, sources, games, bot, …), `backend/tests/`, `docs/`.

## Funciones
- Recomendaciones y busqueda por texto libre (genero, plataforma, presupuesto en COP/USD), comparacion, veredicto contra el minimo historico, ficha de juego, `/gratis`.
- Panel con mascota, teclado fijo, tarjetas con botones, animo, gustos, trivia, XP/racha/cofre/logros, voz (notas de voz y boton 🔊), modo inline, `/estado`.
- Seguridad emocional por reglas con prioridad absoluta (123 y Linea 106).
- Cada funcion tiene su flag en `backend\.env` (ver `backend\.env.example`).

## Ejecucion con reinicio automatico
```powershell
.\start_bot.ps1
```
Reinicia con backoff si el bot se cae y escribe logs (con secretos enmascarados) en `backend\logs\`.
