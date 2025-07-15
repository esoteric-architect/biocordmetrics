import sqlite3
import discord
from discord.ext import commands
from aiohttp import web
import face_recognition
from face_recognition.api import np
import jwt
import time
import os
import json 
from dotenv import load_dotenv
from utils import get_user_encoding
load_dotenv()

JWT_SECRET =  os.getenv("JWTSECRET")
FRONTEND_URL = "http://127.0.0.1:8000/verify"
TOKEN = os.getenv("DISCORDTOKEN")
DB_PATH = 'users.db'
TIME_EXPIRY_SECONDS = 600 

bot = commands.Bot(command_prefix="/", intents=discord.Intents.all())

with open('./messages.json', 'r', encoding='utf-8') as f:
    MESSAGES = json.load(f)
    f.close()

# Views classes 
class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)


    @discord.ui.button(label="Verify Now", style=discord.ButtonStyle.success, custom_id="verify_now")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button): 
        member = interaction.user
        server = interaction.guild
         
        verify_url = create_verify_link(member=member, server=server)
        if verify_url is None : 
            print("[INFO] Interaction Error")
            await interaction.response.send_message(MESSAGES['error_occurred'], ephemeral=True)

        else : 
            try:
                embed = discord.Embed(
                    title=MESSAGES['verify_link_dm']['title'],
                    description=MESSAGES['verify_link_dm']['description'].format(verify_url=verify_url),
                    color=discord.Color.green()
                )
                embed.set_footer(text=MESSAGES['verify_link_dm']['footer'])

                await interaction.response.send_message(embed=embed, ephemeral=True) 
            except discord.Forbidden:
                await interaction.response.send_message(MESSAGES['dm_error'], ephemeral=True)

def create_verify_link(member : discord.Member | discord.User, server: discord.Guild | None ) -> str | None:
    if server is None : 
        return None 
    
    server_id = server.id
    server_name = server.name

    payload = {
        "discord_id": str(member.id),
        "server_id": str(server_id),
        "server_name": server_name,
        "exp": int(time.time()) + 600  # 10 min expiry
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    verify_url = f"{FRONTEND_URL}/{token}/{server_id}"
    return verify_url


# --- HTTP server handler ---
async def handle_verification(request):
    data = await request.json()
    discord_id = data.get("discord_id")
    server_id = data.get("server_id")

    if not discord_id or not server_id:
        return web.json_response({"error": MESSAGES['missing_ids_error']}, status=400)

    try:
        guild = bot.get_guild(int(server_id))
        user = await bot.fetch_user(int(discord_id))
        if guild is not None : 
            member = guild.get_member(int(discord_id))

            role = discord.utils.get(guild.roles, name="Face Verified")
            if role and member: 
                await member.add_roles(role)
            else : 
                try : 
                    new_role = await guild.create_role(name="Face Verified", color=discord.Color.green())
                    print(f"[INFO] Created new role for {server_id} {new_role}")
                    if member is not None : 
                        await member.add_roles(new_role)
                        print(f"[INFO] Added role to {member.name}")
                except discord.Forbidden : 
                    print("[ERROR] Don't have permission to manage roles")
                except Exception as e: 
                    print("[ERROR] {e}")
        
        embed = discord.Embed(
            title=MESSAGES['verification_success_dm']['title'],
            description=MESSAGES['verification_success_dm']['description'],
            color=discord.Color.brand_green()
        )
        embed.set_footer(text=MESSAGES['verification_success_dm']['footer'])

        await user.send(embed=embed)
        print(f"[INFO] Sent DM to {user.name}")
        return web.json_response({"status": "ok"})
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return web.json_response({"error": str(e)}, status=500)

app = web.Application()
app.router.add_post("/verified", handle_verification)

async def start_web_app():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 5000)
    await site.start()
    print("[INFO] HTTP server running on http://localhost:5000")

@bot.event
async def on_ready():
    await bot.tree.sync() 
    print(f"[INFO] Logged in as {bot.user}")
    bot.loop.create_task(start_web_app())

@bot.tree.command(name="createverification", description="Creates an embedded message for user verification.")
async def create(interaction: discord.Interaction):
    if interaction.user is not None and interaction.guild is not None and isinstance(interaction.user, discord.Member): 
        if interaction.user.top_role > interaction.guild.me.top_role : 
    
            embed = discord.Embed(
                title=MESSAGES['create_verification']['title'],
                description=MESSAGES['create_verification']['description'],
                color=discord.Color.green()
            )
            embed.set_footer(text=MESSAGES['create_verification']['footer'])

            await interaction.response.send_message(embed=embed, view=VerifyButton())
        else : 
            embed = discord.Embed(
                    title=MESSAGES['no_permission']['title'],
                    description=MESSAGES['no_permission']['description'], 
                    color=discord.Color.red()
                    )
            embed.set_footer(text=MESSAGES['no_permission']['footer'])
            await interaction.response.send_message(embed=embed, ephemeral=True)
    else : 
        print(f"[ERROR] Interaction Error user is {interaction.user} guild is {interaction.guild}")
        await interaction.response.send_message(MESSAGES['error_occurred'], ephemeral=True)

