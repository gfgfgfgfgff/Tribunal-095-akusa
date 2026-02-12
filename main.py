import os,sys,threading,time
from http.server import HTTPServer, BaseHTTPRequestHandler
import sqlite3
from datetime import datetime
from typing import Optional
import signal

# ========== HACK PY3.13 ==========
if sys.version_info>=(3,13):
    import types,importlib.util
    sys.modules['audioop']=types.ModuleType('audioop')
# ========== HEALTH CHECK ==========
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type','text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'Bot OK')
    def log_message(self,*a,**k):pass
def start_health():
    try:
        server=HTTPServer(('0.0.0.0',int(os.environ.get('PORT',10000))),HealthHandler)
        print(f"✅ Health check sur port {os.environ.get('PORT',10000)}")
        server.serve_forever()
    except:pass
threading.Thread(target=start_health,daemon=True).start()
time.sleep(1)
# ========== IMPORTS ==========
import discord
from discord.ext import commands
from discord import app_commands
TOKEN=os.getenv("DISCORD_TOKEN")
if not TOKEN:print("❌ Token manquant!")
ADMIN_USER_ID=1399234120214909010

# ========== DB ==========
def init_db():
    db=sqlite3.connect("data.db",check_same_thread=False)
    c=db.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS guild_roles(guild_id INT,role_id INT,role_type TEXT,PRIMARY KEY(guild_id,role_id,role_type))")
    c.execute("CREATE TABLE IF NOT EXISTS config(guild_id INT PRIMARY KEY,ban_channel_id INT,log_channel_id INT,mention_role_id INT)")
    c.execute("CREATE TABLE IF NOT EXISTS protected_users(guild_id INT,user_id INT,protected_by INT,protected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,reason TEXT DEFAULT '',PRIMARY KEY(guild_id,user_id))")
    db.commit()
    return db,c
db,cursor=init_db()

def get_roles(gid,t):cursor.execute("SELECT role_id FROM guild_roles WHERE guild_id=? AND role_type=?",(gid,t));return[r[0]for r in cursor.fetchall()]
def has_perm(m,t):return m.guild_permissions.administrator or any(r.id in get_roles(m.guild.id,t)for r in m.roles)
def can_judge(m):return m.guild_permissions.administrator or has_perm(m,"jugement")or has_perm(m,"ban")
def is_protected(gid,uid):cursor.execute("SELECT 1 FROM protected_users WHERE guild_id=? AND user_id=?",(gid,uid));return cursor.fetchone()is not None
def add_protected(gid,uid,pid,r=""):cursor.execute("INSERT OR REPLACE INTO protected_users VALUES(?,?,?,CURRENT_TIMESTAMP,?)",(gid,uid,pid,r));db.commit();return True
def rem_protected(gid,uid):cursor.execute("DELETE FROM protected_users WHERE guild_id=? AND user_id=?",(gid,uid));db.commit();return cursor.rowcount>0
def get_protected(gid):cursor.execute("SELECT user_id,protected_by,reason,protected_at FROM protected_users WHERE guild_id=?",(gid,));return cursor.fetchall()
def get_config(gid):
    cursor.execute("SELECT ban_channel_id,log_channel_id,mention_role_id FROM config WHERE guild_id=?",(gid,))
    r=cursor.fetchone()
    return{"ban_channel_id":r[0],"log_channel_id":r[1],"mention_role_id":r[2]}if r else{}
def set_config(gid,**k):
    c=get_config(gid)
    cursor.execute("INSERT OR REPLACE INTO config VALUES(?,?,?,?)",(gid,k.get('ban_channel_id',c.get('ban_channel_id')),k.get('log_channel_id',c.get('log_channel_id')),k.get('mention_role_id',c.get('mention_role_id'))))
    db.commit()

# ========== BOT ==========
intents=discord.Intents.default()
intents.members=intents.message_content=True
bot=commands.Bot(command_prefix=[">","!"],intents=intents)

