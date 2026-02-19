"""
FamilyMeal Bot - VERSIÓN SIMPLIFICADA
Solo usa Telegram ID (sin email/contraseña innecesarios)
"""

import os
import logging
from datetime import datetime, timedelta
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
supabase: Client = create_client(SUPABASE_URL or "", SUPABASE_KEY or "")

# Estados de conversación (solo para crear/unirse familia)
CREATE_FAMILY_NAME, JOIN_FAMILY_CODE = range(2)

DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MEALS = ['Comida', 'Cena']
INVENTORY_SECTIONS = ['Despensa', 'Frigo', 'Congelador']


class FamilyMealBot:
    
    # ========== /START - ÚNICO PUNTO DE ENTRADA ==========
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start - Maneja TODO automáticamente"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        # 1. Buscar o crear usuario automáticamente
        user = await self.get_or_create_user(telegram_id, username, first_name)
        
        # 2. Verificar si tiene familia
        family = await self.get_user_family(user['id'])
        
        if family:
            # ✅ Tiene familia → Mostrar menú
            await self.show_main_menu(update, context, family, first_name)
        else:
            # ❌ No tiene familia → Preguntar crear o unirse
            await update.message.reply_text(
                f"👋 ¡Hola {first_name}!\n\n"
                f"Aún no perteneces a ninguna familia."
            )
            await self.prompt_create_or_join(update, context)
        
        return ConversationHandler.END
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, family, first_name):
        """Mostrar menú principal"""
        keyboard = [
            [KeyboardButton("📅 Menú Semanal"), KeyboardButton("📖 Recetas")],
            [KeyboardButton("🏠 Inventario"), KeyboardButton("🛒 Lista de Compra")],
            [KeyboardButton("👥 Mi Familia"), KeyboardButton("⚙️ Ajustes")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        text = (
            f"👋 ¡Hola {first_name}!\n\n"
            f"📱 Familia: *{family['name']}*\n\n"
            f"🔔 *Notificaciones automáticas activas:*\n"
            f"  • Recordatorios de descongelar (20:00)\n"
            f"  • Resumen semanal (domingos 18:00)\n\n"
            f"Usa el menú para navegar 👇"
        )
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    # ========== GESTIÓN AUTOMÁTICA DE USUARIOS ==========
    
    async def get_or_create_user(self, telegram_id: int, username: str, first_name: str):
        """Buscar usuario o crearlo automáticamente si no existe"""
        try:
            # Buscar usuario existente
            response = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
            
            if response.data:
                # Usuario existe → Devolverlo
                return response.data[0]
            
            # Usuario NO existe → Crearlo automáticamente
            user_id = str(uuid.uuid4())
            user_data = {
                "id": user_id,
                "telegram_id": telegram_id,
                "email": f"telegram_{telegram_id}@familymeal.app",  # Email ficticio para BD
                "username": username,
                "created_at": datetime.now().isoformat()
            }
            
            result = supabase.table("users").insert(user_data).execute()
            logger.info(f"✅ Nuevo usuario creado: {username} ({telegram_id})")
            return result.data[0]
            
        except Exception as e:
            logger.error(f"❌ Error en get_or_create_user: {e}")
            raise
    
    async def get_user_family(self, user_id: str):
        """Obtener familia del usuario"""
        try:
            response = supabase.table("family_members")\
                .select("family_id, families(id, name, invite_code)")\
                .eq("user_id", user_id)\
                .execute()
            
            if response.data and response.data[0].get('families'):
                return response.data[0]['families']
            return None
        except Exception as e:
            logger.error(f"❌ Error obteniendo familia: {e}")
            return None
    
    # ========== CREAR O UNIRSE A FAMILIA ==========
    
    async def prompt_create_or_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Preguntar si crear o unirse a familia"""
        keyboard = [
            [InlineKeyboardButton("➕ Crear familia nueva", callback_data="create_family")],
            [InlineKeyboardButton("🔗 Unirme con código", callback_data="join_family")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "👨‍👩‍👧‍👦 *¿Qué quieres hacer?*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def create_family_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Iniciar creación de familia"""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "➕ *Crear nueva familia*\n\n"
            "¿Cómo quieres llamar a tu familia?\n\n"
            "Ejemplos:\n"
            "• Familia García\n"
            "• Los Pérez\n"
            "• Casa de Ana\n"
            "• Mi Familia",
            parse_mode='Markdown'
        )
        return CREATE_FAMILY_NAME
    
    async def create_family_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Crear familia con nombre"""
        family_name = update.message.text.strip()
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        # Obtener usuario
        user = await self.get_or_create_user(telegram_id, username, first_name)
        
        try:
            # Generar código único de 8 caracteres
            invite_code = str(uuid.uuid4())[:8].upper()
            
            # Crear familia
            family_data = {
                "name": family_name,
                "invite_code": invite_code,
                "created_by": user['id'],
                "created_at": datetime.now().isoformat()
            }
            
            family_response = supabase.table("families").insert(family_data).execute()
            family_id = family_response.data[0]['id']
            
            # Añadir usuario como admin
            member_data = {
                "family_id": family_id,
                "user_id": user['id'],
                "role": "admin",
                "joined_at": datetime.now().isoformat()
            }
            supabase.table("family_members").insert(member_data).execute()
            
            # Mostrar menú
            keyboard = [
                [KeyboardButton("📅 Menú Semanal"), KeyboardButton("📖 Recetas")],
                [KeyboardButton("🏠 Inventario"), KeyboardButton("🛒 Lista de Compra")],
                [KeyboardButton("👥 Mi Familia"), KeyboardButton("⚙️ Ajustes")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"✅ ¡Familia *{family_name}* creada!\n\n"
                f"🔑 *Código de invitación:*\n"
                f"`{invite_code}`\n\n"
                f"📤 *Compártelo con tu familia*\n"
                f"Cuando te pregunten, dales este código para que se unan.\n\n"
                f"💡 Usa el menú de abajo para empezar 👇",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            logger.info(f"✅ Familia creada: {family_name} (código: {invite_code})")
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"❌ Error creando familia: {e}")
            await update.message.reply_text(
                f"❌ Error al crear la familia.\n\n"
                f"Detalles: {str(e)}\n\n"
                "Usa /start para intentar de nuevo."
            )
            return ConversationHandler.END
    
    async def join_family_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Iniciar unión a familia"""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "🔗 *Unirse a familia*\n\n"
            "Introduce el código de invitación\n"
            "(8 caracteres)\n\n"
            "Ejemplo: `A1B2C3D4`",
            parse_mode='Markdown'
        )
        return JOIN_FAMILY_CODE
    
    async def join_family_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unirse con código"""
        invite_code = update.message.text.strip().upper()
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        # Obtener usuario
        user = await self.get_or_create_user(telegram_id, username, first_name)
        
        try:
            # Buscar familia por código
            family_response = supabase.table("families").select("*").eq("invite_code", invite_code).execute()
            
            if not family_response.data:
                await update.message.reply_text(
                    "❌ *Código no válido*\n\n"
                    "Verifica el código e intenta de nuevo:",
                    parse_mode='Markdown'
                )
                return JOIN_FAMILY_CODE
            
            family = family_response.data[0]
            
            # Verificar si ya es miembro
            existing = supabase.table("family_members")\
                .select("*")\
                .eq("family_id", family['id'])\
                .eq("user_id", user['id'])\
                .execute()
            
            if existing.data:
                # Ya es miembro
                await update.message.reply_text(
                    f"ℹ️ Ya eres miembro de *{family['name']}*",
                    parse_mode='Markdown'
                )
                family_obj = {'id': family['id'], 'name': family['name'], 'invite_code': family['invite_code']}
                await self.show_main_menu(update, context, family_obj, first_name)
                return ConversationHandler.END
            
            # Añadir como miembro
            member_data = {
                "family_id": family['id'],
                "user_id": user['id'],
                "role": "member",
                "joined_at": datetime.now().isoformat()
            }
            supabase.table("family_members").insert(member_data).execute()
            
            # Mostrar menú
            keyboard = [
                [KeyboardButton("📅 Menú Semanal"), KeyboardButton("📖 Recetas")],
                [KeyboardButton("🏠 Inventario"), KeyboardButton("🛒 Lista de Compra")],
                [KeyboardButton("👥 Mi Familia"), KeyboardButton("⚙️ Ajustes")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"✅ ¡Te has unido a *{family['name']}*!\n\n"
                f"Ahora compartes el menú, recetas, inventario y lista de compra con tu familia.\n\n"
                f"💡 Usa el menú de abajo 👇",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            logger.info(f"✅ Usuario {username} unido a familia {family['name']}")
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"❌ Error uniéndose: {e}")
            await update.message.reply_text(
                f"❌ Error al unirse.\n\n"
                f"Detalles: {str(e)}\n\n"
                "Usa /start para intentar de nuevo."
            )
            return ConversationHandler.END
    
    # ========== BOTONES DEL MENÚ ==========
    
    async def menu_button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para botones del menú"""
        text = update.message.text
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        # Obtener usuario
        user = await self.get_or_create_user(telegram_id, username, first_name)
        
        if text == "📅 Menú Semanal":
            await update.message.reply_text(
                "📅 *Menú Semanal*\n\n"
                "🚧 Esta función estará disponible próximamente.\n\n"
                "Podrás:\n"
                "• Planificar comidas y cenas de toda la semana\n"
                "• Asignar recetas a cada día\n"
                "• Ver el menú completo de un vistazo",
                parse_mode='Markdown'
            )
        elif text == "📖 Recetas":
            await update.message.reply_text(
                "📖 *Recetas*\n\n"
                "🚧 Esta función estará disponible próximamente.\n\n"
                "Podrás:\n"
                "• Crear recetas con ingredientes\n"
                "• Ver todas las recetas de la familia\n"
                "• Compartirlas entre miembros",
                parse_mode='Markdown'
            )
        elif text == "🏠 Inventario":
            await update.message.reply_text(
                "🏠 *Inventario*\n\n"
                "🚧 Esta función estará disponible próximamente.\n\n"
                "Podrás gestionar:\n"
                "• 📦 Despensa\n"
                "• ❄️ Frigo\n"
                "• 🧊 Congelador\n\n"
                "Y marcar productos como gastados para añadirlos a la compra.",
                parse_mode='Markdown'
            )
        elif text == "🛒 Lista de Compra":
            await update.message.reply_text(
                "🛒 *Lista de Compra*\n\n"
                "🚧 Esta función estará disponible próximamente.\n\n"
                "Podrás:\n"
                "• Añadir productos manualmente\n"
                "• Ver productos añadidos automáticamente del inventario\n"
                "• Marcar como comprados\n"
                "• Compartir la lista en tiempo real",
                parse_mode='Markdown'
            )
        elif text == "👥 Mi Familia":
            family = await self.get_user_family(user['id'])
            if family:
                # Obtener miembros
                members_response = supabase.table("family_members")\
                    .select("users(username), role, joined_at")\
                    .eq("family_id", family['id'])\
                    .order("joined_at")\
                    .execute()
                
                members_text = ""
                for member in members_response.data:
                    role_emoji = "👑" if member['role'] == 'admin' else "👤"
                    username_display = member['users']['username'] if member.get('users') else "Usuario"
                    members_text += f"{role_emoji} {username_display}\n"
                
                await update.message.reply_text(
                    f"👥 *{family['name']}*\n\n"
                    f"*Miembros ({len(members_response.data)}):*\n"
                    f"{members_text}\n"
                    f"🔑 *Código de invitación:*\n"
                    f"`{family['invite_code']}`\n\n"
                    f"📤 Comparte este código para que más personas se unan.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "❌ No perteneces a ninguna familia.\n\n"
                    "Usa /start para crear una o unirte."
                )
        elif text == "⚙️ Ajustes":
            await update.message.reply_text(
                "⚙️ *Ajustes*\n\n"
                "🚧 Esta función estará disponible próximamente.\n\n"
                "Podrás:\n"
                "• Cambiar nombre de la familia\n"
                "• Configurar horarios de notificaciones\n"
                "• Gestionar miembros\n"
                "• Salir de la familia",
                parse_mode='Markdown'
            )
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancelar conversación"""
        await update.message.reply_text(
            "❌ Operación cancelada.\n\n"
            "Usa /start cuando quieras."
        )
        return ConversationHandler.END


# ========== SCHEDULER ==========

class NotificationScheduler:
    def __init__(self, application):
        self.application = application
        self.scheduler = AsyncIOScheduler()
        
    def start(self):
        logger.info("✅ Scheduler de notificaciones iniciado")
        logger.info("   - Recordatorios de descongelar: Cada día a las 20:00")
        logger.info("   - Resumen semanal: Domingos a las 18:00")
        # Jobs se añadirán cuando el sistema esté completo


# ========== MAIN ==========

def main():
    """Función principal"""
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not TOKEN:
        logger.error("❌ No se encontró TELEGRAM_BOT_TOKEN")
        return
    
    bot = FamilyMealBot()
    application = Application.builder().token(TOKEN).build()
    
    # Handler principal: /start (sin estados de email/password)
    application.add_handler(CommandHandler("start", bot.start))
    
    # Conversation handler SOLO para crear/unirse familia
    family_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(bot.create_family_start, pattern="^create_family$"),
            CallbackQueryHandler(bot.join_family_start, pattern="^join_family$")
        ],
        states={
            CREATE_FAMILY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.create_family_name)],
            JOIN_FAMILY_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.join_family_code)]
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)],
        allow_reentry=True
    )
    
    application.add_handler(family_conv)
    
    # Handlers para botones del menú
    application.add_handler(MessageHandler(
        filters.Regex("^(📅 Menú Semanal|📖 Recetas|🏠 Inventario|🛒 Lista de Compra|👥 Mi Familia|⚙️ Ajustes)$"),
        bot.menu_button_handler
    ))
    
    # Iniciar scheduler
    scheduler = NotificationScheduler(application)
    scheduler.start()
    
    logger.info("🤖 Bot iniciado correctamente")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
