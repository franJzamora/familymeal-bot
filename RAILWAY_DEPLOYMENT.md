# 🚂 Guía de Deployment en Railway

## ¿Por qué Railway en lugar de Heroku?

**Heroku eliminó su plan gratuito en 2022.**

Railway ofrece:
- ✅ $5 USD de crédito GRATIS cada mes
- ✅ Tu bot consume ~$1-2/mes → GRATIS efectivo
- ✅ Interfaz moderna y fácil
- ✅ Deploy automático desde GitHub

---

## 📋 Requisitos Previos

1. Cuenta en GitHub (gratis)
2. Cuenta en Railway (gratis)
3. Tarjeta de crédito (NO cobra si <$5/mes)

---

## 🚀 Deployment en 15 minutos

### Paso 1: Preparar el proyecto

**1.1 Crear repositorio en GitHub**

```bash
# En tu carpeta del bot
git init
git add .
git commit -m "Initial commit"

# Crear repo en GitHub (via web o CLI)
gh repo create familymeal-bot --public --source=. --remote=origin --push
```

**1.2 Añadir archivos necesarios**

Railway necesita estos archivos en tu proyecto:

```
familymeal-bot/
├── telegram_bot_with_notifications.py
├── requirements.txt
├── .env.example
├── Procfile           ← CREAR
├── runtime.txt        ← CREAR
└── .gitignore         ← CREAR
```

**Crear `Procfile`:**
```bash
# Procfile (sin extensión)
worker: python telegram_bot_with_notifications.py
```

**Crear `runtime.txt`:**
```bash
# runtime.txt
python-3.11.7
```

**Crear `.gitignore`:**
```bash
# .gitignore
.env
__pycache__/
*.pyc
.DS_Store
venv/
env/
```

---

### Paso 2: Crear proyecto en Railway

**2.1 Ir a Railway**
- Ve a https://railway.app
- Click "Start a New Project"
- Login con GitHub

**2.2 Deploy desde GitHub**
- Click "Deploy from GitHub repo"
- Selecciona tu repositorio `familymeal-bot`
- Click "Deploy Now"

**2.3 Esperar deployment**
- Railway detecta Python automáticamente
- Instala dependencias de `requirements.txt`
- Tarda ~2-3 minutos

---

### Paso 3: Configurar Variables de Entorno

**3.1 Ir a Variables**
- En tu proyecto Railway → Tab "Variables"
- Click "+ New Variable"

**3.2 Añadir variables:**

```
TELEGRAM_BOT_TOKEN=tu_token_de_botfather
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=tu_anon_key
```

**3.3 Guardar y redeploy**
- Click "Add" para cada variable
- El bot se redesplegará automáticamente

---

### Paso 4: Verificar que funciona

**4.1 Ver logs**
- Tab "Deployments" → Click en el último
- Ver logs en tiempo real
- Deberías ver: "Bot iniciado..."

**4.2 Probar el bot**
- Abre Telegram
- Busca tu bot
- Envía `/start`
- ¡Debería responder!

---

## 🔍 Troubleshooting

### Error: "No module named 'telegram'"

**Solución:** Verifica `requirements.txt`

```txt
python-telegram-bot==20.7
supabase==2.3.4
python-dotenv==1.0.0
apscheduler==3.10.4
```

### Error: "TELEGRAM_BOT_TOKEN not found"

**Solución:** Añade variables de entorno en Railway

### Bot no responde

**Solución:** 
1. Verifica logs en Railway
2. Comprueba que el token es correcto
3. Verifica Supabase credentials

### "Exceeded free tier"

**Solución:**
- Revisa uso en Dashboard
- Tu bot debería usar <$2/mes
- Si supera $5, Railway empezará a cobrar

---

## 💰 Monitorear Costos

### Ver uso actual:
1. Railway Dashboard
2. Tu proyecto
3. Tab "Usage"

**Deberías ver:**
```
Current Usage: $1.23 / $5.00
Days remaining: 18
```

