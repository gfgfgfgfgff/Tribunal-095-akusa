import os
import sqlite3
from datetime import datetime
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_USER_ID = 1399234120214909010

# ================= DATABASE =================

def init_db():
    db = sqlite3.connect("data.db", check_same_thread=False)
    c = db.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS guild_roles(
        guild_id INT,
        role_id INT,
        role_type TEXT,
        PRIMARY KEY(guild_id, role_id, role_type)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS protected_users(
        guild_id INT,
        user_id INT,
        protected_by INT,
        PRIMARY KEY(guild_id, user_id)
    )""")
    db.commit()
    return db, c

db, cursor = init_db()

def get_roles(gid, t):
    cursor.execute("SELECT role_id FROM guild_roles WHERE guild_id=? AND role_type=?", (gid, t))
    return [r[0] for r in cursor.fetchall()]

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

# ================= BOT =================

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

WHITE = discord.Color.from_rgb(255, 255, 255)

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

    def build_embed(self, banned_by=None):
        desc = f"""Accusè : {self.target.mention}

Juge : {self.juge.mention}

Raison : {self.raison}

Preuves : {self.preuve}

────────────────────────────

✅ oui ({len(self.yes)}/3)
❌ non ({len(self.no)}/3)"""

        if banned_by:
            desc += f"\n\n🔨 Juge : {banned_by.mention}"

        return discord.Embed(
            title=f"Jugement de {self.target}",
            description=desc,
            color=WHITE
        )

    async def disable_all(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Oui", style=discord.ButtonStyle.success)
    async def yes_btn(self, interaction: discord.Interaction, button):
        if interaction.user.id in self.yes or interaction.user.id in self.no:
            return await interaction.response.send_message("Tu as deja voté !", ephemeral=True)

        if not any(r.id in get_roles(interaction.guild.id, "vote") for r in interaction.user.roles):
            return await interaction.response.send_message("Tu na pas les permissions requises !", ephemeral=True)

        self.yes.add(interaction.user.id)
        await interaction.response.send_message("Votre vote a bien etait enregistré !", ephemeral=True)

        if len(self.yes) >= 3:
            await self.target.ban(reason="Vote 3/3")
            await self.disable_all()
            await interaction.message.edit(embed=self.build_embed(banned_by=interaction.user), view=self)
        else:
            await interaction.message.edit(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Non", style=discord.ButtonStyle.danger)
    async def no_btn(self, interaction: discord.Interaction, button):
        if interaction.user.id in self.yes or interaction.user.id in self.no:
            return await interaction.response.send_message("Tu as deja voté !", ephemeral=True)

        if not any(r.id in get_roles(interaction.guild.id, "vote") for r in interaction.user.roles):
            return await interaction.response.send_message("Tu na pas les permissions requises !", ephemeral=True)

        self.no.add(interaction.user.id)
        await interaction.response.send_message("Votre vote a bien etait enregistré !", ephemeral=True)
        await interaction.message.edit(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Bannir", style=discord.ButtonStyle.secondary)
    async def direct_ban(self, interaction: discord.Interaction, button):
        if not any(r.id in get_roles(interaction.guild.id, "ban") for r in interaction.user.roles):
            return await interaction.response.send_message("Tu na pas les permissions requises !", ephemeral=True)

        await self.target.ban(reason="Bannissement direct")
        await self.disable_all()
        await interaction.response.defer()
        await interaction.message.edit(embed=self.build_embed(banned_by=interaction.user), view=self)

# ================= COMMANDE /JUGER =================

@bot.tree.command(name="juger")
async def juger(interaction: discord.Interaction, user: discord.Member, raison: str, preuve: str):

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
            f"Tu ne peux pas juger {user.mention} car il est égal ou supérieur à toi",
            ephemeral=True
        )

    if user.top_role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            "Je ne peux pas bannir cet utilisateur car son rôle est supérieur au mien",
            ephemeral=True
        )

    view = TribunalView(user, interaction.user, raison, preuve)
    embed = view.build_embed()
    await interaction.response.send_message(embed=embed, view=view)

# ================= START =================

@bot.event
async def on_ready():
    await bot.tree.sync()
    print("Bot prêt")

if TOKEN:
    bot.run(TOKEN)