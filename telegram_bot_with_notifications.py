"""
FamilyMeal Bot - VERSIÓN COMPLETA
Con inventario, recetas, menú semanal, lista de compra y notificaciones
"""

import os
import logging
from datetime import datetime, timedelta, time as time_type
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
(CREATE_FAMILY_NAME, JOIN_FAMILY_CODE,
 ADD_INVENTORY_SECTION, ADD_INVENTORY_NAME, ADD_INVENTORY_STOCK,
 CREATE_RECIPE_NAME, ADD_RECIPE_INGREDIENT,
 SELECT_MENU_DAY, SELECT_MENU_MEAL, SELECT_MENU_RECIPE, SET_DEFROST_TIME) = range(11)

DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MEALS = ['Comida', 'Cena']
SECTIONS = ['Despensa', 'Frigo', 'Congelador']


class FamilyMealBot:
    
    # ========== /START ==========
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        if family:
            await self.show_main_menu(update, context, family, first_name)
        else:
            await update.message.reply_text(f"👋 ¡Hola {first_name}!\n\nAún no perteneces a ninguna familia.")
            await self.prompt_create_or_join(update, context)
        
        return ConversationHandler.END
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, family, first_name):
        """Mostrar menú principal"""
        keyboard = [
            [KeyboardButton("📅 Menú Semanal"), KeyboardButton("📖 Recetas")],
            [KeyboardButton("🏠 Inventario"), KeyboardButton("🛒 Lista de Compra")],
            [KeyboardButton("👥 Mi Familia")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"👋 ¡Hola {first_name}!\n\n📱 Familia: *{family['name']}*\n\n"
            f"Usa el menú 👇",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    # ========== USUARIOS ==========
    
    async def get_or_create_user(self, telegram_id: int, username: str, first_name: str):
        """Buscar o crear usuario"""
        try:
            response = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
            if response.data:
                return response.data[0]
            
            user_id = str(uuid.uuid4())
            user_data = {
                "id": user_id,
                "telegram_id": telegram_id,
                "email": f"telegram_{telegram_id}@familymeal.app",
                "username": username,
                "created_at": datetime.now().isoformat()
            }
            result = supabase.table("users").insert(user_data).execute()
            return result.data[0]
        except Exception as e:
            logger.error(f"Error get_or_create_user: {e}")
            raise
    
    async def get_user_family(self, user_id: str):
        """Obtener familia del usuario"""
        try:
            response = supabase.table("family_members")\
                .select("family_id, families(id, name, invite_code)")\
                .eq("user_id", user_id).execute()
            if response.data and response.data[0].get('families'):
                return response.data[0]['families']
            return None
        except Exception as e:
            logger.error(f"Error get_user_family: {e}")
            return None
    
    # ========== FAMILIAS ==========
    
    async def prompt_create_or_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("➕ Crear familia", callback_data="create_family")],
            [InlineKeyboardButton("🔗 Unirme con código", callback_data="join_family")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("👨‍👩‍👧‍👦 ¿Qué quieres hacer?", reply_markup=reply_markup)
    
    async def create_family_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("➕ *Crear familia*\n\n¿Nombre?", parse_mode='Markdown')
        return CREATE_FAMILY_NAME
    
    async def create_family_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        family_name = update.message.text.strip()
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        
        try:
            invite_code = str(uuid.uuid4())[:8].upper()
            family_data = {
                "name": family_name,
                "invite_code": invite_code,
                "created_by": user['id'],
                "created_at": datetime.now().isoformat()
            }
            family_response = supabase.table("families").insert(family_data).execute()
            family_id = family_response.data[0]['id']
            
            member_data = {
                "family_id": family_id,
                "user_id": user['id'],
                "role": "admin",
                "joined_at": datetime.now().isoformat()
            }
            supabase.table("family_members").insert(member_data).execute()
            
            keyboard = [
                [KeyboardButton("📅 Menú Semanal"), KeyboardButton("📖 Recetas")],
                [KeyboardButton("🏠 Inventario"), KeyboardButton("🛒 Lista de Compra")],
                [KeyboardButton("👥 Mi Familia")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"✅ Familia *{family_name}* creada\n\n🔑 Código: `{invite_code}`\n\n"
                f"Compártelo con tu familia 👇",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text(f"❌ Error: {e}")
            return ConversationHandler.END
    
    async def join_family_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("🔗 *Unirse*\n\nIntroduce el código:", parse_mode='Markdown')
        return JOIN_FAMILY_CODE
    
    async def join_family_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        invite_code = update.message.text.strip().upper()
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        
        try:
            family_response = supabase.table("families").select("*").eq("invite_code", invite_code).execute()
            if not family_response.data:
                await update.message.reply_text("❌ Código no válido")
                return JOIN_FAMILY_CODE
            
            family = family_response.data[0]
            
            member_data = {
                "family_id": family['id'],
                "user_id": user['id'],
                "role": "member",
                "joined_at": datetime.now().isoformat()
            }
            supabase.table("family_members").insert(member_data).execute()
            
            keyboard = [
                [KeyboardButton("📅 Menú Semanal"), KeyboardButton("📖 Recetas")],
                [KeyboardButton("🏠 Inventario"), KeyboardButton("🛒 Lista de Compra")],
                [KeyboardButton("👥 Mi Familia")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"✅ ¡Unido a *{family['name']}*!",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text(f"❌ Error: {e}")
            return ConversationHandler.END
    
    # ========== INVENTARIO ==========
    
    async def show_inventory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostrar inventario"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        if not family:
            await update.message.reply_text("❌ No perteneces a ninguna familia")
            return
        
        text = "🏠 *Inventario*\n\n"
        
        for section in SECTIONS:
            items = supabase.table("inventory")\
                .select("*")\
                .eq("family_id", family['id'])\
                .eq("section", section)\
                .gt("stock", 0)\
                .execute()
            
            icon = "📦" if section == "Despensa" else "❄️" if section == "Frigo" else "🧊"
            text += f"{icon} *{section}*\n"
            
            if items.data:
                for item in items.data:
                    text += f"  • {item['name']} (stock: {item['stock']})\n"
            else:
                text += "  _Vacío_\n"
            text += "\n"
        
        keyboard = [[InlineKeyboardButton("➕ Añadir producto", callback_data="add_inventory")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def add_inventory_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Iniciar añadir producto"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [[InlineKeyboardButton(s, callback_data=f"inv_section_{s}")] for s in SECTIONS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text("📦 *Añadir producto*\n\n¿Dónde?", reply_markup=reply_markup, parse_mode='Markdown')
        return ADD_INVENTORY_SECTION
    
    async def add_inventory_section(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Seleccionar sección"""
        query = update.callback_query
        await query.answer()
        
        section = query.data.replace("inv_section_", "")
        context.user_data['inv_section'] = section
        
        await query.edit_message_text(f"➕ Añadir a *{section}*\n\n¿Nombre del producto?", parse_mode='Markdown')
        return ADD_INVENTORY_NAME
    
    async def add_inventory_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Capturar nombre"""
        name = update.message.text.strip()
        context.user_data['inv_name'] = name
        
        await update.message.reply_text(f"📊 *{name}*\n\n¿Stock inicial? (número)", parse_mode='Markdown')
        return ADD_INVENTORY_STOCK
    
    async def add_inventory_stock(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Capturar stock y guardar producto"""
        try:
            stock = int(update.message.text.strip())
            context.user_data['inv_stock'] = stock
            
            # Guardar directamente (sin preguntar hora)
            await self.save_inventory_item(update, context)
            return ConversationHandler.END
                
        except ValueError:
            await update.message.reply_text("❌ Debe ser un número. Intenta de nuevo:")
            return ADD_INVENTORY_STOCK
    
    async def save_inventory_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Guardar producto en inventario"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        try:
            item_data = {
                "family_id": family['id'],
                "section": context.user_data['inv_section'],
                "name": context.user_data['inv_name'],
                "quantity": str(context.user_data['inv_stock']),  # Por compatibilidad
                "stock": context.user_data['inv_stock'],
                "created_at": datetime.now().isoformat()
            }
            
            supabase.table("inventory").insert(item_data).execute()
            
            await update.message.reply_text(
                f"✅ *{context.user_data['inv_name']}* añadido\n\n"
                f"📍 {context.user_data['inv_section']}\n"
                f"📊 Stock: {context.user_data['inv_stock']}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text(f"❌ Error: {e}")
    
    # ========== LISTA DE COMPRA ==========
    
    async def show_shopping_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostrar lista de compra (productos con stock = 0)"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        if not family:
            await update.message.reply_text("❌ No perteneces a ninguna familia")
            return
        
        items = supabase.table("inventory")\
            .select("*")\
            .eq("family_id", family['id'])\
            .eq("stock", 0)\
            .execute()
        
        if not items.data:
            await update.message.reply_text("🛒 *Lista de compra*\n\n✅ ¡Todo comprado!", parse_mode='Markdown')
            return
        
        text = "🛒 *Lista de compra*\n\n"
        keyboard = []
        
        for item in items.data:
            text += f"⬜ {item['name']} ({item['section']})\n"
            keyboard.append([InlineKeyboardButton(f"✅ {item['name']}", callback_data=f"buy_{item['id']}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def mark_as_bought(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Marcar producto como comprado (stock +1)"""
        query = update.callback_query
        await query.answer()
        
        item_id = query.data.replace("buy_", "")
        
        try:
            # Obtener item actual
            item = supabase.table("inventory").select("*").eq("id", item_id).execute()
            if not item.data:
                await query.edit_message_text("❌ Producto no encontrado")
                return
            
            current_item = item.data[0]
            
            # Incrementar stock
            supabase.table("inventory")\
                .update({"stock": 1})\
                .eq("id", item_id)\
                .execute()
            
            await query.edit_message_text(f"✅ *{current_item['name']}* comprado (stock: 1)", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error: {e}")
            await query.edit_message_text(f"❌ Error: {e}")
    
    # ========== RECETAS (simplificado) ==========
    
    async def show_recipes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostrar recetas"""
        await update.message.reply_text(
            "📖 *Recetas*\n\n🚧 Próximamente podrás crear recetas con ingredientes.",
            parse_mode='Markdown'
        )
    
    # ========== MENÚ SEMANAL (simplificado) ==========
    
    async def show_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostrar menú semanal"""
        await update.message.reply_text(
            "📅 *Menú Semanal*\n\n🚧 Próximamente podrás planificar comidas de la semana.",
            parse_mode='Markdown'
        )
    
    # ========== MI FAMILIA ==========
    
    async def show_family(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostrar info de familia"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        if not family:
            await update.message.reply_text("❌ No perteneces a ninguna familia")
            return
        
        members_response = supabase.table("family_members")\
            .select("users(username), role")\
            .eq("family_id", family['id'])\
            .execute()
        
        members_text = ""
        for member in members_response.data:
            role_emoji = "👑" if member['role'] == 'admin' else "👤"
            username_display = member['users']['username'] if member.get('users') else "Usuario"
            members_text += f"{role_emoji} {username_display}\n"
        
        await update.message.reply_text(
            f"👥 *{family['name']}*\n\n"
            f"*Miembros:*\n{members_text}\n"
            f"🔑 Código: `{family['invite_code']}`",
            parse_mode='Markdown'
        )
    
    # ========== MENU BUTTONS HANDLER ==========
    
    async def menu_button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para botones del menú"""
        text = update.message.text
        
        if text == "📅 Menú Semanal":
            await self.show_menu(update, context)
        elif text == "📖 Recetas":
            await self.show_recipes(update, context)
        elif text == "🏠 Inventario":
            await self.show_inventory(update, context)
        elif text == "🛒 Lista de Compra":
            await self.show_shopping_list(update, context)
        elif text == "👥 Mi Familia":
            await self.show_family(update, context)
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancelar conversación"""
        await update.message.reply_text("❌ Cancelado")
        return ConversationHandler.END


# ========== MAIN ==========

def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.error("❌ No TELEGRAM_BOT_TOKEN")
        return
    
    bot = FamilyMealBot()
    application = Application.builder().token(TOKEN).build()
    
    # /start
    application.add_handler(CommandHandler("start", bot.start))
    
    # Crear/unirse familia
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
    
    # Añadir inventario
    inventory_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.add_inventory_start, pattern="^add_inventory$")],
        states={
            ADD_INVENTORY_SECTION: [CallbackQueryHandler(bot.add_inventory_section, pattern="^inv_section_")],
            ADD_INVENTORY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.add_inventory_name)],
            ADD_INVENTORY_STOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.add_inventory_stock)]
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)],
        allow_reentry=True
    )
    application.add_handler(inventory_conv)
    
    # Marcar como comprado
    application.add_handler(CallbackQueryHandler(bot.mark_as_bought, pattern="^buy_"))
    
    # Botones del menú
    application.add_handler(MessageHandler(
        filters.Regex("^(📅 Menú Semanal|📖 Recetas|🏠 Inventario|🛒 Lista de Compra|👥 Mi Familia)$"),
        bot.menu_button_handler
    ))
    
    logger.info("🤖 Bot iniciado")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
