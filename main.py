# ================= SERVEUR WEB POUR HEALTH CHECK RENDER =================
import threading
from flask import Flask, jsonify
import os
from datetime import datetime

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "bot": "online",
        "timestamp": datetime.now().isoformat()
    }), 200

def run_webserver():
    port = int(os.getenv('PORT', 10000))
    print(f"✅ Serveur health check démarré sur le port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

threading.Thread(target=run_webserver, daemon=True).start()
# =========================================================================

# ================= PYTHON 3.13 AUDIO PATCH =================
import sys, types
if sys.version_info >= (3, 13):
    sys.modules['audioop'] = types.ModuleType('audioop')

# ================= IMPORTS =================
import os
import sqlite3
import io
from datetime import datetime
from typing import Optional, List
import discord
from discord.ext import commands
from discord import app_commands

# ================= CONFIG =================
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_USER_ID = 1399234120214909010

# ================= DATABASE =================
DB_PATH = "data.db"

def init_db():
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = db.cursor()
    
    c.execute("""CREATE TABLE IF NOT EXISTS allowed_roles(
        guild_id INT,
        role_id INT,
        action_type TEXT,
        PRIMARY KEY(guild_id, role_id, action_type)
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS protected_users(
        guild_id INT,
        user_id INT,
        protected_by INT,
        PRIMARY KEY(guild_id, user_id)
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS guild_config(
        guild_id INT PRIMARY KEY,
        jugement_channel_id INT,
        mention_role_id INT,
        logs_channel_id INT
    )""")
    
    db.commit()
    return db, c

db, cursor = init_db()

# ================= UTILITAIRES =================
def get_allowed_roles(gid, action):
    cursor.execute("SELECT role_id FROM allowed_roles WHERE guild_id=? AND action_type=?", (gid, action))
    return [r[0] for r in cursor.fetchall()]

def is_role_allowed(gid, role_id, action):
    cursor.execute("SELECT 1 FROM allowed_roles WHERE guild_id=? AND role_id=? AND action_type=?", 
                  (gid, role_id, action))
    return cursor.fetchone() is not None

def add_allowed_role(gid, role_id, action):
    cursor.execute("INSERT OR REPLACE INTO allowed_roles VALUES(?,?,?)", (gid, role_id, action))
    db.commit()

def remove_allowed_role(gid, role_id, action):
    cursor.execute("DELETE FROM allowed_roles WHERE guild_id=? AND role_id=? AND action_type=?", 
                  (gid, role_id, action))
    db.commit()

def get_guild_config(gid):
    cursor.execute("SELECT jugement_channel_id, mention_role_id, logs_channel_id FROM guild_config WHERE guild_id=?", (gid,))
    return cursor.fetchone()

def set_guild_config(gid, jugement_channel=None, mention_role=None, logs_channel=None):
    current = get_guild_config(gid)
    
    if current:
        cursor.execute("""UPDATE guild_config SET 
            jugement_channel_id = COALESCE(?, jugement_channel_id),
            mention_role_id = COALESCE(?, mention_role_id),
            logs_channel_id = COALESCE(?, logs_channel_id)
            WHERE guild_id=?""", 
            (jugement_channel, mention_role, logs_channel, gid))
    else:
        cursor.execute("INSERT INTO guild_config VALUES(?,?,?,?)", 
                      (gid, jugement_channel, mention_role, logs_channel))
    db.commit()

def is_protected(gid, uid):
    cursor.execute("SELECT 1 FROM protected_users WHERE guild_id=? AND user_id=?", (gid, uid))
    return cursor.fetchone() is not None

def add_protected(gid, uid, pid):
    cursor.execute("INSERT OR REPLACE INTO protected_users VALUES(?,?,?)", (gid, uid, pid))
    db.commit()

def rem_protected(gid, uid):
    cursor.execute("DELETE FROM protected_users WHERE guild_id=? AND user_id=?", (gid, uid))
    db.commit()

def get_protected(gid):
    cursor.execute("SELECT user_id, protected_by FROM protected_users WHERE guild_id=?", (gid,))
    return cursor.fetchall()

def reset_database_from_file(file_content):
    global db, cursor
    db.close()
    with open(DB_PATH, 'wb') as f:
        f.write(file_content)
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = db.cursor()
    return True

# ================= BOT =================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

WHITE = discord.Color.from_rgb(255, 255, 255)

# ================= VIEW POUR PROTECTED PAGINATION =================
class ProtectedPaginationView(discord.ui.View):
    def __init__(self, guild, protected_list, user_mentions, protector_mentions):
        super().__init__(timeout=60)
        self.guild = guild
        self.protected_list = protected_list
        self.user_mentions = user_mentions
        self.protector_mentions = protector_mentions
        self.current_page = 0
        self.items_per_page = 10
        self.total_pages = (len(protected_list) + self.items_per_page - 1) // self.items_per_page
        self.update_buttons()
    
    def get_current_page_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        current_users = self.user_mentions[start:end]
        current_protectors = self.protector_mentions[start:end]
        
        embed = discord.Embed(
            title="**Liste des utilisateurs protect**",
            color=WHITE
        )
        
        for i in range(len(current_users)):
            embed.add_field(
                name=f"Protéger : {current_users[i]}",
                value=f"Par : {current_protectors[i]}",
                inline=False
            )
        
        embed.set_footer(text=f"utilisateurs proteger : {len(self.protected_list)}")
        return embed
    
    def update_buttons(self):
        self.clear_items()
        
        left_button = discord.ui.Button(
            label="◀",
            style=discord.ButtonStyle.primary,
            custom_id="left"
        )
        left_button.callback = self.left_callback
        self.add_item(left_button)
        
        page_button = discord.ui.Button(
            label=f"{self.current_page + 1}/{self.total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            custom_id="page"
        )
        self.add_item(page_button)
        
        right_button = discord.ui.Button(
            label="▶",
            style=discord.ButtonStyle.primary,
            custom_id="right"
        )
        right_button.callback = self.right_callback
        self.add_item(right_button)
    
    async def left_callback(self, interaction: discord.Interaction):
        if self.current_page == 0:
            self.current_page = self.total_pages - 1
        else:
            self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_current_page_embed(), view=self)
    
    async def right_callback(self, interaction: discord.Interaction):
        if self.current_page == self.total_pages - 1:
            self.current_page = 0
        else:
            self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_current_page_embed(), view=self)