---

## 🔄 Updates Automáticos

**Cuando hagas cambios:**

```bash
# En tu PC
git add .
git commit -m "Añadir nueva función"
git push origin main
```

**Railway automáticamente:**
1. Detecta el push
2. Hace nuevo deploy
3. Actualiza el bot
4. Todo en ~2 minutos

---

## 📊 Alternativa: Railway CLI

**Instalar:**
```bash
npm i -g @railway/cli
```

**Desplegar:**
```bash
railway login
railway init
railway up
```

**Ver logs:**
```bash
railway logs
```

**Variables:**
```bash
railway variables set TELEGRAM_BOT_TOKEN=xxx
```

---

## ⚙️ Configuración Avanzada

### Mantener bot siempre activo

Por defecto Railway puede dormir el servicio. Para evitarlo:

**Opción 1: Watchdog (Ping interno)**

Añadir al bot:
```python
# Cada 5 minutos, hacer algo
scheduler.add_job(
    lambda: logger.info("Keepalive ping"),
    trigger=CronTrigger(minute='*/5')
)
```

**Opción 2: Cron-job externo**

Usar https://cron-job.org para hacer ping cada 10 min:
```
URL: https://tu-app.railway.app/health
Método: GET
Frecuencia: */10 * * * *
```

Y añadir endpoint al bot:
```python
from flask import Flask

app = Flask(__name__)

@app.route('/health')
def health():
    return 'OK', 200

# Correr Flask en thread separado
```

---

## 🎯 Checklist Final

- [ ] Código en GitHub
- [ ] Procfile creado
- [ ] runtime.txt con Python 3.11+
- [ ] requirements.txt actualizado
- [ ] Proyecto creado en Railway
- [ ] Variables de entorno configuradas
- [ ] Bot desplegado correctamente
- [ ] Logs muestran "Bot iniciado"
- [ ] Bot responde a /start
- [ ] Notificaciones probadas

---

## 📈 Escalado

### Si tu bot crece:

**Hasta 50 familias:**
- Plan gratuito suficiente
- ~$2/mes de uso

**50-500 familias:**
- Plan Developer: $5/mes base
- +uso adicional

**500+ familias:**
- Considera múltiples workers
- O migrar a VPS

---

## 🆚 Railway vs Heroku

| Feature | Railway | Heroku |
|---------|---------|--------|
| **Precio** | $5 crédito/mes | $5/mes mínimo |
| **Costo real** | $0-2/mes = GRATIS | $5/mes siempre |
| **Deploy** | Git push | Git push |
| **Logs** | Tiempo real | Tiempo real |
| **CLI** | ✅ Moderno | ✅ Clásico |
| **Interfaz** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |

**Ganador:** Railway (gratis + mejor)

---

## 🔐 Seguridad

### Variables de entorno:
- ✅ NUNCA commits .env al repo
- ✅ Usa Railway Variables
- ✅ Tokens en lugar de contraseñas

### GitHub:
- ✅ Repo puede ser público (sin credenciales)
- ✅ .gitignore debe incluir .env

### Supabase:
- ✅ Usa anon key (no service_role)
- ✅ RLS activo en todas las tablas

---

## 🎓 Recursos

- [Railway Docs](https://docs.railway.app/)
- [Railway Examples](https://railway.app/examples)
- [Railway Discord](https://discord.gg/railway)

---

## 💡 Tips Finales

1. **Monitorea uso semanalmente** en Railway Dashboard
2. **Activa notificaciones** si superas $3/mes
3. **Usa Railway CLI** para deploy rápido
4. **Logs son tu amigo** para debugging
5. **Git push = autodeploy** (muy cómodo)

---

## 🎉 ¡Listo!

Tu bot está corriendo 24/7 en la nube, gratis, con notificaciones automáticas funcionando.

**Siguiente paso:** ¡Úsalo con tu familia! 🍽️
