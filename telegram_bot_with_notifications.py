"""
FamilyMeal Bot - VERSIÓN COMPLETA
Con inventario, recetas, MENÚ SEMANAL completo, lista de compra y notificaciones
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
 CREATE_RECIPE_NAME, SELECT_INGREDIENT_SECTION, SELECT_INGREDIENT_PRODUCT, 
 ADD_INGREDIENT_QUANTITY, SET_DEFROST_TIME,
 SELECT_MENU_DAY, SELECT_MENU_MEAL, SELECT_MENU_RECIPE) = range(13)

DAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MEALS = ['Comida', 'Cena']
SECTIONS = ['Despensa', 'Frigo', 'Congelador']


def get_week_to_display():
    """
    Determinar qué semana mostrar:
    - Si es Domingo después de las 12:00 → Semana siguiente
    - Resto de casos → Semana actual
    """
    now = datetime.now()
    
    # Si es Domingo (weekday=6) y son las 12:00 o más tarde
    if now.weekday() == 6 and now.hour >= 12:
        # Mostrar semana siguiente (desde el Lunes)
        monday = now.date() + timedelta(days=1)
    else:
        # Mostrar semana actual
        monday = now.date() - timedelta(days=now.weekday())
    
    week_dates = [monday + timedelta(days=i) for i in range(7)]
    return week_dates


def get_available_days():
    """Obtener solo los días disponibles desde MAÑANA hasta domingo"""
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    week_dates = get_week_to_display()
    # Filtrar desde mañana en adelante
    available = [(i, date) for i, date in enumerate(week_dates) if date >= tomorrow]
    return available


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
                "quantity": str(context.user_data['inv_stock']),
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
            item = supabase.table("inventory").select("*").eq("id", item_id).execute()
            if not item.data:
                await query.edit_message_text("❌ Producto no encontrado")
                return
            
            current_item = item.data[0]
            
            supabase.table("inventory")\
                .update({"stock": 1})\
                .eq("id", item_id)\
                .execute()
            
            await query.edit_message_text(f"✅ *{current_item['name']}* comprado (stock: 1)", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error: {e}")
            await query.edit_message_text(f"❌ Error: {e}")
    
    # ========== RECETAS ==========
    
    async def show_recipes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostrar recetas de la familia"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        if not family:
            await update.message.reply_text("❌ No perteneces a ninguna familia")
            return
        
        recipes = supabase.table("recipes")\
            .select("*")\
            .eq("family_id", family['id'])\
            .execute()
        
        if not recipes.data:
            text = "📖 *Recetas*\n\n_Aún no hay recetas._\n\n¡Crea la primera!"
        else:
            text = "📖 *Recetas de la familia*\n\n"
            for recipe in recipes.data:
                icon = "🧊" if recipe.get('needs_defrost') else "✅"
                text += f"{icon} {recipe['name']}\n"
        
        keyboard = [[InlineKeyboardButton("➕ Crear receta", callback_data="create_recipe")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def create_recipe_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Iniciar creación de receta"""
        query = update.callback_query
        await query.answer()
        
        context.user_data['recipe_ingredients'] = []
        context.user_data['recipe_needs_defrost'] = False
        
        await query.edit_message_text("📖 *Nueva receta*\n\n¿Nombre de la receta?", parse_mode='Markdown')
        return CREATE_RECIPE_NAME
    
    async def create_recipe_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Capturar nombre de receta y empezar con ingredientes"""
        recipe_name = update.message.text.strip()
        context.user_data['recipe_name'] = recipe_name
        
        await self.ask_ingredient_section(update, context)
        return SELECT_INGREDIENT_SECTION
    
    async def ask_ingredient_section(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Preguntar de qué sección es el ingrediente"""
        keyboard = [
            [InlineKeyboardButton("🧊 Congelador", callback_data="ing_sect_Congelador")],
            [InlineKeyboardButton("❄️ Frigo", callback_data="ing_sect_Frigo")],
            [InlineKeyboardButton("📦 Despensa", callback_data="ing_sect_Despensa")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"➕ *Añadir ingrediente*\n\n¿De dónde?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def select_ingredient_section(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Seleccionar sección y mostrar productos"""
        query = update.callback_query
        await query.answer()
        
        section = query.data.replace("ing_sect_", "")
        context.user_data['current_ing_section'] = section
        
        if section == "Congelador":
            context.user_data['recipe_needs_defrost'] = True
        
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        products = supabase.table("inventory")\
            .select("*")\
            .eq("family_id", family['id'])\
            .eq("section", section)\
            .gt("stock", 0)\
            .execute()
        
        if not products.data:
            await query.edit_message_text(
                f"❌ No hay productos en *{section}*\n\n"
                f"Añade productos al inventario primero.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        keyboard = []
        for product in products.data:
            keyboard.append([InlineKeyboardButton(
                f"{product['name']} (stock: {product['stock']})",
                callback_data=f"ing_prod_{product['id']}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        icon = "🧊" if section == "Congelador" else "❄️" if section == "Frigo" else "📦"
        await query.edit_message_text(
            f"{icon} *{section}*\n\nSelecciona producto:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return SELECT_INGREDIENT_PRODUCT
    
    async def select_ingredient_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Producto seleccionado, preguntar cantidad"""
        query = update.callback_query
        await query.answer()
        
        product_id = query.data.replace("ing_prod_", "")
        
        product = supabase.table("inventory").select("*").eq("id", product_id).execute()
        if not product.data:
            await query.edit_message_text("❌ Producto no encontrado")
            return ConversationHandler.END
        
        context.user_data['current_ingredient'] = product.data[0]
        
        await query.edit_message_text(
            f"📊 *{product.data[0]['name']}*\n\n¿Cuántas unidades?",
            parse_mode='Markdown'
        )
        return ADD_INGREDIENT_QUANTITY
    
    async def add_ingredient_quantity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Guardar cantidad y preguntar si añadir más ingredientes"""
        try:
            quantity = int(update.message.text.strip())
            
            ingredient_data = {
                'product_id': context.user_data['current_ingredient']['id'],
                'name': context.user_data['current_ingredient']['name'],
                'section': context.user_data['current_ingredient']['section'],
                'quantity': quantity
            }
            
            context.user_data['recipe_ingredients'].append(ingredient_data)
            
            ingredients_text = "\n".join([
                f"• {ing['name']} ({ing['quantity']} ud) - {ing['section']}"
                for ing in context.user_data['recipe_ingredients']
            ])
            
            keyboard = [
                [InlineKeyboardButton("➕ Otro ingrediente", callback_data="add_another_ing")],
                [InlineKeyboardButton("✅ Terminar receta", callback_data="finish_recipe")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ *Ingrediente añadido*\n\n"
                f"Receta: *{context.user_data['recipe_name']}*\n\n"
                f"Ingredientes:\n{ingredients_text}",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return SELECT_INGREDIENT_SECTION
            
        except ValueError:
            await update.message.reply_text("❌ Debe ser un número. Intenta de nuevo:")
            return ADD_INGREDIENT_QUANTITY
    
    async def add_another_ingredient(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Añadir otro ingrediente"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🧊 Congelador", callback_data="ing_sect_Congelador")],
            [InlineKeyboardButton("❄️ Frigo", callback_data="ing_sect_Frigo")],
            [InlineKeyboardButton("📦 Despensa", callback_data="ing_sect_Despensa")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"➕ *Añadir ingrediente*\n\n¿De dónde?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return SELECT_INGREDIENT_SECTION
    
    async def finish_recipe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Finalizar receta y preguntar hora si necesita descongelar"""
        query = update.callback_query
        await query.answer()
        
        needs_defrost = context.user_data.get('recipe_needs_defrost', False)
        
        if needs_defrost:
            await query.edit_message_text(
                "🧊 *Esta receta necesita descongelar*\n\n"
                "¿A qué hora quieres el recordatorio?\n"
                "(Formato: HH:MM, ej: 22:00 o 21:30)",
                parse_mode='Markdown'
            )
            return SET_DEFROST_TIME
        else:
            await self.save_recipe(update, context, query, "22:00")
            return ConversationHandler.END
    
    async def set_defrost_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Capturar hora de recordatorio y guardar receta"""
        reminder_time = update.message.text.strip()
        
        try:
            time_parts = reminder_time.split(":")
            if len(time_parts) != 2:
                raise ValueError
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            if hour < 0 or hour > 23:
                raise ValueError
            if minute not in [0, 30]:
                await update.message.reply_text(
                    "❌ Los minutos deben ser :00 o :30\n"
                    "Ej: 22:00, 21:30, 20:00\n\n"
                    "Intenta de nuevo:"
                )
                return SET_DEFROST_TIME
        except:
            await update.message.reply_text(
                "❌ Formato incorrecto.\n"
                "Usa HH:MM con minutos :00 o :30\n"
                "Ej: 22:00, 21:30\n\n"
                "Intenta de nuevo:"
            )
            return SET_DEFROST_TIME
        
        await self.save_recipe(update, context, None, reminder_time)
        return ConversationHandler.END
    
    async def save_recipe(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query, reminder_time: str):
        """Guardar receta e ingredientes en la BD"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        try:
            # Asegurar formato HH:MM:00 para la BD
            if len(reminder_time.split(':')) == 2:
                reminder_time = f"{reminder_time}:00"
            
            recipe_data = {
                "family_id": family['id'],
                "name": context.user_data['recipe_name'],
                "created_by": user['id'],
                "needs_defrost": context.user_data.get('recipe_needs_defrost', False),
                "defrost_reminder_time": reminder_time if context.user_data.get('recipe_needs_defrost', False) else None,
                "created_at": datetime.now().isoformat()
            }
            
            recipe_response = supabase.table("recipes").insert(recipe_data).execute()
            recipe_id = recipe_response.data[0]['id']
            
            for ingredient in context.user_data['recipe_ingredients']:
                ingredient_data = {
                    "recipe_id": recipe_id,
                    "ingredient_name": ingredient['name'],
                    "quantity": str(ingredient['quantity']),
                    "created_at": datetime.now().isoformat()
                }
                supabase.table("recipe_ingredients").insert(ingredient_data).execute()
            
            ingredients_text = "\n".join([
                f"• {ing['name']} ({ing['quantity']} ud)"
                for ing in context.user_data['recipe_ingredients']
            ])
            
            defrost_info = f"\n\n🧊 Recordatorio: {reminder_time}" if context.user_data.get('recipe_needs_defrost', False) else ""
            
            message = (
                f"✅ *Receta creada*\n\n"
                f"📖 {context.user_data['recipe_name']}\n\n"
                f"Ingredientes:\n{ingredients_text}"
                f"{defrost_info}"
            )
            
            if query:
                await query.edit_message_text(message, parse_mode='Markdown')
            else:
                await update.message.reply_text(message, parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Error: {e}")
            error_msg = f"❌ Error al guardar receta: {e}"
            if query:
                await query.edit_message_text(error_msg)
            else:
                await update.message.reply_text(error_msg)
    
    # ========== MENÚ SEMANAL ==========
    
    async def show_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostrar menú semanal"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        if not family:
            await update.message.reply_text("❌ No perteneces a ninguna familia")
            return
        
        week_dates = get_week_to_display()
        today = datetime.now().date()
        
        text = "📅 *Menú Semanal*\n\n"
        
        # Mostrar cada día
        for i, date in enumerate(week_dates):
            day_name = DAYS[i]
            is_today = (date == today)
            day_marker = " ← Hoy" if is_today else ""
            
            text += f"\n*{day_name} {date.strftime('%d/%m')}*{day_marker}\n"
            
            if date < today:
                text += "_Día pasado_\n"
                continue
            
            # Obtener comidas del día
            for meal_type in MEALS:
                meal_plan = supabase.table("meal_plans")\
                    .select("*, recipes(name, needs_defrost)")\
                    .eq("family_id", family['id'])\
                    .eq("date", str(date))\
                    .eq("meal_type", meal_type)\
                    .execute()
                
                meal_icon = "🍽️" if meal_type == "Comida" else "🌙"
                
                if meal_plan.data:
                    plan = meal_plan.data[0]
                    if plan.get('recipes'):
                        recipe_name = plan['recipes']['name']
                        defrost_icon = " 🧊" if plan['recipes'].get('needs_defrost') else ""
                        cooked_icon = " ✅" if plan.get('is_cooked') else ""
                        text += f"{meal_icon} {meal_type}: {recipe_name}{defrost_icon}{cooked_icon}\n"
                    elif plan.get('meal_text'):
                        text += f"{meal_icon} {meal_type}: {plan['meal_text']}\n"
                else:
                    text += f"{meal_icon} {meal_type}: -\n"
        
        keyboard = [
            [InlineKeyboardButton("➕ Añadir comida", callback_data="add_meal")],
            [InlineKeyboardButton("🗑️ Limpiar semana", callback_data="clear_week")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def add_meal_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Iniciar añadir comida al menú"""
        query = update.callback_query
        await query.answer()
        
        available_days = get_available_days()
        
        if not available_days:
            await query.edit_message_text("❌ No hay días disponibles esta semana")
            return ConversationHandler.END
        
        keyboard = []
        for day_idx, date in available_days:
            day_name = DAYS[day_idx]
            keyboard.append([InlineKeyboardButton(
                f"{day_name} {date.strftime('%d/%m')}",
                callback_data=f"menu_day_{day_idx}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "📅 *Añadir comida*\n\n¿Qué día?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return SELECT_MENU_DAY
    
    async def select_menu_day(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Seleccionar día"""
        query = update.callback_query
        await query.answer()
        
        day_idx = int(query.data.replace("menu_day_", ""))
        context.user_data['menu_day_idx'] = day_idx
        
        week_dates = get_week_to_display()
        date = week_dates[day_idx]
        context.user_data['menu_date'] = str(date)
        
        keyboard = [
            [InlineKeyboardButton("🍽️ Comida", callback_data="menu_meal_Comida")],
            [InlineKeyboardButton("🌙 Cena", callback_data="menu_meal_Cena")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        day_name = DAYS[day_idx]
        await query.edit_message_text(
            f"📅 *{day_name} {date.strftime('%d/%m')}*\n\n¿Comida o Cena?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return SELECT_MENU_MEAL
    
    async def select_menu_meal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Seleccionar comida o cena - directamente mostrar recetas"""
        query = update.callback_query
        await query.answer()
        
        meal_type = query.data.replace("menu_meal_", "")
        context.user_data['menu_meal_type'] = meal_type
        
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        recipes = supabase.table("recipes")\
            .select("*")\
            .eq("family_id", family['id'])\
            .execute()
        
        if not recipes.data:
            await query.edit_message_text(
                "❌ No hay recetas.\n\nCrea una primero en 📖 Recetas",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        keyboard = []
        for recipe in recipes.data:
            icon = "🧊" if recipe.get('needs_defrost') else "✅"
            keyboard.append([InlineKeyboardButton(
                f"{icon} {recipe['name']}",
                callback_data=f"menu_recipe_{recipe['id']}"
            )])
        
        # Añadir opción eliminar
        keyboard.append([InlineKeyboardButton("❌ Eliminar comida", callback_data="menu_opt_delete")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📖 *{meal_type}*\n\nSelecciona receta:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return SELECT_MENU_RECIPE
    
    async def select_menu_recipe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Guardar receta seleccionada en el menú O eliminar"""
        query = update.callback_query
        await query.answer()
        
        # Verificar si es opción de eliminar
        if query.data == "menu_opt_delete":
            await self.delete_meal_plan(update, context, query)
            return ConversationHandler.END
        
        recipe_id = query.data.replace("menu_recipe_", "")
        
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        try:
            # Obtener receta
            recipe = supabase.table("recipes").select("*").eq("id", recipe_id).execute()
            if not recipe.data:
                await query.edit_message_text("❌ Receta no encontrada")
                return ConversationHandler.END
            
            recipe_data = recipe.data[0]
            
            # Verificar si ya existe
            existing = supabase.table("meal_plans")\
                .select("id")\
                .eq("family_id", family['id'])\
                .eq("date", context.user_data['menu_date'])\
                .eq("meal_type", context.user_data['menu_meal_type'])\
                .execute()
            
            if existing.data:
                # Actualizar
                supabase.table("meal_plans")\
                    .update({
                        "recipe_id": recipe_id,
                        "meal_text": None,
                        "is_cooked": False,
                        "defrost_reminder_time": recipe_data.get('defrost_reminder_time') if recipe_data.get('needs_defrost') else None
                    })\
                    .eq("id", existing.data[0]['id'])\
                    .execute()
            else:
                # Crear
                meal_plan_data = {
                    "family_id": family['id'],
                    "date": context.user_data['menu_date'],
                    "meal_type": context.user_data['menu_meal_type'],
                    "recipe_id": recipe_id,
                    "created_by": user['id'],
                    "defrost_reminder_time": recipe_data.get('defrost_reminder_time') if recipe_data.get('needs_defrost') else None,
                    "created_at": datetime.now().isoformat()
                }
                supabase.table("meal_plans").insert(meal_plan_data).execute()
            
            defrost_info = ""
            if recipe_data.get('needs_defrost'):
                defrost_info = f"\n\n🔔 Notificación programada: {recipe_data.get('defrost_reminder_time', '22:00')}"
            
            await query.edit_message_text(
                f"✅ *Añadido*\n\n"
                f"{context.user_data['menu_meal_type']}: {recipe_data['name']}"
                f"{defrost_info}",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error: {e}")
            await query.edit_message_text(f"❌ Error: {e}")
            return ConversationHandler.END
    
    async def delete_meal_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query):
        """Eliminar comida del menú"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        try:
            supabase.table("meal_plans")\
                .delete()\
                .eq("family_id", family['id'])\
                .eq("date", context.user_data['menu_date'])\
                .eq("meal_type", context.user_data['menu_meal_type'])\
                .execute()
            
            await query.edit_message_text(f"✅ Eliminado")
        except Exception as e:
            logger.error(f"Error: {e}")
            await query.edit_message_text(f"❌ Error: {e}")
    
    async def clear_week(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostrar opciones para limpiar semana"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("✅ Marcar todo como cocinado", callback_data="clear_mark_cooked")],
            [InlineKeyboardButton("🗑️ Borrar sin marcar", callback_data="clear_delete")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="clear_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🗑️ *¿Qué quieres hacer con el menú?*\n\n"
            "✅ *Marcar cocinado:* Guarda que cocinaste todo (sin borrar el menú)\n"
            "🗑️ *Borrar:* Elimina todo directamente",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def clear_mark_cooked(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Marcar todo el menú como cocinado"""
        query = update.callback_query
        await query.answer()
        
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        try:
            week_dates = get_week_to_display()
            monday = str(week_dates[0])
            sunday = str(week_dates[6])
            
            # Marcar todo como cocinado
            supabase.table("meal_plans") \
                .update({
                    "is_cooked": True,
                    "cooked_at": datetime.now().isoformat()
                }) \
                .eq("family_id", family['id']) \
                .gte("date", monday) \
                .lte("date", sunday) \
                .execute()
            
            await query.edit_message_text(
                "✅ *Todo marcado como cocinado*\n\n"
                "El menú sigue visible. Usa 'Borrar' si quieres limpiarlo.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error: {e}")
            await query.edit_message_text(f"❌ Error: {e}")
    
    async def clear_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Borrar todo el menú sin marcar"""
        query = update.callback_query
        await query.answer()
        
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        
        user = await self.get_or_create_user(telegram_id, username, first_name)
        family = await self.get_user_family(user['id'])
        
        try:
            week_dates = get_week_to_display()
            monday = str(week_dates[0])
            sunday = str(week_dates[6])
            
            supabase.table("meal_plans") \
                .delete() \
                .eq("family_id", family['id']) \
                .gte("date", monday) \
                .lte("date", sunday) \
                .execute()
            
            await query.edit_message_text("✅ *Menú borrado*", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error: {e}")
            await query.edit_message_text(f"❌ Error: {e}")
    
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


# ========== NOTIFICATION SCHEDULER ==========

class NotificationScheduler:
    """Sistema de notificaciones automáticas"""
    
    def __init__(self, application):
        self.application = application
        self.scheduler = AsyncIOScheduler()
    
    def start(self):
        """Iniciar el scheduler"""
        # Ejecutar cada 30 minutos para permitir recordatorios a y media
        self.scheduler.add_job(
            self.check_and_send_reminders,
            trigger=CronTrigger(minute='0,30'),  # Ejecutar a las :00 y :30
            id='defrost_reminders',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("✅ Scheduler de notificaciones ACTIVADO")
        logger.info("   - Revisa cada 30 minutos si hay recordatorios pendientes")
    
    async def check_and_send_reminders(self):
        """Revisar y enviar recordatorios de descongelar"""
        logger.info("🔔 Ejecutando check de recordatorios...")
        
        try:
            # Hora actual
            now = datetime.now()
            # Redondear a :00 o :30
            if now.minute < 30:
                current_time = now.strftime("%H:00:00")
            else:
                current_time = now.strftime("%H:30:00")
            
            tomorrow = (now + timedelta(days=1)).date()
            
            # Buscar meal_plans para mañana con recordatorio a esta hora
            meal_plans = supabase.table("meal_plans")\
                .select("*, recipes(name, needs_defrost), families(id, name)")\
                .eq("date", str(tomorrow))\
                .eq("defrost_reminder_time", current_time)\
                .execute()
            
            if not meal_plans.data:
                logger.info(f"   No hay recordatorios para mañana {tomorrow} a las {current_time}")
                return
            
            logger.info(f"   Encontrados {len(meal_plans.data)} recordatorios")
            
            # Procesar cada meal_plan
            for plan in meal_plans.data:
                if not plan.get('recipes'):
                    continue
                
                if not plan['recipes'].get('needs_defrost'):
                    continue
                
                await self.send_defrost_reminder(plan, tomorrow)
        
        except Exception as e:
            logger.error(f"❌ Error en check_and_send_reminders: {e}")
    
    async def send_defrost_reminder(self, meal_plan, date):
        """Enviar recordatorio a todos los miembros de la familia"""
        try:
            family_id = meal_plan['families']['id']
            family_name = meal_plan['families']['name']
            recipe_name = meal_plan['recipes']['name']
            meal_type = meal_plan['meal_type']
            
            # Obtener ingredientes del congelador
            recipe_id = meal_plan['recipe_id']
            ingredients = supabase.table("recipe_ingredients")\
                .select("ingredient_name, quantity")\
                .eq("recipe_id", recipe_id)\
                .execute()
            
            # Filtrar solo ingredientes del congelador
            freezer_items = []
            if ingredients.data:
                for ing in ingredients.data:
                    # Buscar si el ingrediente está en el congelador
                    inv_item = supabase.table("inventory")\
                        .select("name, section")\
                        .eq("family_id", family_id)\
                        .eq("section", "Congelador")\
                        .ilike("name", f"%{ing['ingredient_name']}%")\
                        .execute()
                    
                    if inv_item.data:
                        freezer_items.append(f"• {ing['ingredient_name']} ({ing['quantity']} ud)")
            
            if not freezer_items:
                logger.info(f"   No hay ingredientes de congelador para {recipe_name}")
                return
            
            # Obtener miembros de la familia
            members = supabase.table("family_members")\
                .select("users(telegram_id)")\
                .eq("family_id", family_id)\
                .execute()
            
            if not members.data:
                logger.info(f"   No hay miembros en familia {family_name}")
                return
            
            # Formato de fecha
            day_name = DAYS[date.weekday()]
            date_formatted = date.strftime("%d/%m")
            
            # Crear mensaje
            items_text = "\n".join(freezer_items)
            message = (
                f"🧊 *Recordatorio de descongelar*\n\n"
                f"Para mañana ({day_name} {date_formatted}) necesitas sacar del congelador:\n\n"
                f"{items_text}\n\n"
                f"📖 Receta: *{recipe_name}*\n"
                f"🍽️ {meal_type}\n\n"
                f"¡No olvides descongelarlo esta noche!"
            )
            
            # Enviar a cada miembro
            sent_count = 0
            for member in members.data:
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
                        logger.error(f"   Error enviando a {telegram_id}: {e}")
            
            logger.info(f"   ✅ Recordatorio enviado a {sent_count} miembros: {recipe_name} ({meal_type})")
        
        except Exception as e:
            logger.error(f"❌ Error en send_defrost_reminder: {e}")


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
    
    # Crear receta
    recipe_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.create_recipe_start, pattern="^create_recipe$")],
        states={
            CREATE_RECIPE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.create_recipe_name)],
            SELECT_INGREDIENT_SECTION: [
                CallbackQueryHandler(bot.select_ingredient_section, pattern="^ing_sect_"),
                CallbackQueryHandler(bot.add_another_ingredient, pattern="^add_another_ing$"),
                CallbackQueryHandler(bot.finish_recipe, pattern="^finish_recipe$")
            ],
            SELECT_INGREDIENT_PRODUCT: [CallbackQueryHandler(bot.select_ingredient_product, pattern="^ing_prod_")],
            ADD_INGREDIENT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.add_ingredient_quantity)],
            SET_DEFROST_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.set_defrost_time)]
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)],
        allow_reentry=True
    )
    application.add_handler(recipe_conv)
    
    # Menú semanal
    menu_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.add_meal_start, pattern="^add_meal$")],
        states={
            SELECT_MENU_DAY: [CallbackQueryHandler(bot.select_menu_day, pattern="^menu_day_")],
            SELECT_MENU_MEAL: [CallbackQueryHandler(bot.select_menu_meal, pattern="^menu_meal_")],
            SELECT_MENU_RECIPE: [
                CallbackQueryHandler(bot.select_menu_recipe, pattern="^menu_recipe_"),
                CallbackQueryHandler(bot.select_menu_recipe, pattern="^menu_opt_delete$")
            ]
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)],
        allow_reentry=True
    )
    application.add_handler(menu_conv)
    
    # Limpiar semana
    application.add_handler(CallbackQueryHandler(bot.clear_week, pattern="^clear_week$"))
    application.add_handler(CallbackQueryHandler(bot.clear_mark_cooked, pattern="^clear_mark_cooked$"))
    application.add_handler(CallbackQueryHandler(bot.clear_delete, pattern="^clear_delete$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.edit_message_text("Cancelado"), pattern="^clear_cancel$"))
    
    # Marcar como comprado
    application.add_handler(CallbackQueryHandler(bot.mark_as_bought, pattern="^buy_"))
    
    # Botones del menú
    application.add_handler(MessageHandler(
        filters.Regex("^(📅 Menú Semanal|📖 Recetas|🏠 Inventario|🛒 Lista de Compra|👥 Mi Familia)$"),
        bot.menu_button_handler
    ))
    
    # Iniciar scheduler de notificaciones
    scheduler = NotificationScheduler(application)
    scheduler.start()
    
    logger.info("🤖 Bot iniciado - NOTIFICACIONES ACTIVAS ✅")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
