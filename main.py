import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import sqlite3
from datetime import datetime
from typing import Optional
import signal

# ========== HEALTH CHECK SERVER AMÉLIORÉ ==========
class HealthHandler(BaseHTTPRequestHandler):
    """Handler pour les health checks HTTP"""
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write('🤖 Bot Discord Tribunal en ligne!'.encode('utf-8'))
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "discord-bot"}')
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot Discord Tribunal')
    
    def log_message(self, format, *args):
        pass

def start_health_server():
    try:
        port = int(os.environ.get('PORT', 10000))
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        print(f"✅ Serveur health check démarré sur le port {port}")
        print(f"✅ URL: http://0.0.0.0:{port}/")
        sys.stdout.flush()
        
        def shutdown(signum, frame):
            print("🔴 Arrêt du serveur health check...")
            server.shutdown()
        
        signal.signal(signal.SIGTERM, shutdown)
        server.serve_forever()
    except Exception as e:
        print(f"❌ Erreur serveur health check: {e}")
        sys.stdout.flush()

print("🚀 Démarrage du health check...")
health_thread = threading.Thread(target=start_health_server, daemon=True)
health_thread.start()
time.sleep(2)
print("✅ Health check prêt")
# ========== FIN HEALTH CHECK ==========

# ========== IMPORTS DISCORD ==========
import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ ERREUR: DISCORD_TOKEN non défini!")
    print("Configure la variable d'environnement DISCORD_TOKEN sur Render")
    print("⚠️ Le bot Discord ne démarrera pas, mais le health check est actif")

# ========== ADMIN ID ==========
ADMIN_USER_ID = 1399234120214909010  # ← REMPLACE PAR TON ID DISCORD

print("🔧 Initialisation du bot Discord...")