@bot.command()
async def test(ctx):
    member = ctx.author
    server = ctx.guild
    server_name = server.name
    verify_url = create_verify_link(member=member, server=server)
    if verify_url is None : 
         print("[INFO] Interaction Error")
    else : 
        try:
            embed = discord.Embed(
                title=MESSAGES['test_command_dm']['title'].format(server_name=server_name),
                description=MESSAGES['test_command_dm']['description'],
                color=discord.Color.green()
            )
            embed.add_field(
                name=MESSAGES['test_command_dm']['field_name'],
                value=MESSAGES['test_command_dm']['field_value'].format(verify_url=verify_url),
                inline=False
            )
            embed.set_footer(text=MESSAGES['test_command_dm']['footer'])

            await member.send(embed=embed)
            print(f"[INFO] Sent verification DM to {member.name}")
        except discord.Forbidden:
            print(f"[ERROR] Can't DM {member.name}. They might have DMs off.")
        except discord.HTTPException :
            print("[ERROR] API error")


def get_alt_matches(member : discord.Member, server_id : str, tolerance : float = 0.6) -> list[str] | None  : 
    encoding = get_user_encoding(discord_id=member.id, db_path=DB_PATH)
    if encoding is None : 
        return None 
    conn =  sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT discord_id, face_encoding, servers FROM users")
    rows = c.fetchall()
    conn.close() 

    alts = [] 

    for discord_id, face_blob, servers in rows : 
        if server_id not in servers.split(',') : 
            continue 
        known_encoding = np.frombuffer(face_blob, dtype=np.float64)
        matches = face_recognition.compare_faces([known_encoding], encoding, tolerance=tolerance)
        if matches[0] and discord_id != str(member.id) : 
            alts.append(discord_id)
    
    if alts : 
        return alts 
    return None 
    

@bot.tree.command(name="altcheck", description="Check if a user has an alt in the server.")
async def altcheck(interaction : discord.Interaction, member : discord.Member) : 
    
    if interaction.guild is not None:
        server_id = str(interaction.guild.id)
        alts = get_alt_matches(member=member, server_id=server_id)
        
        if alts is not None :
             embed = discord.Embed(
                    title=MESSAGES['alts_found_title'], 
                    description=MESSAGES['alts_found_description'].format(member_name=member.name, alts=alts), 
                    color=discord.Color.green() 
                    ) 
             embed.set_footer(text=MESSAGES['alts_found_footer'])
             await interaction.response.send_message(embed=embed, ephemeral=True)
        else: 
            print(f"[INFO] No alts found for {member.name}")
            embed = discord.Embed(
                    title=MESSAGES['no_alts_title'], 
                    description=MESSAGES['no_alts_description'].format(member_name=member.name), 
                    color=discord.Color.red() 
                    ) 
            embed.set_footer(text=MESSAGES['no_alts_footer'])
            await interaction.response.send_message(embed=embed, ephemeral=True)

def get_user_verified_servers(member : discord.Member) -> list[str] : 
    discord_id = str(member.id)
    conn =  sqlite3.connect(DB_PATH)
    c = conn.cursor() 
    c.execute("SELECT servers FROM users WHERE discord_id = ?", (discord_id,))
    row = c.fetchone()
    conn.close()

    if row is None:
        return []   
    servers = row[0]
    return servers.split(",") if servers else []  

async def check_role_created_by_bot(server : discord.Guild, bot_user : discord.ClientUser, limit=10) -> discord.Role | None : 
    async for entry in server.audit_logs(limit=limit, action=discord.AuditLogAction.role_create) : 
        role = entry.target 
        if role is not None and isinstance(role, discord.Role) :
            if role.name == "Face Verified" and entry.user == bot_user : 
                return role 
    return None  

async def get_status(member : discord.Member, bot_user : discord.ClientUser) -> bool:
    server = member.guild
    if server is not None :
        role  = await check_role_created_by_bot(server=server, bot_user=bot_user) 
        if role is None : 
            return False 
        return role in member.roles 
    return False 
        
@bot.tree.command(name="status", description="Get the verification status of a member.")
async def status(interaction : discord.Interaction, member : discord.Member) : 

    if bot.user is not None : 
        status = await get_status(member, bot.user)
        servers = get_user_verified_servers(member=member)
        if status:
            embed = discord.Embed(
                    title=MESSAGES['verified_title'], 
                    description=MESSAGES['verified_description'], 
                    color=discord.Color.green())
        else : 
            embed = discord.Embed(
                    title=MESSAGES['not_verified_title'], 
                    description=MESSAGES['not_verified_description'], 
                    color=discord.Color.red()
                    )
        
        embed.set_footer(text=MESSAGES['servers_footer'].format(servers_count=len(servers))) 
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="resetverification", description="reset a user face verification")
async def reset(interaction : discord.Interaction, member : discord.Member) : 
    server = interaction.guild 
    bot_user = bot.user
    if server is not None and bot_user is not None : 
        role = check_role_created_by_bot(server=server, bot_user=bot_user) 
        if role in member.roles : 
            error_occured = False 
            try : 
                await member.remove_roles(role, reason="Manual Verification Reset")
            except discord.Forbidden : 
                print("[ERROR] Bot lacks permissions to manage roles")
                error_occured = True
            except discord.HTTPException : 
                print("[ERROR] API ERROR")
                error_occured = True 
            else: 
                await interaction.response.send_message(MESSAGES['role_removed_success'])
            if error_occured : 
                await interaction.response.send_message(MESSAGES['error_occurred'])
        else : 
            await interaction.response.send_message(MESSAGES['user_not_verified'])
    else : 
        await interaction.response.send_message(MESSAGES['error_occurred'])


@bot.event
async def on_user_update(before, after) : 
    if before.name != after.name : 
        pass 

bot.run(TOKEN)