# ================= TRIBUNAL VIEW =================
class TribunalView(discord.ui.View):
    def __init__(self, target, juge, raison, preuve):
        super().__init__(timeout=None)
        self.target = target
        self.juge = juge
        self.raison = raison
        self.preuve = preuve
        self.yes = set()
        self.no = set()
        self.banned = False

    def build_embed(self, banned_by=None):
        desc = f"""Accusé : {self.target.mention}

Juge : {self.juge.mention}

Raison : {self.raison}

Preuves : {self.preuve}

────────────────────────────

✅ oui ({len(self.yes)}/3)
❌ non ({len(self.no)}/3)"""
        
        if banned_by:
            desc += f"\n\n🔨 Juge : {banned_by.mention}"

        embed = discord.Embed(
            title=f"**Jugement de {self.target.display_name}**",
            description=desc,
            color=WHITE
        )
        
        if self.target.avatar:
            embed.set_thumbnail(url=self.target.avatar.url)
        
        return embed

    async def disable_all(self):
        for item in self.children:
            item.disabled = True
        self.banned = True

    @discord.ui.button(label="Oui", style=discord.ButtonStyle.success)
    async def yes_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.banned:
            return await interaction.response.send_message("Ce jugement est déjà terminé.", ephemeral=True)
            
        if interaction.user.id in self.yes or interaction.user.id in self.no:
            return await interaction.response.send_message("Tu as déjà voté !", ephemeral=True)

        allowed_roles = get_allowed_roles(interaction.guild.id, "vote")
        if allowed_roles and not any(r.id in allowed_roles for r in interaction.user.roles):
            return await interaction.response.send_message("Tu n'as pas les permissions requises !", ephemeral=True)

        self.yes.add(interaction.user.id)
        await interaction.response.send_message("Votre vote a bien été enregistré !", ephemeral=True)

        if len(self.yes) >= 3:
            try:
                await self.target.ban(reason="Vote 3/3")
                await self.disable_all()
                await interaction.message.edit(embed=self.build_embed(banned_by=interaction.user), view=self)
            except discord.Forbidden:
                await interaction.followup.send("Je n'ai pas la permission de bannir cet utilisateur.", ephemeral=True)
        else:
            await interaction.message.edit(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Non", style=discord.ButtonStyle.danger)
    async def no_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.banned:
            return await interaction.response.send_message("Ce jugement est déjà terminé.", ephemeral=True)
            
        if interaction.user.id in self.yes or interaction.user.id in self.no:
            return await interaction.response.send_message("Tu as déjà voté !", ephemeral=True)

        allowed_roles = get_allowed_roles(interaction.guild.id, "vote")
        if allowed_roles and not any(r.id in allowed_roles for r in interaction.user.roles):
            return await interaction.response.send_message("Tu n'as pas les permissions requises !", ephemeral=True)

        self.no.add(interaction.user.id)
        await interaction.response.send_message("Votre vote a bien été enregistré !", ephemeral=True)
        await interaction.message.edit(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Bannir", style=discord.ButtonStyle.secondary)
    async def direct_ban(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.banned:
            return await interaction.response.send_message("Ce jugement est déjà terminé.", ephemeral=True)
            
        allowed_roles = get_allowed_roles(interaction.guild.id, "bannissement")
        if allowed_roles and not any(r.id in allowed_roles for r in interaction.user.roles):
            return await interaction.response.send_message("Tu n'as pas les permissions requises !", ephemeral=True)

        try:
            await self.target.ban(reason="Bannissement direct")
            await self.disable_all()
            await interaction.response.edit_message(embed=self.build_embed(banned_by=interaction.user), view=self)
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de bannir cet utilisateur.", ephemeral=True)

# ================= COMMANDE /AUTORISE =================
@bot.tree.command(name="autorise", description="Configurer les rôles autorisés pour une action")
@app_commands.describe(
    role="Le rôle à autoriser",
    action="L'action à autoriser (jugement, vote, bannissement)"
)
@app_commands.choices(action=[
    app_commands.Choice(name="Jugement", value="jugement"),
    app_commands.Choice(name="Vote", value="vote"),
    app_commands.Choice(name="Bannissement", value="bannissement")
])
async def autorise(interaction: discord.Interaction, role: discord.Role, action: str):
    if interaction.user.id != ADMIN_USER_ID:
        return await interaction.response.send_message("Tu n'es pas autorisé à utiliser cette commande.", ephemeral=True)
    
    if is_role_allowed(interaction.guild.id, role.id, action):
        remove_allowed_role(interaction.guild.id, role.id, action)
        await interaction.response.send_message(f"{role.mention} n'est plus autorisé à **{action}**.", ephemeral=True)
    else:
        add_allowed_role(interaction.guild.id, role.id, action)
        await interaction.response.send_message(f"{role.mention} est maintenant autorisé à **{action}**.", ephemeral=True)

# ================= COMMANDE /CONFIG =================
@bot.tree.command(name="config", description="Configurer les salons et mentions du bot")
@app_commands.describe(
    salon_jugement="Le salon où les jugements seront envoyés",
    mention="Le rôle à mentionner lors d'un jugement",
    salon_logs="Le salon pour les logs"
)
async def config(
    interaction: discord.Interaction, 
    salon_jugement: Optional[discord.TextChannel] = None,
    mention: Optional[discord.Role] = None,
    salon_logs: Optional[discord.TextChannel] = None
):
    if interaction.user.id != ADMIN_USER_ID:
        return await interaction.response.send_message("Tu n'es pas autorisé à utiliser cette commande.", ephemeral=True)
    
    set_guild_config(
        interaction.guild.id,
        salon_jugement.id if salon_jugement else None,
        mention.id if mention else None,
        salon_logs.id if salon_logs else None
    )
    
    embed = discord.Embed(
        title="**Configuration mise à jour**",
        color=WHITE
    )
    
    config = get_guild_config(interaction.guild.id)
    
    if config:
        jugement_channel = interaction.guild.get_channel(config[0]) if config[0] else None
        mention_role = interaction.guild.get_role(config[1]) if config[1] else None
        logs_channel = interaction.guild.get_channel(config[2]) if config[2] else None
        
        embed.add_field(
            name="Salon des jugements",
            value=jugement_channel.mention if jugement_channel else "Non configuré",
            inline=False
        )
        embed.add_field(
            name="Rôle à mentionner",
            value=mention_role.mention if mention_role else "Non configuré",
            inline=False
        )
        embed.add_field(
            name="Salon des logs",
            value=logs_channel.mention if logs_channel else "Non configuré",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= COMMANDE /SAVEDB =================
@bot.tree.command(name="savedb", description="Sauvegarder toute la base de données et l'envoyer en fichier")
async def savedb(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_USER_ID:
        return await interaction.response.send_message("Tu n'es pas autorisé à utiliser cette commande.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        with open(DB_PATH, 'rb') as f:
            db_file = io.BytesIO(f.read())
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_data_{timestamp}.db"
        
        await interaction.followup.send(
            content="Sauvegarde de la base de données effectuée :",
            file=discord.File(db_file, filename),
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"Erreur lors de la sauvegarde : {str(e)}",
            ephemeral=True
        )

# ================= COMMANDE /SETDB =================
@bot.tree.command(name="setdb", description="Restaurer une configuration depuis un fichier de sauvegarde")
@app_commands.describe(
    fichier="Le fichier de sauvegarde .db à restaurer"
)
async def setdb(interaction: discord.Interaction, fichier: discord.Attachment):
    if interaction.user.id != ADMIN_USER_ID:
        return await interaction.response.send_message("Tu n'es pas autorisé à utiliser cette commande.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        if not fichier.filename.endswith('.db'):
            await interaction.followup.send(
                "Le fichier doit être une base de données SQLite (.db)",
                ephemeral=True
            )
            return
        
        file_content = await fichier.read()
        reset_database_from_file(file_content)
        
        await interaction.followup.send(
            "Configuration restaurée avec succès !",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"Erreur lors de la restauration : {str(e)}",
            ephemeral=True
        )

# ================= COMMANDE /JUGER =================
@bot.tree.command(name="juger", description="Juger un utilisateur")
@app_commands.describe(
    user="L'utilisateur à juger",
    raison="La raison du jugement",
    preuve="Lien vers une image ou vidéo (preuve)"
)
async def juger(interaction: discord.Interaction, user: discord.Member, raison: str, preuve: str):
    
    allowed_roles = get_allowed_roles(interaction.guild.id, "jugement")
    if allowed_roles:
        if not any(r.id in allowed_roles for r in interaction.user.roles):
            return await interaction.response.send_message(
                "Tu n'as pas les permissions requises pour lancer un jugement !",
                ephemeral=True
            )
    elif not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message(
            "Tu n'as pas la permission de bannir des membres !",
            ephemeral=True
        )

    if is_protected(interaction.guild.id, user.id):
        return await interaction.response.send_message(
            f"{user.mention} est déjà protégé contre les jugements",
            ephemeral=True
        )

    if user == interaction.guild.owner:
        return await interaction.response.send_message(
            "Impossible de juger le propriétaire du serveur",
            ephemeral=True
        )

    if interaction.user.top_role <= user.top_role:
        return await interaction.response.send_message(
            f"Tu ne peux pas lancer un jugement pour {user.mention} car il est égal ou supérieur à toi",
            ephemeral=True
        )

    if user.top_role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            "Je ne peux pas bannir cet utilisateur car son rôle est supérieur au mien",
            ephemeral=True
        )

    view = TribunalView(user, interaction.user, raison, preuve)
    embed = view.build_embed()
    
    config = get_guild_config(interaction.guild.id)
    mention_role = interaction.guild.get_role(config[1]) if config and config[1] else None
    
    content = mention_role.mention if mention_role else None
    
    if config and config[0]:
        channel = interaction.guild.get_channel(config[0])
        if channel:
            await channel.send(content=content, embed=embed, view=view)
            await interaction.response.send_message(f"Jugement envoyé dans {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message(content=content, embed=embed, view=view)
    else:
        await interaction.response.send_message(content=content, embed=embed, view=view)

# ================= COMMANDES DE PROTECTION =================
@bot.tree.command(name="protect", description="Protéger un utilisateur contre les jugements")
async def protect(interaction: discord.Interaction, user: discord.Member):
    if interaction.user.id != ADMIN_USER_ID:
        return await interaction.response.send_message("Tu n'es pas autorisé à utiliser cette commande.", ephemeral=True)
    
    if is_protected(interaction.guild.id, user.id):
        return await interaction.response.send_message(f"{user.mention} est déjà protégé contre les jugements", ephemeral=True)
    
    add_protected(interaction.guild.id, user.id, interaction.user.id)
    await interaction.response.send_message(f"{user.mention} **est maintenant protégé** des jugements", ephemeral=True)

@bot.tree.command(name="unprotect", description="Retirer la protection d'un utilisateur")
async def unprotect(interaction: discord.Interaction, user: discord.Member):
    if interaction.user.id != ADMIN_USER_ID:
        return await interaction.response.send_message("Tu n'es pas autorisé à utiliser cette commande.", ephemeral=True)
    
    if not is_protected(interaction.guild.id, user.id):
        return await interaction.response.send_message(f"{user.mention} n'était pas protégé", ephemeral=True)
    
    rem_protected(interaction.guild.id, user.id)
    await interaction.response.send_message(f"{user.mention} **n'est plus protégé** des jugements", ephemeral=True)

@bot.tree.command(name="protected", description="Lister tous les utilisateurs protégés")
async def protected(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_USER_ID:
        return await interaction.response.send_message("Tu n'es pas autorisé à utiliser cette commande.", ephemeral=True)
    
    protected_list = get_protected(interaction.guild.id)
    
    if not protected_list:
        return await interaction.response.send_message("Aucun utilisateur protégé.", ephemeral=True)
    
    user_mentions = []
    protector_mentions = []
    
    for user_id, protected_by in protected_list:
        user = interaction.guild.get_member(user_id)
        protector = interaction.guild.get_member(protected_by)
        user_mentions.append(user.mention if user else f"Utilisateur inconnu ({user_id})")
        protector_mentions.append(protector.mention if protector else f"ID: {protected_by}")
    
    view = ProtectedPaginationView(interaction.guild, protected_list, user_mentions, protector_mentions)
    embed = view.get_current_page_embed()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ================= COMMANDES D'INFORMATION =================
@bot.tree.command(name="help", description="Afficher les informations sur les permissions")
async def help_command(interaction: discord.Interaction):
    guild = interaction.guild
    
    jugement_role_ids = get_allowed_roles(guild.id, "jugement")
    jugement_roles = []
    
    if jugement_role_ids:
        jugement_roles = [guild.get_role(rid).mention for rid in jugement_role_ids if guild.get_role(rid)]
    else:
        for role in guild.roles:
            if role.permissions.ban_members:
                jugement_roles.append(role.mention)
    
    vote_role_ids = get_allowed_roles(guild.id, "vote")
    vote_roles = [guild.get_role(rid).mention for rid in vote_role_ids if guild.get_role(rid)]
    
    ban_role_ids = get_allowed_roles(guild.id, "bannissement")
    ban_roles = [guild.get_role(rid).mention for rid in ban_role_ids if guild.get_role(rid)]
    
    embed = discord.Embed(
        title="**Informations sur les permissions**",
        color=WHITE
    )
    
    embed.add_field(
        name="`Autorisation de lancer un jugement` :",
        value=", ".join(jugement_roles) if jugement_roles else "Aucun rôle configuré (nécessite permission BAN_MEMBERS)",
        inline=False
    )
    
    embed.add_field(
        name="`Autorisation de voter pour un jugement` :",
        value=", ".join(vote_roles) if vote_roles else "Aucun rôle configuré",
        inline=False
    )
    
    embed.add_field(
        name="`Autorisation de bannir directement` :",
        value=", ".join(ban_roles) if ban_roles else "Aucun rôle configuré",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.tree.command(name="info", description="Afficher la configuration du bot")
async def info_command(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_USER_ID:
        return await interaction.response.send_message("Tu n'es pas autorisé à utiliser cette commande.", ephemeral=True)
    
    embed = discord.Embed(
        title="**Configuration**",
        color=WHITE
    )
    
    config = get_guild_config(interaction.guild.id)
    
    if config:
        jugement_channel = interaction.guild.get_channel(config[0]) if config[0] else None
        mention_role = interaction.guild.get_role(config[1]) if config[1] else None
        logs_channel = interaction.guild.get_channel(config[2]) if config[2] else None
        
        embed.add_field(
            name="Salon des jugements",
            value=jugement_channel.mention if jugement_channel else "Non configuré",
            inline=False
        )
        embed.add_field(
            name="Rôle à mentionner",
            value=mention_role.mention if mention_role else "Non configuré",
            inline=False
        )
        embed.add_field(
            name="Salon des logs",
            value=logs_channel.mention if logs_channel else "Non configuré",
            inline=False
        )
    else:
        embed.add_field(
            name="Configuration",
            value="Aucune configuration spécifique",
            inline=False
        )
    
    jugement_roles = get_allowed_roles(interaction.guild.id, "jugement")
    vote_roles = get_allowed_roles(interaction.guild.id, "vote")
    ban_roles = get_allowed_roles(interaction.guild.id, "bannissement")
    
    embed.add_field(
        name="Rôles autorisés (jugement)",
        value=", ".join([interaction.guild.get_role(rid).mention for rid in jugement_roles if interaction.guild.get_role(rid)]) or "Aucun",
        inline=False
    )
    
    embed.add_field(
        name="Rôles autorisés (vote)",
        value=", ".join([interaction.guild.get_role(rid).mention for rid in vote_roles if interaction.guild.get_role(rid)]) or "Aucun",
        inline=False
    )
    
    embed.add_field(
        name="Rôles autorisés (bannissement)",
        value=", ".join([interaction.guild.get_role(rid).mention for rid in ban_roles if interaction.guild.get_role(rid)]) or "Aucun",
        inline=False
    )
    
    protected_count = len(get_protected(interaction.guild.id))
    embed.add_field(
        name="Utilisateurs protégés",
        value=f"{protected_count} utilisateur(s)",
        inline=False
    )
    
    embed.set_footer(text=f"Admin ID: {ADMIN_USER_ID}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= START =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot prêt - Connecté en tant que {bot.user}")
    print(f"Serveurs connectés : {len(bot.guilds)}")
    print(f"Commandes synchronisées : {len(bot.tree.get_commands())}")

if __name__ == "__main__":
    if TOKEN:
        print("Démarrage du bot Discord...")
        bot.run(TOKEN)
    else:
        print("Erreur: DISCORD_TOKEN non défini")