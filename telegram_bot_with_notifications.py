"""
FamilyMeal Bot con NOTIFICACIONES AUTOMÁTICAS
Usando APScheduler para enviar recordatorios programados
"""

import os
import logging
from datetime import datetime, timedelta, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters
from supabase import create_client, Client
import uuid
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Estados (mismos que antes)
(REGISTER_EMAIL, REGISTER_PASSWORD, CREATE_OR_JOIN, 
 CREATE_FAMILY_NAME, JOIN_FAMILY_CODE) = range(5)

DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MEALS = ['Comida', 'Cena']
INVENTORY_SECTIONS = ['Despensa', 'Frigo', 'Congelador']


class NotificationScheduler:
    """Gestor de notificaciones programadas"""
    
    def __init__(self, application):
        self.application = application
        self.scheduler = AsyncIOScheduler()
        
    def start(self):
        """Iniciar el scheduler"""
        # Tarea diaria a las 20:00 (8 PM) para recordatorios de descongelar
        self.scheduler.add_job(
            self.send_defrost_reminders,
            trigger=CronTrigger(hour=20, minute=0),  # Cada día a las 20:00
            id='defrost_reminders',
            replace_existing=True
        )
        
        # Opcional: Resumen semanal los domingos a las 18:00
        self.scheduler.add_job(
            self.send_weekly_summary,
            trigger=CronTrigger(day_of_week='sun', hour=18, minute=0),
            id='weekly_summary',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("✅ Scheduler de notificaciones iniciado")
        logger.info("   - Recordatorios de descongelar: Cada día a las 20:00")
        logger.info("   - Resumen semanal: Domingos a las 18:00")
    
    async def send_defrost_reminders(self):
        """Enviar recordatorios de descongelar a TODAS las familias"""
        logger.info("🔔 Ejecutando recordatorios de descongelar...")
        
        try:
            # Obtener todas las familias activas
            families_response = supabase.table("families").select("id, name").execute()
            
            for family in families_response.data:
                await self._check_and_notify_family(family['id'], family['name'])
                
        except Exception as e:
            logger.error(f"❌ Error enviando recordatorios: {e}")
    
    async def _check_and_notify_family(self, family_id: str, family_name: str):
        """Verificar y notificar a una familia específica"""
        try:
            # Obtener comidas de mañana
            tomorrow = datetime.now().date() + timedelta(days=1)
            
            plans_response = supabase.table("meal_plans")\
                .select("*, recipes(id, name)")\
                .eq("family_id", family_id)\
                .eq("date", str(tomorrow))\
                .execute()
            
            if not plans_response.data:
                return  # No hay comidas planificadas para mañana
            
            # Buscar ingredientes congelados
            items_to_defrost = []
            meal_details = []
            
            for plan in plans_response.data:
                if plan.get('recipes'):
                    recipe_name = plan['recipes']['name']
                    meal_type = plan['meal_type']
                    
                    # Obtener ingredientes de la receta
                    ingredients_response = supabase.table("recipe_ingredients")\
                        .select("ingredient_name")\
                        .eq("recipe_id", plan['recipes']['id'])\
                        .execute()
                    
                    if ingredients_response.data:
                        ingredient_names = [ing['ingredient_name'] for ing in ingredients_response.data]
                        
                        # Buscar cuáles están en el congelador
                        for ing_name in ingredient_names:
                            inventory_response = supabase.table("inventory")\
                                .select("name")\
                                .eq("family_id", family_id)\
                                .eq("section", "Congelador")\
                                .ilike("name", f"%{ing_name}%")\
                                .execute()
                            
                            if inventory_response.data:
                                items_to_defrost.append(inventory_response.data[0]['name'])
                                meal_details.append(f"{meal_type}: {recipe_name}")
            
            # Si hay ingredientes congelados, notificar a todos los miembros
            if items_to_defrost:
                await self._notify_family_members(
                    family_id, 
                    family_name, 
                    tomorrow, 
                    set(items_to_defrost),
                    set(meal_details)
                )
                
        except Exception as e:
            logger.error(f"❌ Error verificando familia {family_id}: {e}")
    
    async def _notify_family_members(self, family_id: str, family_name: str, 
                                    date, items: set, meals: set):
        """Enviar notificación a todos los miembros de una familia"""
        try:
            # Obtener todos los miembros de la familia
            members_response = supabase.table("family_members")\
                .select("users(telegram_id)")\
                .eq("family_id", family_id)\
                .execute()
            
            if not members_response.data:
                return
            
            # Construir mensaje
            message = f"🧊 *Recordatorio - {family_name}*\n\n"
            message += f"Para mañana ({date.strftime('%d/%m')}) hay que descongelar:\n\n"
            
            for item in items:
                message += f"  • {item}\n"
            
            message += f"\n📅 Comidas planificadas:\n"
            for meal in meals:
                message += f"  • {meal}\n"
            
            message += f"\n💡 ¡Sácalos del congelador esta noche!"
            
            # Enviar a cada miembro
            sent_count = 0
            for member in members_response.data:
                if member.get('users') and member['users'].get('telegram_id'):
                    telegram_id = member['users']['telegram_id']
                    try:
                        await self.application.bot.send_message(
                            chat_id=telegram_id,
                            text=message,
                            parse_mode='Markdown'
                        )
                        sent_count += 1
                    except Exception as e:
                        logger.error(f"No se pudo enviar a {telegram_id}: {e}")
            
            logger.info(f"✅ Notificaciones enviadas a {sent_count} miembros de {family_name}")
            
        except Exception as e:
            logger.error(f"❌ Error notificando familia {family_id}: {e}")
    
    async def send_weekly_summary(self):
        """Enviar resumen semanal del menú"""
        logger.info("📊 Enviando resúmenes semanales...")
        
        try:
            families_response = supabase.table("families").select("id, name").execute()
            
            for family in families_response.data:
                await self._send_family_weekly_summary(family['id'], family['name'])
                
        except Exception as e:
            logger.error(f"❌ Error enviando resúmenes: {e}")
    
    async def _send_family_weekly_summary(self, family_id: str, family_name: str):
        """Enviar resumen semanal a una familia"""
        try:
            # Obtener el menú de la próxima semana
            next_monday = datetime.now().date() + timedelta(days=(7 - datetime.now().weekday()))
            
            message = f"📅 *Menú de la semana - {family_name}*\n"
            message += f"Semana del {next_monday.strftime('%d/%m')}\n\n"
            
            has_meals = False
            
            for i, day in enumerate(DAYS):
                day_date = next_monday + timedelta(days=i)
                
                plans_response = supabase.table("meal_plans")\
                    .select("meal_type, meal_text, recipes(name)")\
                    .eq("family_id", family_id)\
                    .eq("date", str(day_date))\
                    .execute()
                
                if plans_response.data:
                    has_meals = True
                    message += f"*{day}*\n"
                    for plan in plans_response.data:
                        content = plan.get('meal_text') or \
                                (plan['recipes']['name'] if plan.get('recipes') else 'Sin nombre')
                        message += f"  {plan['meal_type']}: {content}\n"
                    message += "\n"
            
            if not has_meals:
                message += "_No hay comidas planificadas aún_\n"
            
            message += "\n💡 Usa /start para planificar o modificar el menú"
            
            # Enviar a todos los miembros
            members_response = supabase.table("family_members")\
                .select("users(telegram_id)")\
                .eq("family_id", family_id)\
                .execute()
            
            for member in members_response.data:
                if member.get('users') and member['users'].get('telegram_id'):
                    telegram_id = member['users']['telegram_id']
                    try:
                        await self.application.bot.send_message(
                            chat_id=telegram_id,
                            text=message,
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"No se pudo enviar a {telegram_id}: {e}")
            
            logger.info(f"✅ Resumen semanal enviado a {family_name}")
            
        except Exception as e:
            logger.error(f"❌ Error en resumen semanal: {e}")


class FamilyMealBot:
    """Bot principal (versión simplificada - incluye solo setup)"""
    
    def __init__(self):
        self.user_sessions = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start"""
        user_id = update.effective_user.id
        user_data = await self.get_user_by_telegram_id(user_id)
        
        if user_data:
            family = await self.get_user_family(user_data['id'])
            if family:
                keyboard = [
                    [KeyboardButton("📅 Menú Semanal"), KeyboardButton("📖 Recetas")],
                    [KeyboardButton("🏠 Inventario"), KeyboardButton("🛒 Lista de Compra")],
                    [KeyboardButton("👥 Mi Familia"), KeyboardButton("⚙️ Ajustes")]
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await update.message.reply_text(
                    f"👋 ¡Hola!\n\nFamilia: *{family['name']}*\n"
                    f"Recibirás notificaciones automáticas:\n"
                    f"  🧊 Recordatorios de descongelar (20:00)\n"
                    f"  📅 Resumen semanal (domingos 18:00)\n\n"
                    f"Usa el menú para navegar 👇",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "👋 ¡Bienvenido!\n\nPara empezar, introduce tu email:"
                )
                return REGISTER_EMAIL
        else:
            await update.message.reply_text(
                "👋 ¡Bienvenido a *FamilyMeal*!\n\n"
                "Para empezar, introduce tu email:",
                parse_mode='Markdown'
            )
            return REGISTER_EMAIL
    
    # ... (resto de métodos como en telegram_bot_complete.py)
    
    async def get_user_by_telegram_id(self, telegram_id: int):
        try:
            response = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
            return response.data[0] if response.data else None
        except:
            return None
    
    async def get_user_family(self, user_id: str):
        try:
            response = supabase.table("family_members").select("families(*)").eq("user_id", user_id).execute()
            if response.data and response.data[0].get('families'):
                return response.data[0]['families']
            return None
        except:
            return None
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ Cancelado")
        return ConversationHandler.END


def main():
    """Función principal con scheduler integrado"""
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.error("❌ No TELEGRAM_BOT_TOKEN")
        return
    
    bot = FamilyMealBot()
    application = Application.builder().token(TOKEN).build()
    
    # ============================================
    # INICIALIZAR NOTIFICACIONES AUTOMÁTICAS
    # ============================================
    notification_scheduler = NotificationScheduler(application)
    notification_scheduler.start()
    
    # Handlers básicos
    register_handler = ConversationHandler(
        entry_points=[CommandHandler("start", bot.start)],
        states={
            REGISTER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: None)],
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)]
    )
    
    application.add_handler(register_handler)
    
    logger.info("🤖 Bot iniciado con notificaciones automáticas...")
    logger.info("   📬 Las notificaciones se enviarán automáticamente")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
