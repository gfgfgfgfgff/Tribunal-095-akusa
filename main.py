import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import sqlite3
from datetime import datetime
from typing import Optional
import signal

# ========== HACK POUR PYTHON 3.13 ==========
if sys.version_info >= (3, 13):
    import types
    import importlib.util
    spec = importlib.util.spec_from_loader('audioop', loader=None)
    audioop = types.ModuleType('audioop')
    sys.modules['audioop'] = audioop
# ===========================================

# ========== HEALTH CHECK SERVER ==========
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'Bot Discord Tribunal en ligne!')
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "discord-bot"}')
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'Bot Discord Tribunal')
    def log_message(self, format, *args): pass

def start_health_server():
    try:
        port = int(os.environ.get('PORT', 10000))
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        print(f"✅ Serveur health check demarre sur le port {port}")
        sys.stdout.flush()
        def shutdown(signum, frame): server.shutdown()
        signal.signal(signal.SIGTERM, shutdown)
        server.serve_forever()
    except Exception as e:
        print(f"❌ Erreur serveur health check: {e}")
        sys.stdout.flush()

print("🚀 Demarrage du health check...")
threading.Thread(target=start_health_server, daemon=True).start()
time.sleep(2)
print("✅ Health check pret")
# ========== FIN HEALTH CHECK ==========

import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ ERREUR: DISCORD_TOKEN non defini!")
    print("⚠️ Le bot Discord ne demarrera pas, mais le health check est actif")

ADMIN_USER_ID = 1399234120214909010

print("🔧 Initialisation du bot Discord...")