# ========== TRIBUNAL VIEW ==========
class TribunalView(discord.ui.View):
    def __init__(self,target,embed,proof=None,mod=None):
        super().__init__(timeout=None)
        self.target=target;self.yes=set();self.no=set();self.e=embed;self.mod=mod;self.done=False
    async def update(self,m):
        y=" ".join(f"<@{u}>"for u in self.yes)or"Aucun";n=" ".join(f"<@{u}>"for u in self.no)or"Aucun"
        e=discord.Embed(title=self.e.title,color=self.e.color,timestamp=self.e.timestamp)
        e.set_thumbnail(url=self.e.thumbnail.url)
        for f in self.e.fields:
            if f.name not in["⚖️ Etat"]:e.add_field(name=f.name,value=f.value)
        e.add_field(name="⚖️ Etat",value=f"✅ OUI ({len(self.yes)}/3)\n{y}\n❌ NON ({len(self.no)}/3)\n{n}",inline=False)
        await m.edit(embed=e)
    async def verdict(self,i):
        if len(self.yes)>=3:
            try:await self.target.ban(reason="Vote 3/3");await i.message.edit(embed=discord.Embed(title="🔨 BANNI",color=discord.Color.red()),view=None);self.done=True
            except:await i.message.edit(embed=discord.Embed(title="❌ PERMISSION",color=discord.Color.orange()),view=None)
        elif len(self.no)>=3:
            await i.message.edit(embed=discord.Embed(title="❌ ANNULE",color=discord.Color.green()),view=None);self.done=True
        else:await self.update(i.message)
    @discord.ui.button(label="Oui",emoji="✅",style=discord.ButtonStyle.success)
    async def oui(self,i,b):
        if not has_perm(i.user,"vote"):return await i.response.send_message("❌ Non autorise",ephemeral=True)
        if i.user.id in self.yes|self.no:return await i.response.send_message("❌ Deja vote",ephemeral=True)
        self.yes.add(i.user.id);await i.response.send_message("✅ Vote OUI",ephemeral=True);await self.verdict(i)
    @discord.ui.button(label="Non",emoji="❌",style=discord.ButtonStyle.danger)
    async def non(self,i,b):
        if not has_perm(i.user,"vote"):return await i.response.send_message("❌ Non autorise",ephemeral=True)
        if i.user.id in self.yes|self.no:return await i.response.send_message("❌ Deja vote",ephemeral=True)
        self.no.add(i.user.id);await i.response.send_message("✅ Vote NON",ephemeral=True);await self.verdict(i)
    @discord.ui.button(label="Bannir",emoji="👨‍⚖️",style=discord.ButtonStyle.secondary)
    async def direct(self,i,b):
        if not has_perm(i.user,"ban"):return await i.response.send_message("❌ Non autorise",ephemeral=True)
        try:await self.target.ban(reason=f"Direct par {i.user}");await i.message.edit(embed=discord.Embed(title=f"🔨 Banni par {i.user.name}",color=discord.Color.red()),view=None)
        except:await i.response.send_message("❌ Erreur",ephemeral=True)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} | {len(bot.guilds)} serveurs")