# ---------- DATABASE FUNCTIONS ----------
def init_db():
    db = sqlite3.connect("data.db", check_same_thread=False)
    cursor = db.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guild_roles (
            guild_id INTEGER,
            role_id INTEGER,
            role_type TEXT CHECK(role_type IN ('vote', 'ban', 'jugement')),
            PRIMARY KEY (guild_id, role_id, role_type)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY,
            ban_channel_id INTEGER,
            log_channel_id INTEGER,
            mention_role_id INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS protected_users (
            guild_id INTEGER,
            user_id INTEGER,
            protected_by INTEGER,
            protected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason TEXT DEFAULT '',
            PRIMARY KEY (guild_id, user_id)
        )
    """)

    db.commit()
    return db, cursor

db, cursor = init_db()
print("✅ Base de données initialisée")

def get_roles(guild_id: int, role_type: str):
    try:
        cursor.execute(
            "SELECT role_id FROM guild_roles WHERE guild_id = ? AND role_type = ?",
            (guild_id, role_type)
        )
        return [r[0] for r in cursor.fetchall()]
    except Exception as e:
        print(f"Erreur get_roles: {e}")
        return []

def has_permission(member: discord.Member, role_type: str) -> bool:
    if member.guild_permissions.administrator:
        return True
    allowed_roles = get_roles(member.guild.id, role_type)
    return any(role.id in allowed_roles for role in member.roles)

def can_start_judgment(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    if has_permission(member, "jugement"):
        return True
    if has_permission(member, "ban"):
        return True
    return False

def is_user_protected(guild_id: int, user_id: int) -> bool:
    try:
        cursor.execute(
            "SELECT 1 FROM protected_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        return cursor.fetchone() is not None
    except Exception as e:
        print(f"Erreur is_user_protected: {e}")
        return False

def add_protected_user(guild_id: int, user_id: int, protected_by: int, reason: str = ""):
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO protected_users (guild_id, user_id, protected_by, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, protected_by, reason)
        )
        db.commit()
        return True
    except Exception as e:
        print(f"Erreur add_protected_user: {e}")
        return False

def remove_protected_user(guild_id: int, user_id: int):
    try:
        cursor.execute(
            "DELETE FROM protected_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        db.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"Erreur remove_protected_user: {e}")
        return False

def get_protected_users(guild_id: int):
    try:
        cursor.execute(
            "SELECT user_id, protected_by, reason, protected_at FROM protected_users WHERE guild_id = ?",
            (guild_id,)
        )
        return cursor.fetchall()
    except Exception as e:
        print(f"Erreur get_protected_users: {e}")
        return []

def get_config(guild_id: int) -> dict:
    try:
        cursor.execute(
            "SELECT ban_channel_id, log_channel_id, mention_role_id FROM config WHERE guild_id = ?",
            (guild_id,)
        )
        result = cursor.fetchone()

        if result:
            return {
                "ban_channel_id": result[0],
                "log_channel_id": result[1],
                "mention_role_id": result[2]
            }
    except Exception as e:
        print(f"Erreur get_config: {e}")

    return {
        "ban_channel_id": None,
        "log_channel_id": None,
        "mention_role_id": None
    }

def set_config(guild_id: int, **kwargs):
    try:
        current = get_config(guild_id)
        updates = {}
        for key in ['ban_channel_id', 'log_channel_id', 'mention_role_id']:
            updates[key] = kwargs.get(key, current.get(key))

        cursor.execute("""
            INSERT OR REPLACE INTO config 
            (guild_id, ban_channel_id, log_channel_id, mention_role_id) 
            VALUES (?, ?, ?, ?)
        """, (guild_id, updates['ban_channel_id'], 
              updates['log_channel_id'], updates['mention_role_id']))

        db.commit()
        return True
    except Exception as e:
        print(f"Erreur set_config: {e}")
        return False

# ---------- BOT SETUP ----------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=">", intents=intents)

# ---------- TRIBUNAL VIEW ----------
class TribunalView(discord.ui.View):
    def __init__(self, target: discord.Member, original_embed: discord.Embed, 
                 proof_url: str = None, moderator: discord.Member = None):
        super().__init__(timeout=None)
        self.target = target
        self.votes_yes = set()
        self.votes_no = set()
        self.original_embed = original_embed
        self.proof_url = proof_url
        self.moderator = moderator
        self.has_concluded = False

    async def update_embed(self, message):
        mentions_oui = " ".join([f"<@{user_id}>" for user_id in self.votes_yes]) if self.votes_yes else "Aucun"
        mentions_non = " ".join([f"<@{user_id}>" for user_id in self.votes_no]) if self.votes_no else "Aucun"

        embed = discord.Embed(
            title=self.original_embed.title,
            color=self.original_embed.color,
            timestamp=self.original_embed.timestamp
        )

        embed.set_thumbnail(url=self.original_embed.thumbnail.url)

        for field in self.original_embed.fields:
            if field.name not in ["Pour :", "Contre :", "⚖️ État du jugement"]:
                embed.add_field(name=field.name, value=field.value, inline=field.inline)

        embed.add_field(
            name="⚖️ État du jugement",
            value=f"✅ **OUI** ({len(self.votes_yes)}/3)\n{mentions_oui if mentions_oui != 'Aucun' else 'Aucun vote'}\n\n❌ **NON** ({len(self.votes_no)}/3)\n{mentions_non if mentions_non != 'Aucun' else 'Aucun vote'}",
            inline=False
        )

        await message.edit(embed=embed)

    async def send_log(self, verdict: str, accepted: bool, moderator: discord.Member = None):
        config = get_config(self.target.guild.id)
        log_channel_id = config.get("log_channel_id")

        if log_channel_id:
            channel = self.target.guild.get_channel(log_channel_id)
            if channel:
                if accepted:
                    embed = discord.Embed(
                        title="",
                        description=f"Le jugement de {self.target.mention} a été accepté",
                        color=discord.Color.green(),
                        timestamp=datetime.now()
                    )
                else:
                    embed = discord.Embed(
                        title="",
                        description=f"Le jugement de {self.target.mention} a été refusé",
                        color=discord.Color.red(),
                        timestamp=datetime.now()
                    )

                embed.add_field(name="Modérateur", value=moderator.mention if moderator else "Inconnu", inline=False)
                embed.add_field(name="Votes pour", value=str(len(self.votes_yes)), inline=True)
                embed.add_field(name="Votes contre", value=str(len(self.votes_no)), inline=True)
                embed.add_field(name="Verdict", value=verdict, inline=False)

                await channel.send(embed=embed)

    async def check_verdict(self, interaction: discord.Interaction):
        if len(self.votes_yes) >= 3:
            try:
                await self.target.ban(reason="Vote du tribunal (3 oui)")
                embed = discord.Embed(
                    title="🔨 VERDICT : BANNISSEMENT APPLIQUÉ",
                    description=f"{self.target.mention} a été banni suite au vote du tribunal.",
                    color=discord.Color.red()
                )
                await interaction.message.edit(embed=embed, view=None)
                self.has_concluded = True
                await self.send_log("Bannissement appliqué (3 votes pour)", True, self.moderator)
            except discord.Forbidden:
                embed = discord.Embed(
                    title="❌ ERREUR : Permission manquante",
                    description="Je n'ai pas la permission de bannir cet utilisateur.",
                    color=discord.Color.orange()
                )
                await interaction.message.edit(embed=embed, view=None)
                self.has_concluded = True
        elif len(self.votes_no) >= 3:
            embed = discord.Embed(
                title="❌ VERDICT : JUGEMENT ANNULÉ",
                description="Le vote a abouti à un non-bannissement.",
                color=discord.Color.green()
            )
            await interaction.message.edit(embed=embed, view=None)
            self.has_concluded = True
            await self.send_log("Jugement annulé (3 votes contre)", False, self.moderator)
        else:
            await self.update_embed(interaction.message)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.has_concluded:
            await interaction.response.send_message(
                "❌ Ce jugement est déjà terminé.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Oui", emoji="✅", style=discord.ButtonStyle.success)
    async def oui(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user, "vote"):
            return await interaction.response.send_message("Tu n'es pas autorisé à voter.", ephemeral=True)

        if interaction.user.id in self.votes_yes | self.votes_no:
            return await interaction.response.send_message("Tu as déjà voté.", ephemeral=True)

        self.votes_yes.add(interaction.user.id)

        await interaction.response.send_message("✅ Vote **OUI** enregistré!", ephemeral=True)
        await self.check_verdict(interaction)

    @discord.ui.button(label="Non", emoji="❌", style=discord.ButtonStyle.danger)
    async def non(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user, "vote"):
            return await interaction.response.send_message("Tu n'es pas autorisé à voter.", ephemeral=True)

        if interaction.user.id in self.votes_yes | self.votes_no:
            return await interaction.response.send_message("Tu as déjà voté.", ephemeral=True)

        self.votes_no.add(interaction.user.id)

        await interaction.response.send_message("❌ Vote **NON** enregistré!", ephemeral=True)
        await self.check_verdict(interaction)

    @discord.ui.button(label="Bannir", emoji="👨‍⚖️", style=discord.ButtonStyle.secondary)
    async def bannir(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user, "ban"):
            return await interaction.response.send_message(
                "Tu n'as pas les permissions nécessaires pour appuyer sur ce bouton",
                ephemeral=True
            )

        try:
            await self.target.ban(reason="Bannissement direct (juge)")
            embed = discord.Embed(
                title="🔨 BANNISSEMENT DIRECT EXÉCUTÉ",
                description=f"{self.target.mention} a été banni par {interaction.user.mention}.",
                color=discord.Color.red()
            )
            await interaction.message.edit(embed=embed, view=None)
            self.has_concluded = True

            config = get_config(self.target.guild.id)
            log_channel_id = config.get("log_channel_id")
            if log_channel_id:
                channel = self.target.guild.get_channel(log_channel_id)
                if channel:
                    embed_log = discord.Embed(
                        title="",
                        description=f"Le jugement de {self.target.mention} a été accepté",
                        color=discord.Color.green(),
                        timestamp=datetime.now()
                    )
                    embed_log.add_field(name="Modérateur", value=interaction.user.mention, inline=False)
                    embed_log.add_field(name="Type", value="Bannissement direct", inline=False)
                    embed_log.add_field(name="Raison", value="Bannissement par un juge", inline=False)
                    await channel.send(embed=embed_log)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Je n'ai pas la permission de bannir cet utilisateur.",
                ephemeral=True
            )

# ---------- BOT EVENTS ----------
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ Connecté en tant que : {bot.user}")
        print(f"✅ {len(synced)} commande(s) slash synchronisée(s)")
        print(f"✅ Serveurs: {len(bot.guilds)}")
        print(f"✅ Health check actif sur le port {os.environ.get('PORT', 10000)}")
        print("🚀 Bot prêt à fonctionner!")
        
        port = os.environ.get('PORT', 10000)
        print(f"🌐 Health check URL: https://tribunal-095-akusa.onrender.com/")
    except Exception as e:
        print(f"❌ Erreur de synchronisation: {e}")

# ---------- SLASH COMMANDS ----------
@bot.tree.command(name="config", description="Configurer le bot (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    salon_jugement="Salon où envoyer les jugements",
    salon_logs="Salon où envoyer les logs",
    role_mentionner="Rôle à mentionner à chaque jugement"
)
async def config(interaction: discord.Interaction, 
                salon_jugement: Optional[discord.TextChannel] = None, 
                salon_logs: Optional[discord.TextChannel] = None,
                role_mentionner: Optional[discord.Role] = None):

    try:
        if salon_jugement is None and salon_logs is None and role_mentionner is None:
            cursor.execute("DELETE FROM config WHERE guild_id = ?", (interaction.guild_id,))
            db.commit()
            await interaction.response.send_message("✅ Configuration réinitialisée.", ephemeral=True)
            return

        set_config(interaction.guild_id, 
                   ban_channel_id=salon_jugement.id if salon_jugement else None,
                   log_channel_id=salon_logs.id if salon_logs else None,
                   mention_role_id=role_mentionner.id if role_mentionner else None)

        embed = discord.Embed(
            title="⚙️ Configuration mise à jour",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        config_info = get_config(interaction.guild_id)

        if salon_jugement:
            embed.add_field(name="📁 Salon de jugement", value=salon_jugement.mention, inline=False)
        elif config_info.get("ban_channel_id"):
            channel = interaction.guild.get_channel(config_info["ban_channel_id"])
            if channel:
                embed.add_field(name="📁 Salon de jugement", value=f"{channel.mention} (inchangé)", inline=False)

        if salon_logs:
            embed.add_field(name="📋 Salon des logs", value=salon_logs.mention, inline=False)
        elif config_info.get("log_channel_id"):
            channel = interaction.guild.get_channel(config_info["log_channel_id"])
            if channel:
                embed.add_field(name="📋 Salon des logs", value=f"{channel.mention} (inchangé)", inline=False)

        if role_mentionner:
            embed.add_field(name="👥 Rôle à mentionner", value=role_mentionner.mention, inline=False)
        elif config_info.get("mention_role_id"):
            role = interaction.guild.get_role(config_info["mention_role_id"])
            if role:
                embed.add_field(name="👥 Rôle à mentionner", value=f"{role.mention} (inchangé)", inline=False)

        embed.set_footer(text=f"Configuré par {interaction.user}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    except Exception as e:
        print(f"Erreur dans /config: {e}")
        await interaction.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="ban", description="Lancer un jugement de bannissement")
@app_commands.describe(
    user="Utilisateur à juger",
    raison="Raison du bannissement",
    preuve="Image ou vidéo comme preuve"
)
async def ban(interaction: discord.Interaction, user: discord.Member, raison: str, preuve: discord.Attachment):
    try:
        if is_user_protected(interaction.guild_id, user.id):
            return await interaction.response.send_message(
                "❌ Vous ne pouvez pas lancer un jugement pour un membre protégé.",
                ephemeral=True
            )

        if not can_start_judgment(interaction.user):
            return await interaction.response.send_message(
                "❌ Tu n'as pas la permission d'utiliser cette commande.", 
                ephemeral=True
            )

        valid_content_types = [
            'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
            'video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/x-ms-wmv',
            'video/webm'
        ]

        if preuve.content_type not in valid_content_types:
            return await interaction.response.send_message(
                f"❌ Le fichier doit être une image ou une vidéo! Type reçu: {preuve.content_type}", 
                ephemeral=True
            )

        embed = discord.Embed(
            title=f"⚖️ Jugement de {user}",
            color=discord.Color.dark_red(),
            timestamp=datetime.now()
        )

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="👮 Modérateur", value=interaction.user.mention, inline=False)
        embed.add_field(name="🦹 Accusé", value=user.mention, inline=False)
        embed.add_field(name="📋 Raison", value=raison, inline=False)
        embed.add_field(name="📁 Preuve", value=f"[Cliquez ici pour voir la preuve]({preuve.url})", inline=False)
        embed.add_field(name="⚖️ État du jugement", 
                       value=f"✅ **OUI** (0/3)\nAucun vote\n\n❌ **NON** (0/3)\nAucun vote", 
                       inline=False)
        embed.set_footer(text="Tribunal du serveur • Utilisez les boutons pour voter")

        config_info = get_config(interaction.guild_id)
        ban_channel_id = config_info.get("ban_channel_id")

        mention_text = ""
        mention_role_id = config_info.get("mention_role_id")
        if mention_role_id:
            role = interaction.guild.get_role(mention_role_id)
            if role:
                mention_text = role.mention

        if ban_channel_id:
            channel = interaction.guild.get_channel(ban_channel_id)
            if channel:
                salon_nom = channel.mention
            else:
                salon_nom = "le salon courant"
                await interaction.followup.send(
                    "⚠️ Le salon configuré n'existe plus. Le jugement a été envoyé ici.", 
                    ephemeral=True
                )
        else:
            salon_nom = "le salon courant"

        await interaction.response.send_message(f"**Jugement** lancé dans {salon_nom}.", ephemeral=True)

        view = TribunalView(user, embed, preuve.url, interaction.user)

        if ban_channel_id and (channel := interaction.guild.get_channel(ban_channel_id)):
            message = await channel.send(content=mention_text, embed=embed, view=view)
        else:
            message = await interaction.channel.send(content=mention_text, embed=embed, view=view)

    except Exception as e:
        print(f"Erreur dans /ban: {e}")
        await interaction.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="baninfo", description="Voir les informations d'un bannissement")
@app_commands.describe(user="Utilisateur banni")
async def baninfo(interaction: discord.Interaction, user: discord.User):
    try:
        embed = discord.Embed(
            title=f"Bannissement de ({user.name})",
            color=discord.Color.dark_red(),
            timestamp=datetime.now()
        )

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Banni par :", value="Information non disponible", inline=False)
        embed.add_field(name="Raison :", value="Information non disponible", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Erreur dans /baninfo: {e}")
        await interaction.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="autorise", description="Ajouter ou retirer l'autorisation d'un rôle (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    role="Rôle à autoriser/désautoriser", 
    type="Type de permission"
)
@app_commands.choices(type=[
    app_commands.Choice(name="vote", value="vote"),
    app_commands.Choice(name="ban", value="ban"),
    app_commands.Choice(name="jugement", value="jugement")
])
async def autorise(interaction: discord.Interaction, role: discord.Role, type: app_commands.Choice[str]):
    try:
        cursor.execute(
            "SELECT 1 FROM guild_roles WHERE guild_id = ? AND role_id = ? AND role_type = ?",
            (interaction.guild_id, role.id, type.value)
        )

        already_authorized = cursor.fetchone() is not None

        if already_authorized:
            cursor.execute(
                "DELETE FROM guild_roles WHERE guild_id = ? AND role_id = ? AND role_type = ?",
                (interaction.guild_id, role.id, type.value)
            )
            action = "désautorisé"
            color = discord.Color.orange()
        else:
            cursor.execute(
                "INSERT INTO guild_roles (guild_id, role_id, role_type) VALUES (?, ?, ?)",
                (interaction.guild_id, role.id, type.value)
            )
            action = "autorisé"
            color = discord.Color.green()

        db.commit()

        embed = discord.Embed(
            title="⚙️ Autorisation modifiée",
            description=f"{role.mention} a été **{action}** pour **{type.value}**.",
            color=color,
            timestamp=datetime.now()
        )

        current_roles = get_roles(interaction.guild_id, type.value)
        if current_roles:
            roles_mentions = " ".join([f"<@&{role_id}>" for role_id in current_roles])
            embed.add_field(
                name=f"Rôles actuellement autorisés ({type.value})",
                value=roles_mentions,
                inline=False
            )

        embed.set_footer(text=f"Action par {interaction.user}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    except Exception as e:
        print(f"Erreur dans /autorise: {e}")
        await interaction.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="protect", description="Protéger un utilisateur des jugements (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    user="Utilisateur à protéger",
    raison="Raison de la protection (optionnel)"
)
async def protect(interaction: discord.Interaction, user: discord.Member, raison: Optional[str] = ""):
    try:
        if is_user_protected(interaction.guild_id, user.id):
            return await interaction.response.send_message(
                f"❌ {user.mention} est déjà protégé.", 
                ephemeral=True
            )

        if add_protected_user(interaction.guild_id, user.id, interaction.user.id, raison):
            embed = discord.Embed(
                title="🛡️ Utilisateur protégé",
                description=f"{user.mention} est maintenant protégé des jugements.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )

            if raison:
                embed.add_field(name="Raison", value=raison, inline=False)

            embed.add_field(name="Protégé par", value=interaction.user.mention, inline=False)
            embed.set_footer(text=f"ID: {user.id}")

            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Erreur lors de l'ajout de la protection.", 
                ephemeral=True
            )

    except Exception as e:
        print(f"Erreur dans /protect: {e}")
        await interaction.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="unprotect", description="Retirer la protection d'un utilisateur (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    user="Utilisateur à déprotéger"
)
async def unprotect(interaction: discord.Interaction, user: discord.Member):
    try:
        if not is_user_protected(interaction.guild_id, user.id):
            return await interaction.response.send_message(
                f"❌ {user.mention} n'est pas protégé.", 
                ephemeral=True
            )

        if remove_protected_user(interaction.guild_id, user.id):
            embed = discord.Embed(
                title="🛡️ Protection retirée",
                description=f"{user.mention} n'est plus protégé des jugements.",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )

            embed.add_field(name="Retiré par", value=interaction.user.mention, inline=False)
            embed.set_footer(text=f"ID: {user.id}")

            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Erreur lors du retrait de la protection.", 
                ephemeral=True
            )

    except Exception as e:
        print(f"Erreur dans /unprotect: {e}")
        await interaction.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="protected", description="Voir la liste des utilisateurs protégés")
async def protected(interaction: discord.Interaction):
    try:
        protected_users = get_protected_users(interaction.guild_id)

        if not protected_users:
            return await interaction.response.send_message(
                "Aucun utilisateur n'est actuellement protégé.", 
                ephemeral=True
            )

        embed = discord.Embed(
            title="🛡️ Utilisateurs protégés",
            description=f"{len(protected_users)} utilisateur(s) protégé(s)",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        for user_id, protected_by, reason, protected_at in protected_users[:10]:
            user = interaction.guild.get_member(user_id)
            protector = interaction.guild.get_member(protected_by)

            user_display = user.mention if user else f"`{user_id}` (non présent)"
            protector_display = protector.mention if protector else f"`{protected_by}`"
            reason_display = reason if reason else "Aucune raison fournie"

            embed.add_field(
                name=user_display,
                value=f"**Protégé par:** {protector_display}\n**Raison:** {reason_display}\n**Depuis:** <t:{int(datetime.fromisoformat(protected_at).timestamp())}:R>",
                inline=False
            )

        if len(protected_users) > 10:
            embed.set_footer(text=f"Et {len(protected_users) - 10} autre(s) utilisateur(s)")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    except Exception as e:
        print(f"Erreur dans /protected: {e}")
        await interaction.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="info", description="Voir la configuration actuelle")
async def info(interaction: discord.Interaction):
    try:
        embed = discord.Embed(
            title="⚙️ Configuration du bot",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        vote_roles = get_roles(interaction.guild_id, "vote")
        ban_roles = get_roles(interaction.guild_id, "ban")
        jugement_roles = get_roles(interaction.guild_id, "jugement")
        config_info = get_config(interaction.guild_id)
        protected_count = len(get_protected_users(interaction.guild_id))

        vote_roles_mentions = " ".join([f"<@&{role_id}>" for role_id in vote_roles]) if vote_roles else "Aucun"
        ban_roles_mentions = " ".join([f"<@&{role_id}>" for role_id in ban_roles]) if ban_roles else "Aucun"
        jugement_roles_mentions = " ".join([f"<@&{role_id}>" for role_id in jugement_roles]) if jugement_roles else "Aucun"

        ban_channel_info = "Salon courant"
        if config_info.get("ban_channel_id"):
            channel = interaction.guild.get_channel(config_info["ban_channel_id"])
            ban_channel_info = channel.mention if channel else "❌ Salon introuvable"

        log_channel_info = "Non configuré"
        if config_info.get("log_channel_id"):
            channel = interaction.guild.get_channel(config_info["log_channel_id"])
            log_channel_info = channel.mention if channel else "❌ Salon introuvable"

        mention_role_info = "Non configuré"
        if config_info.get("mention_role_id"):
            role = interaction.guild.get_role(config_info["mention_role_id"])
            mention_role_info = role.mention if role else "❌ Rôle introuvable"

        embed.add_field(name="👥 Rôles pouvant voter", value=vote_roles_mentions, inline=False)
        embed.add_field(name="⚖️ Rôles pouvant bannir", value=ban_roles_mentions, inline=False)
        embed.add_field(name="🎯 Rôles pouvant lancer un jugement", value=jugement_roles_mentions, inline=False)
        embed.add_field(name="📁 Salon de jugement", value=ban_channel_info, inline=False)
        embed.add_field(name="📋 Salon des logs", value=log_channel_info, inline=False)
        embed.add_field(name="👥 Rôle à mentionner", value=mention_role_info, inline=False)
        embed.add_field(name="🛡️ Utilisateurs protégés", value=f"{protected_count} utilisateur(s)", inline=False)

        embed.add_field(name="📜 Commandes disponibles", value="""
`/ban` - Lancer un jugement
`/baninfo` - Voir infos bannissement
`/autorise` - Autoriser/désautoriser un rôle (admin)
`/config` - Configurer les salons (admin)
`/protect` - Protéger un utilisateur (admin)
`/unprotect` - Retirer la protection (admin)
`/protected` - Voir les protégés
`/info` - Voir cette configuration
""", inline=False)

        embed.set_footer(text=f"Demandé par {interaction.user}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    except Exception as e:
        print(f"Erreur dans /info: {e}")
        await interaction.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

# ---------- PREFIX COMMANDS ----------
@bot.command(name=">savedb")
@commands.check(lambda ctx: ctx.author.id == ADMIN_USER_ID)
async def savedb(ctx):
    """Sauvegarde la base de données et l'envoie en DM"""
    try:
        await ctx.author.send(file=discord.File('data.db'))
        embed = discord.Embed(
            title="✅ Base de données sauvegardée",
            description="Le fichier `data.db` a été envoyé dans tes DM.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
    except Exception as e:
        print(f"Erreur savedb: {e}")
        embed = discord.Embed(
            title="❌ Erreur",
            description="Impossible d'envoyer la base de données. Vérifie que tes DM sont ouverts.",
            color=0xFF0000
        )
        await ctx.send(embed=embed)

@bot.command(name=">setdb")
@commands.check(lambda ctx: ctx.author.id == ADMIN_USER_ID)
async def setdb(ctx):
    """Restaure la base de données depuis un fichier attaché"""
    if not ctx.message.attachments:
        embed = discord.Embed(
            title="❌ Aucun fichier",
            description="Veuillez attacher un fichier `data.db` à votre message.",
            color=0xFF0000
        )
        return await ctx.send(embed=embed)
    
    try:
        await ctx.message.attachments[0].save('data.db')
        
        global db, cursor
        db, cursor = init_db()
        
        embed = discord.Embed(
            title="✅ Base de données restaurée",
            description="Le fichier `data.db` a été remplacé avec succès.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Erreur setdb: {e}")
        embed = discord.Embed(
            title="❌ Erreur",
            description="Impossible de restaurer la base de données.",
            color=0xFF0000
        )
        await ctx.send(embed=embed)

# ---------- ERROR HANDLING ----------
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    try:
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message("❌ Tu n'as pas les permissions nécessaires.", ephemeral=True)
        elif isinstance(error, app_commands.errors.CommandNotFound):
            await interaction.response.send_message("❌ Commande introuvable.", ephemeral=True)
        else:
            print(f"Erreur globale: {error}")
            await interaction.response.send_message("❌ Une erreur est survenue.", ephemeral=True)
    except:
        pass

# ---------- START BOT ----------
print("🤖 Démarrage du bot Discord...")
try:
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("⚠️ Token Discord manquant, maintien du health check actif...")
        while True:
            time.sleep(60)
except Exception as e:
    print(f"❌ Erreur de démarrage du bot: {e}")
    print("⚠️ Le health check reste actif")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("🔴 Arrêt du script")