def init_db():
    db = sqlite3.connect("data.db", check_same_thread=False)
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guild_roles (
            guild_id INTEGER, role_id INTEGER,
            role_type TEXT CHECK(role_type IN ('vote', 'ban', 'jugement')),
            PRIMARY KEY (guild_id, role_id, role_type)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY,
            ban_channel_id INTEGER, log_channel_id INTEGER, mention_role_id INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS protected_users (
            guild_id INTEGER, user_id INTEGER, protected_by INTEGER,
            protected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, reason TEXT DEFAULT '',
            PRIMARY KEY (guild_id, user_id)
        )
    """)
    db.commit()
    return db, cursor

db, cursor = init_db()
print("✅ Base de donnees initialisee")

def get_roles(guild_id: int, role_type: str):
    try:
        cursor.execute("SELECT role_id FROM guild_roles WHERE guild_id = ? AND role_type = ?", (guild_id, role_type))
        return [r[0] for r in cursor.fetchall()]
    except: return []

def has_permission(member: discord.Member, role_type: str) -> bool:
    if member.guild_permissions.administrator: return True
    return any(role.id in get_roles(member.guild.id, role_type) for role in member.roles)

def can_start_judgment(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or has_permission(member, "jugement") or has_permission(member, "ban")

def is_user_protected(guild_id: int, user_id: int) -> bool:
    try:
        cursor.execute("SELECT 1 FROM protected_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        return cursor.fetchone() is not None
    except: return False

def add_protected_user(guild_id: int, user_id: int, protected_by: int, reason: str = ""):
    try:
        cursor.execute("INSERT OR REPLACE INTO protected_users VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)", (guild_id, user_id, protected_by, reason))
        db.commit()
        return True
    except: return False

def remove_protected_user(guild_id: int, user_id: int):
    try:
        cursor.execute("DELETE FROM protected_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        db.commit()
        return cursor.rowcount > 0
    except: return False

def get_protected_users(guild_id: int):
    try:
        cursor.execute("SELECT user_id, protected_by, reason, protected_at FROM protected_users WHERE guild_id = ?", (guild_id,))
        return cursor.fetchall()
    except: return []

def get_config(guild_id: int) -> dict:
    try:
        cursor.execute("SELECT ban_channel_id, log_channel_id, mention_role_id FROM config WHERE guild_id = ?", (guild_id,))
        r = cursor.fetchone()
        if r: return {"ban_channel_id": r[0], "log_channel_id": r[1], "mention_role_id": r[2]}
    except: pass
    return {"ban_channel_id": None, "log_channel_id": None, "mention_role_id": None}

def set_config(guild_id: int, **kwargs):
    try:
        c = get_config(guild_id)
        cursor.execute("INSERT OR REPLACE INTO config VALUES (?, ?, ?, ?)",
            (guild_id, kwargs.get('ban_channel_id', c['ban_channel_id']),
             kwargs.get('log_channel_id', c['log_channel_id']),
             kwargs.get('mention_role_id', c['mention_role_id'])))
        db.commit()
        return True
    except: return False

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix=[">", "!"], intents=intents)

class TribunalView(discord.ui.View):
    def __init__(self, target, original_embed, proof_url=None, moderator=None):
        super().__init__(timeout=None)
        self.target = target
        self.votes_yes = set()
        self.votes_no = set()
        self.original_embed = original_embed
        self.proof_url = proof_url
        self.moderator = moderator
        self.has_concluded = False

    async def update_embed(self, message):
        oui = " ".join(f"<@{uid}>" for uid in self.votes_yes) if self.votes_yes else "Aucun"
        non = " ".join(f"<@{uid}>" for uid in self.votes_no) if self.votes_no else "Aucun"
        embed = discord.Embed(title=self.original_embed.title, color=self.original_embed.color, timestamp=self.original_embed.timestamp)
        embed.set_thumbnail(url=self.original_embed.thumbnail.url)
        for f in self.original_embed.fields:
            if f.name not in ["Pour :", "Contre :", "⚖️ Etat du jugement"]:
                embed.add_field(name=f.name, value=f.value, inline=f.inline)
        embed.add_field(name="⚖️ Etat du jugement", value=f"✅ **OUI** ({len(self.votes_yes)}/3)\n{oui}\n\n❌ **NON** ({len(self.votes_no)}/3)\n{non}", inline=False)
        await message.edit(embed=embed)

    async def check_verdict(self, i):
        if len(self.votes_yes) >= 3:
            try:
                await self.target.ban(reason="Vote du tribunal (3 oui)")
                await i.message.edit(embed=discord.Embed(title="🔨 VERDICT : BANNISSEMENT APPLIQUE", description=f"{self.target.mention} a ete banni.", color=discord.Color.red()), view=None)
                self.has_concluded = True
            except: await i.message.edit(embed=discord.Embed(title="❌ ERREUR", description="Permission manquante", color=discord.Color.orange()), view=None)
        elif len(self.votes_no) >= 3:
            await i.message.edit(embed=discord.Embed(title="❌ VERDICT : JUGEMENT ANNULE", description="Non-bannissement", color=discord.Color.green()), view=None)
            self.has_concluded = True
        else: await self.update_embed(i.message)

    @discord.ui.button(label="Oui", emoji="✅", style=discord.ButtonStyle.success)
    async def oui(self, i, b):
        if not has_permission(i.user, "vote"): return await i.response.send_message("Non autorise.", ephemeral=True)
        if i.user.id in self.votes_yes | self.votes_no: return await i.response.send_message("Deja vote.", ephemeral=True)
        self.votes_yes.add(i.user.id)
        await i.response.send_message("✅ Vote OUI enregistre!", ephemeral=True)
        await self.check_verdict(i)

    @discord.ui.button(label="Non", emoji="❌", style=discord.ButtonStyle.danger)
    async def non(self, i, b):
        if not has_permission(i.user, "vote"): return await i.response.send_message("Non autorise.", ephemeral=True)
        if i.user.id in self.votes_yes | self.votes_no: return await i.response.send_message("Deja vote.", ephemeral=True)
        self.votes_no.add(i.user.id)
        await i.response.send_message("❌ Vote NON enregistre!", ephemeral=True)
        await self.check_verdict(i)

    @discord.ui.button(label="Bannir", emoji="👨‍⚖️", style=discord.ButtonStyle.secondary)
    async def bannir(self, i, b):
        if not has_permission(i.user, "ban"): return await i.response.send_message("Non autorise.", ephemeral=True)
        try:
            await self.target.ban(reason="Bannissement direct")
            await i.message.edit(embed=discord.Embed(title="🔨 BANNISSEMENT DIRECT", description=f"{self.target.mention} banni par {i.user.mention}", color=discord.Color.red()), view=None)
        except: await i.response.send_message("❌ Permission manquante.", ephemeral=True)

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ Connecte: {bot.user}")
        print(f"✅ {len(synced)} commandes slash")
        print(f"✅ Serveurs: {len(bot.guilds)}")
    except Exception as e: print(f"❌ Erreur sync: {e}")

# ========== SLASH COMMANDS ==========
@bot.tree.command(name="config", description="Configurer le bot (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
async def config(i, salon_jugement: Optional[discord.TextChannel]=None, salon_logs: Optional[discord.TextChannel]=None, role_mentionner: Optional[discord.Role]=None):
    try:
        if not any([salon_jugement, salon_logs, role_mentionner]):
            cursor.execute("DELETE FROM config WHERE guild_id = ?", (i.guild_id,)); db.commit()
            return await i.response.send_message("✅ Configuration reinitialisee.", ephemeral=True)
        set_config(i.guild_id, ban_channel_id=salon_jugement.id if salon_jugement else None,
                  log_channel_id=salon_logs.id if salon_logs else None,
                  mention_role_id=role_mentionner.id if role_mentionner else None)
        await i.response.send_message("✅ Configuration mise a jour.", ephemeral=True)
    except Exception as e: await i.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="ban", description="Lancer un jugement")
async def ban(i: discord.Interaction, user: discord.Member, raison: str, preuve: discord.Attachment):
    try:
        if is_user_protected(i.guild_id, user.id): return await i.response.send_message("❌ Membre protege.", ephemeral=True)
        if not can_start_judgment(i.user): return await i.response.send_message("❌ Permission refusee.", ephemeral=True)
        if preuve.content_type not in ['image/jpeg','image/jpg','image/png','image/gif','image/webp','video/mp4','video/quicktime','video/x-msvideo','video/x-ms-wmv','video/webm']:
            return await i.response.send_message("❌ Image ou video requise.", ephemeral=True)
        e = discord.Embed(title=f"⚖️ Jugement de {user}", color=discord.Color.dark_red(), timestamp=datetime.now())
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(name="👮 Moderateurburu", value=i.user.mention, inline=False)
        e.add_field(name="🦹 Accuse", value=user.mention, inline=False)
        e.add_field(name="📋 Raison", value=raison, inline=False)
        e.add_field(name="📁 Preuve", value=f"[Voir la preuve]({preuve.url})", inline=False)
        e.add_field(name="⚖️ Etat", value="✅ OUI (0/3)\n❌ NON (0/3)", inline=False)
        cfg = get_config(i.guild_id)
        chan = i.guild.get_channel(cfg['ban_channel_id']) if cfg['ban_channel_id'] else i.channel
        mention = f"<@&{cfg['mention_role_id']}>" if cfg.get('mention_role_id') and i.guild.get_role(cfg['mention_role_id']) else ""
        await i.response.send_message(f"✅ Jugement lance dans {chan.mention}", ephemeral=True)
        await chan.send(content=mention, embed=e, view=TribunalView(user, e, preuve.url, i.user))
    except Exception as e: await i.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="autorise", description="Gerer les roles (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(type=[app_commands.Choice(n, v) for n, v in [("vote","vote"), ("ban","ban"), ("jugement","jugement")]])
async def autorise(i, role: discord.Role, type: app_commands.Choice[str]):
    try:
        cursor.execute("SELECT 1 FROM guild_roles WHERE guild_id=? AND role_id=? AND role_type=?", (i.guild_id, role.id, type.value))
        exists = cursor.fetchone()
        if exists:
            cursor.execute("DELETE FROM guild_roles WHERE guild_id=? AND role_id=? AND role_type=?", (i.guild_id, role.id, type.value))
            action, color = "desautorise", discord.Color.orange()
        else:
            cursor.execute("INSERT INTO guild_roles VALUES (?, ?, ?)", (i.guild_id, role.id, type.value))
            action, color = "autorise", discord.Color.green()
        db.commit()
        await i.response.send_message(f"✅ {role.mention} {action} pour {type.value}.", ephemeral=True)
    except Exception as e: await i.response.send_message(f"❌ Erreur: {str(e)[:100]}", ephemeral=True)

@bot.tree.command(name="protect", description="Proteger un utilisateur (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
async def protect(i, user: discord.Member, raison: str = ""):
    if is_user_protected(i.guild_id, user.id): return await i.response.send_message(f"❌ {user.mention} deja protege.", ephemeral=True)
    if add_protected_user(i.guild_id, user.id, i.user.id, raison):
        await i.response.send_message(f"✅ {user.mention} protege.", ephemeral=True)
    else: await i.response.send_message("❌ Erreur.", ephemeral=True)

@bot.tree.command(name="unprotect", description="Retirer protection (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
async def unprotect(i, user: discord.Member):
    if not is_user_protected(i.guild_id, user.id): return await i.response.send_message(f"❌ {user.mention} non protege.", ephemeral=True)
    if remove_protected_user(i.guild_id, user.id):
        await i.response.send_message(f"✅ Protection retiree.", ephemeral=True)
    else: await i.response.send_message("❌ Erreur.", ephemeral=True)

@bot.tree.command(name="protected", description="Liste des proteges")
async def protected(i):
    users = get_protected_users(i.guild_id)
    if not users: return await i.response.send_message("Aucun protege.", ephemeral=True)
    e = discord.Embed(title="🛡️ Utilisateurs proteges", color=discord.Color.blue())
    for uid, pid, r, t in users[:10]:
        u = i.guild.get_member(uid)
        e.add_field(name=u.mention if u else f"`{uid}`", value=f"Par: <@{pid}>\nRaison: {r or 'Aucune'}", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="info", description="Configuration actuelle")
async def info(i):
    cfg = get_config(i.guild_id)
    e = discord.Embed(title="⚙️ Configuration", color=discord.Color.blue())
    e.add_field(name="📁 Salon jugement", value=f"<#{cfg['ban_channel_id']}>" if cfg['ban_channel_id'] else "Non defini", inline=False)
    e.add_field(name="📋 Salon logs", value=f"<#{cfg['log_channel_id']}>" if cfg['log_channel_id'] else "Non defini", inline=False)
    e.add_field(name="👥 Role mention", value=f"<@&{cfg['mention_role_id']}>" if cfg['mention_role_id'] else "Non defini", inline=False)
    e.add_field(name="🛡️ Proteges", value=f"{len(get_protected_users(i.guild_id))} utilisateur(s)", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)

# ========== COMMANDES SLASH DB (PROPRIETAIRE SEULEMENT) ==========
@bot.tree.command(name="savedb", description="[PROPRIETAIRE] Sauvegarder la base de donnees")
async def savedb_slash(i: discord.Interaction):
    if i.user.id != i.guild.owner_id:
        return await i.response.send_message(embed=discord.Embed(title="❌ Acces refuse", description="Seul le proprietaire du serveur peut utiliser cette commande.", color=0xFF0000), ephemeral=True)
    try:
        await i.user.send(file=discord.File('data.db'))
        await i.response.send_message(embed=discord.Embed(title="✅ Sauvegarde reussie", description="Fichier `data.db` envoye en DM.", color=0x00FF00), ephemeral=True)
    except:
        await i.response.send_message(embed=discord.Embed(title="❌ Erreur", description="Impossible d'envoyer en DM.", color=0xFF0000), ephemeral=True)

@bot.tree.command(name="setdb", description="[PROPRIETAIRE] Restaurer la base de donnees")
async def setdb_slash(i: discord.Interaction, fichier: discord.Attachment):
    if i.user.id != i.guild.owner_id:
        return await i.response.send_message(embed=discord.Embed(title="❌ Acces refuse", description="Seul le proprietaire du serveur peut utiliser cette commande.", color=0xFF0000), ephemeral=True)
    if not fichier.filename.endswith('.db'):
        return await i.response.send_message(embed=discord.Embed(title="❌ Fichier invalide", description="Le fichier doit etre au format .db", color=0xFF0000), ephemeral=True)
    try:
        await fichier.save('data.db')
        global db, cursor
        db, cursor = init_db()
        await i.response.send_message(embed=discord.Embed(title="✅ Restauration reussie", description="Base de donnees remplacee avec succes.", color=0x00FF00), ephemeral=True)
    except:
        await i.response.send_message(embed=discord.Embed(title="❌ Erreur", description="Impossible de restaurer la base de donnees.", color=0xFF0000), ephemeral=True)

# ========== PREFIX COMMANDS (GARDEES POUR COMPATIBILITE) ==========
@bot.command(name=">savedb")
@commands.check(lambda ctx: ctx.author.id == ADMIN_USER_ID)
async def savedb_prefix(ctx):
    try:
        await ctx.author.send(file=discord.File('data.db'))
        await ctx.send(embed=discord.Embed(title="✅ Sauvegarde", description="Fichier envoye en DM.", color=0x00FF00))
    except:
        await ctx.send(embed=discord.Embed(title="❌ Erreur", description="DM fermes.", color=0xFF0000))

@bot.command(name=">setdb")
@commands.check(lambda ctx: ctx.author.id == ADMIN_USER_ID)
async def setdb_prefix(ctx):
    if not ctx.message.attachments:
        return await ctx.send(embed=discord.Embed(title="❌ Fichier manquant", description="Attache un fichier .db", color=0xFF0000))
    try:
        await ctx.message.attachments[0].save('data.db')
        global db2, cursor2
        db2, cursor2 = init_db()
        await ctx.send(embed=discord.Embed(title="✅ Restauration", description="Base de donnees remplacee.", color=0x00FF00))
    except:
        await ctx.send(embed=discord.Embed(title="❌ Erreur", description="Restauration echouee.", color=0xFF0000))

@bot.tree.error
async def on_error(i, error):
    try:
        if isinstance(error, app_commands.errors.MissingPermissions):
            await i.response.send_message("❌ Permissions administrateur requises.", ephemeral=True)
        else:
            print(f"Erreur: {error}")
            await i.response.send_message("❌ Une erreur est survenue.", ephemeral=True)
    except: pass

print("🤖 Demarrage du bot Discord...")
if TOKEN:
    bot.run(TOKEN)
else:
    while True: time.sleep(60)