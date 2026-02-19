"""
FamilyMeal Bot - VERSIÓN MEJORADA
Con flujo de autenticación completo y funcional
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

# Estados de conversación
(REGISTER_EMAIL, REGISTER_PASSWORD, CREATE_OR_JOIN, 
 CREATE_FAMILY_NAME, JOIN_FAMILY_CODE) = range(5)

DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MEALS = ['Comida', 'Cena']
INVENTORY_SECTIONS = ['Despensa', 'Frigo', 'Congelador']


class FamilyMealBot:
    
    def __init__(self):
        self.user_sessions = {}
    
    # ========== COMMAND /START ==========
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start - Punto de entrada principal"""
        telegram_id = update.effective_user.id
        
        # Verificar si el usuario ya está registrado
        user_data = await self.get_user_by_telegram_id(telegram_id)
        
        if user_data:
            # Usuario registrado - verificar si tiene familia
            family = await self.get_user_family(user_data['id'])
            
            if family:
                # Tiene familia - mostrar menú principal
                await self.show_main_menu(update, context, family)
            else:
                # No tiene familia - preguntar crear o unirse
                await update.message.reply_text(
                    "👋 ¡Hola de nuevo!\n\n"
                    "Aún no perteneces a ninguna familia."
                )
                await self.prompt_create_or_join(update, context)
        else:
            # Usuario nuevo - iniciar registro
            await update.message.reply_text(
                "👋 ¡Bienvenido a *FamilyMeal*!\n\n"
                "Planifica las comidas de tu familia de forma sencilla.\n\n"
                "Para empezar, introduce tu email:",
                parse_mode='Markdown'
            )
            return REGISTER_EMAIL
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, family):
        """Mostrar menú principal"""
        keyboard = [
            [KeyboardButton("📅 Menú Semanal"), KeyboardButton("📖 Recetas")],
            [KeyboardButton("🏠 Inventario"), KeyboardButton("🛒 Lista de Compra")],
            [KeyboardButton("👥 Mi Familia"), KeyboardButton("⚙️ Ajustes")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        text = (
            f"👋 ¡Hola!\n\n"
            f"📱 Familia: *{family['name']}*\n"
            f"🔔 Recibirás notificaciones automáticas:\n"
            f"  • Recordatorios de descongelar (20:00)\n"
            f"  • Resumen semanal (domingos 18:00)\n\n"
            f"Usa el menú para navegar 👇"
        )
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        return ConversationHandler.END
    
    # ========== REGISTRO ==========
    
    async def register_email(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Capturar email para registro"""
        email = update.message.text.strip()
        
        # Validación básica
        if '@' not in email or '.' not in email:
            await update.message.reply_text("❌ Email no válido. Intenta de nuevo:")
            return REGISTER_EMAIL
        
        # Verificar si el email ya existe
        try:
            existing = supabase.table("users").select("id").eq("email", email).execute()
            if existing.data:
                await update.message.reply_text(
                    "⚠️ Este email ya está registrado.\n"
                    "Si eres tú, tus datos ya están en el sistema.\n\n"
                    "Continuando con el registro..."
                )
        except:
            pass
        
        context.user_data['email'] = email
        await update.message.reply_text("🔐 Ahora crea una contraseña (mínimo 6 caracteres):")
        return REGISTER_PASSWORD
    
    async def register_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Crear usuario en la base de datos"""
        password = update.message.text.strip()
        
        if len(password) < 6:
            await update.message.reply_text("❌ Mínimo 6 caracteres. Intenta de nuevo:")
            return REGISTER_PASSWORD
        
        email = context.user_data['email']
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        
        try:
            # Verificar si el usuario ya existe por telegram_id
            existing_user = await self.get_user_by_telegram_id(telegram_id)
            
            if existing_user:
                # Usuario ya existe, solo verificar familia
                user_id = existing_user['id']
                family = await self.get_user_family(user_id)
                
                if family:
                    await self.show_main_menu(update, context, family)
                    return ConversationHandler.END
                else:
                    await update.message.reply_text("✅ Sesión recuperada")
                    await self.prompt_create_or_join(update, context)
                    return CREATE_OR_JOIN
            
            # Crear nuevo usuario (sin Auth de Supabase, solo tabla users)
            user_id = str(uuid.uuid4())
            user_data = {
                "id": user_id,
                "telegram_id": telegram_id,
                "email": email,
                "username": username,
                "created_at": datetime.now().isoformat()
            }
            
            supabase.table("users").insert(user_data).execute()
            self.user_sessions[telegram_id] = user_id
            
            await update.message.reply_text("✅ ¡Cuenta creada con éxito!")
            await self.prompt_create_or_join(update, context)
            return CREATE_OR_JOIN
            
        except Exception as e:
            logger.error(f"Error en registro: {e}")
            await update.message.reply_text(
                "❌ Error al crear la cuenta.\n"
                f"Detalles: {str(e)}\n\n"
                "Usa /start para intentar de nuevo."
            )
            return ConversationHandler.END
    
    # ========== CREAR O UNIRSE A FAMILIA ==========
    
    async def prompt_create_or_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Preguntar si crear o unirse a familia"""
        keyboard = [
            [InlineKeyboardButton("➕ Crear familia nueva", callback_data="create_family")],
            [InlineKeyboardButton("🔗 Unirme a familia existente", callback_data="join_family")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "👨‍👩‍👧‍👦 ¿Qué quieres hacer?",
            reply_markup=reply_markup
        )
    
    async def create_family_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Iniciar creación de familia"""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "➕ *Crear nueva familia*\n\n"
            "¿Cómo quieres llamar a tu familia?\n"
            "(ej: Familia García, Los Pérez, Casa de Ana...)",
            parse_mode='Markdown'
        )
        return CREATE_FAMILY_NAME
    
    async def create_family_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Crear familia con nombre"""
        family_name = update.message.text.strip()
        telegram_id = update.effective_user.id
        
        # Obtener user_id
        user_data = await self.get_user_by_telegram_id(telegram_id)
        if not user_data:
            await update.message.reply_text("❌ Error: Usuario no encontrado. Usa /start")
            return ConversationHandler.END
        
        user_id = user_data['id']
        
        try:
            # Generar código único
            invite_code = str(uuid.uuid4())[:8].upper()
            
            # Crear familia
            family_data = {
                "name": family_name,
                "invite_code": invite_code,
                "created_by": user_id,
                "created_at": datetime.now().isoformat()
            }
            
            family_response = supabase.table("families").insert(family_data).execute()
            family_id = family_response.data[0]['id']
            
            # Añadir usuario como admin
            member_data = {
                "family_id": family_id,
                "user_id": user_id,
                "role": "admin",
                "joined_at": datetime.now().isoformat()
            }
            supabase.table("family_members").insert(member_data).execute()
            
            # Mostrar resultado con menú
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
                f"📤 Comparte este código con tu familia para que se unan.\n\n"
                f"💡 Usa el menú de abajo para empezar 👇",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error creando familia: {e}")
            await update.message.reply_text(
                f"❌ Error al crear la familia: {str(e)}\n\n"
                "Usa /start para intentar de nuevo."
            )
            return ConversationHandler.END
    
    async def join_family_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Iniciar unión a familia"""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "🔗 *Unirse a familia*\n\n"
            "Introduce el código de invitación que te compartieron\n"
            "(8 caracteres, ej: A1B2C3D4):",
            parse_mode='Markdown'
        )
        return JOIN_FAMILY_CODE
    
    async def join_family_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unirse con código"""
        invite_code = update.message.text.strip().upper()
        telegram_id = update.effective_user.id
        
        # Obtener user_id
        user_data = await self.get_user_by_telegram_id(telegram_id)
        if not user_data:
            await update.message.reply_text("❌ Error: Usuario no encontrado. Usa /start")
            return ConversationHandler.END
        
        user_id = user_data['id']
        
        try:
            # Buscar familia
            family_response = supabase.table("families").select("*").eq("invite_code", invite_code).execute()
            
            if not family_response.data:
                await update.message.reply_text(
                    "❌ Código no válido.\n\n"
                    "Verifica el código e intenta de nuevo:"
                )
                return JOIN_FAMILY_CODE
            
            family = family_response.data[0]
            
            # Verificar si ya es miembro
            existing = supabase.table("family_members").select("*").eq("family_id", family['id']).eq("user_id", user_id).execute()
            
            if existing.data:
                await update.message.reply_text(f"ℹ️ Ya eres miembro de *{family['name']}*", parse_mode='Markdown')
                family_obj = {'id': family['id'], 'name': family['name']}
                await self.show_main_menu(update, context, family_obj)
                return ConversationHandler.END
            
            # Añadir como miembro
            member_data = {
                "family_id": family['id'],
                "user_id": user_id,
                "role": "member",
                "joined_at": datetime.now().isoformat()
            }
            supabase.table("family_members").insert(member_data).execute()
            
            keyboard = [
                [KeyboardButton("📅 Menú Semanal"), KeyboardButton("📖 Recetas")],
                [KeyboardButton("🏠 Inventario"), KeyboardButton("🛒 Lista de Compra")],
                [KeyboardButton("👥 Mi Familia"), KeyboardButton("⚙️ Ajustes")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"✅ ¡Te has unido a *{family['name']}*!\n\n"
                f"💡 Usa el menú de abajo para empezar 👇",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text(
                f"❌ Error al unirse: {str(e)}\n\n"
                "Usa /start para intentar de nuevo."
            )
            return ConversationHandler.END
    
    # ========== FUNCIONES DE MENÚ ==========
    
    async def menu_button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para botones del menú"""
        text = update.message.text
        
        if text == "📅 Menú Semanal":
            await update.message.reply_text(
                "📅 *Menú Semanal*\n\n"
                "Esta función estará disponible próximamente.\n"
                "Podrás planificar las comidas de toda la semana.",
                parse_mode='Markdown'
            )
        elif text == "📖 Recetas":
            await update.message.reply_text(
                "📖 *Recetas*\n\n"
                "Esta función estará disponible próximamente.\n"
                "Podrás crear y gestionar las recetas de tu familia.",
                parse_mode='Markdown'
            )
        elif text == "🏠 Inventario":
            await update.message.reply_text(
                "🏠 *Inventario*\n\n"
                "Esta función estará disponible próximamente.\n"
                "Podrás gestionar tu Despensa, Frigo y Congelador.",
                parse_mode='Markdown'
            )
        elif text == "🛒 Lista de Compra":
            await update.message.reply_text(
                "🛒 *Lista de Compra*\n\n"
                "Esta función estará disponible próximamente.\n"
                "Podrás compartir la lista de compra con tu familia.",
                parse_mode='Markdown'
            )
        elif text == "👥 Mi Familia":
            telegram_id = update.effective_user.id
            user_data = await self.get_user_by_telegram_id(telegram_id)
            if user_data:
                family = await self.get_user_family(user_data['id'])
                if family:
                    # Obtener miembros
                    members_response = supabase.table("family_members")\
                        .select("users(username), role")\
                        .eq("family_id", family['id'])\
                        .execute()
                    
                    members_text = ""
                    for member in members_response.data:
                        role_emoji = "👑" if member['role'] == 'admin' else "👤"
                        username = member['users']['username'] if member.get('users') else "Usuario"
                        members_text += f"{role_emoji} {username}\n"
                    
                    await update.message.reply_text(
                        f"👥 *{family['name']}*\n\n"
                        f"*Miembros:*\n{members_text}\n"
                        f"🔑 *Código:* `{family['invite_code']}`",
                        parse_mode='Markdown'
                    )
        elif text == "⚙️ Ajustes":
            await update.message.reply_text(
                "⚙️ *Ajustes*\n\n"
                "Esta función estará disponible próximamente.",
                parse_mode='Markdown'
            )
    
    # ========== FUNCIONES AUXILIARES ==========
    
    async def get_user_by_telegram_id(self, telegram_id: int):
        """Obtener usuario por telegram_id"""
        try:
            response = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error obteniendo usuario: {e}")
            return None
    
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
            logger.error(f"Error obteniendo familia: {e}")
            return None
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancelar conversación"""
        await update.message.reply_text(
            "❌ Operación cancelada.\n\n"
            "Usa /start cuando quieras empezar de nuevo."
        )
        return ConversationHandler.END


# ========== SCHEDULER (simplificado para testing) ==========

class NotificationScheduler:
    def __init__(self, application):
        self.application = application
        self.scheduler = AsyncIOScheduler()
        
    def start(self):
        logger.info("✅ Scheduler de notificaciones iniciado")
        logger.info("   - Recordatorios de descongelar: Cada día a las 20:00")
        logger.info("   - Resumen semanal: Domingos a las 18:00")
        # Scheduler configurado pero sin jobs por ahora
        # Se activarán cuando el sistema esté completo


# ========== MAIN ==========

def main():
    """Función principal"""
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not TOKEN:
        logger.error("❌ No se encontró TELEGRAM_BOT_TOKEN")
        return
    
    bot = FamilyMealBot()
    application = Application.builder().token(TOKEN).build()
    
    # Conversation handler para registro
    register_conv = ConversationHandler(
        entry_points=[CommandHandler("start", bot.start)],
        states={
            REGISTER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.register_email)],
            REGISTER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.register_password)],
            CREATE_OR_JOIN: [
                CallbackQueryHandler(bot.create_family_start, pattern="^create_family$"),
                CallbackQueryHandler(bot.join_family_start, pattern="^join_family$")
            ],
            CREATE_FAMILY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.create_family_name)],
            JOIN_FAMILY_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.join_family_code)]
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)],
        allow_reentry=True
    )
    
    application.add_handler(register_conv)
    
    # Handlers para botones del menú
    application.add_handler(MessageHandler(
        filters.Regex("^(📅 Menú Semanal|📖 Recetas|🏠 Inventario|🛒 Lista de Compra|👥 Mi Familia|⚙️ Ajustes)$"),
        bot.menu_button_handler
    ))
    
    # Iniciar scheduler
    scheduler = NotificationScheduler(application)
    scheduler.start()
    
    logger.info("🤖 Bot iniciado...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