# ========== SLASH COMMANDS ==========
@bot.tree.command(name="config",description="Configurer (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
async def config(i,salon_jugement:Optional[discord.TextChannel]=None,salon_logs:Optional[discord.TextChannel]=None,role_mentionner:Optional[discord.Role]=None):
    if not any([salon_jugement,salon_logs,role_mentionner]):
        cursor.execute("DELETE FROM config WHERE guild_id=?",(i.guild_id,));db.commit()
        return await i.response.send_message("✅ Reset",ephemeral=True)
    set_config(i.guild_id,ban_channel_id=salon_jugement.id if salon_jugement else None,log_channel_id=salon_logs.id if salon_logs else None,mention_role_id=role_mentionner.id if role_mentionner else None)
    await i.response.send_message("✅ OK",ephemeral=True)

@bot.tree.command(name="ban",description="Lancer jugement")
async def ban(i:discord.Interaction,user:discord.Member,raison:str,preuve:discord.Attachment):
    if is_protected(i.guild_id,user.id):return await i.response.send_message("❌ Protege",ephemeral=True)
    if not can_judge(i.user):return await i.response.send_message("❌ Permission",ephemeral=True)
    if not preuve.content_type.startswith(('image/','video/')):return await i.response.send_message("❌ Image/Video",ephemeral=True)
    e=discord.Embed(title=f"⚖️ {user.name}",color=discord.Color.dark_red(),timestamp=datetime.now())
    e.set_thumbnail(url=user.display_avatar.url)
    e.add_field(name="Modo",value=i.user.mention);e.add_field(name="Accuse",value=user.mention)
    e.add_field(name="Raison",value=raison);e.add_field(name="Preuve",value=f"[Lien]({preuve.url})")
    e.add_field(name="⚖️ Etat",value="✅ 0/3\n❌ 0/3")
    cfg=get_config(i.guild_id)
    chan=i.guild.get_channel(cfg.get('ban_channel_id'))or i.channel
    role=f"<@&{cfg['mention_role_id']}>"if cfg.get('mention_role_id')else""
    await i.response.send_message(f"✅ Envoye dans {chan.mention}",ephemeral=True)
    await chan.send(content=role,embed=e,view=TribunalView(user,e,preuve.url,i.user))

@bot.tree.command(name="autorise",description="Roles (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(t=[app_commands.Choice(name=x,value=x)for x in["vote","ban","jugement"]])
async def autorise(i,role:discord.Role,t:app_commands.Choice[str]):
    cursor.execute("SELECT 1 FROM guild_roles WHERE guild_id=? AND role_id=? AND role_type=?",(i.guild_id,role.id,t.value))
    if cursor.fetchone():
        cursor.execute("DELETE FROM guild_roles WHERE guild_id=? AND role_id=? AND role_type=?",(i.guild_id,role.id,t.value))
        await i.response.send_message(f"❌ {role.mention} desautorise",ephemeral=True)
    else:
        cursor.execute("INSERT INTO guild_roles VALUES(?,?,?)",(i.guild_id,role.id,t.value))
        await i.response.send_message(f"✅ {role.mention} autorise",ephemeral=True)
    db.commit()

@bot.tree.command(name="protect",description="Proteger (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
async def protect(i,user:discord.Member,raison:str=""):
    if is_protected(i.guild_id,user.id):return await i.response.send_message("❌ Deja protege",ephemeral=True)
    add_protected(i.guild_id,user.id,i.user.id,raison)
    await i.response.send_message(f"✅ {user.mention} protege",ephemeral=True)

@bot.tree.command(name="unprotect",description="Deproteger (ADMIN)")
@app_commands.checks.has_permissions(administrator=True)
async def unprotect(i,user:discord.Member):
    if not is_protected(i.guild_id,user.id):return await i.response.send_message("❌ Non protege",ephemeral=True)
    rem_protected(i.guild_id,user.id)
    await i.response.send_message(f"✅ Protection retiree",ephemeral=True)

@bot.tree.command(name="protected",description="Liste proteges")
async def protected(i):
    users=get_protected(i.guild_id)
    if not users:return await i.response.send_message("Aucun protege",ephemeral=True)
    e=discord.Embed(title="🛡️ Proteges",color=discord.Color.blue())
    for uid,pid,r,t in users[:10]:e.add_field(name=f"<@{uid}>",value=f"Par: <@{pid}>\nRaison: {r or 'Aucune'}",inline=False)
    await i.response.send_message(embed=e,ephemeral=True)

@bot.tree.command(name="info",description="Config actuelle")
async def info(i):
    cfg=get_config(i.guild_id)
    e=discord.Embed(title="⚙️ Config",color=discord.Color.blue())
    e.add_field(name="📁 Jugement",value=f"<#{cfg['ban_channel_id']}>"if cfg.get('ban_channel_id')else"Non defini")
    e.add_field(name="📋 Logs",value=f"<#{cfg['log_channel_id']}>"if cfg.get('log_channel_id')else"Non defini")
    e.add_field(name="👥 Mention",value=f"<@&{cfg['mention_role_id']}>"if cfg.get('mention_role_id')else"Non defini")
    e.add_field(name="🛡️ Proteges",value=f"{len(get_protected(i.guild_id))} utilisateur(s)")
    await i.response.send_message(embed=e,ephemeral=True)

# ========== DB SLASH (PROPRIETAIRE) ==========
@bot.tree.command(name="savedb",description="[PROPRIETAIRE] Sauvegarde DB")
async def savedb(i):
    if i.user.id!=i.guild.owner_id:return await i.response.send_message("❌ Proprietaire seulement",ephemeral=True)
    try:
        await i.user.send(file=discord.File('data.db'))
        await i.response.send_message("✅ DB envoyee en DM",ephemeral=True)
    except:await i.response.send_message("❌ DM ferme",ephemeral=True)

@bot.tree.command(name="setdb",description="[PROPRIETAIRE] Restaure DB")
async def setdb(i,fichier:discord.Attachment):
    if i.user.id!=i.guild.owner_id:return await i.response.send_message("❌ Proprietaire seulement",ephemeral=True)
    if not fichier.filename.endswith('.db'):return await i.response.send_message("❌ Fichier .db requis",ephemeral=True)
    try:
        await fichier.save('data.db')
        global db,cursor;db,cursor=init_db()
        await i.response.send_message("✅ DB restauree",ephemeral=True)
    except:await i.response.send_message("❌ Erreur",ephemeral=True)

# ========== PREFIX (ADMIN) ==========
@bot.command(name=">savedb")
@commands.check(lambda ctx:ctx.author.id==ADMIN_USER_ID)
async def savedb_p(ctx):
    try:
        await ctx.author.send(file=discord.File('data.db'))
        await ctx.send("✅ DB envoyee")
    except:await ctx.send("❌ Erreur")

@bot.command(name=">setdb")
@commands.check(lambda ctx:ctx.author.id==ADMIN_USER_ID)
async def setdb_p(ctx):
    if not ctx.message.attachments:return await ctx.send("❌ Attache un fichier")
    try:
        await ctx.message.attachments[0].save('data.db')
        global db2,cursor2;db2,cursor2=init_db()
        await ctx.send("✅ DB restauree")
    except:await ctx.send("❌ Erreur")

# ========== START ==========
if TOKEN:bot.run(TOKEN)
else:
    while 1:time.sleep(60)