import os
import subprocess
import re
import json
import discord
import paramiko
from wakeonlan import send_magic_packet
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

load_dotenv()

client = discord.Client(intents=discord.Intents.default())
cmd = discord.app_commands
tree = cmd.CommandTree(client)

GLOBAL_IP = subprocess.run(["curl", "-s", "https://api.ipify.org"], capture_output=True, text=True).stdout.strip()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
SSH_HOST = os.getenv('SSH_HOST')
SSH_PORT = int(os.getenv('SSH_PORT', 22))
SSH_USER = os.getenv('SSH_USER')
TARGET_MAC = os.getenv('TARGET_MAC')
BROADCAST_IP = os.getenv('BROADCAST_IP')

PING_TIMEOUT = 120

executor = ThreadPoolExecutor()

def ping_host(host):
    """指定されたホストにpingを送信し、応答があるか確認"""
    try:
        command = ["ping", "-c", "1", "-W", "1", host]
        return subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def execute_remote_command(command):
    """SSH経由でリモートコマンドを実行"""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER)

    stdin, stdout, stderr = ssh.exec_command(command)
    output = stdout.read().decode('utf-8')
    error = stderr.read().decode('utf-8')
    ssh.close()

    if error:
        raise Exception(f"SSHエラー: {error}")
    return output

async def execute_remote_command_async(command):
    """SSH経由でリモートコマンドを非同期で実行"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, execute_remote_command, command)

@client.event
async def on_ready():
    await client.change_presence()
    await tree.sync()

profiles = json.load(open("./servers.json", "r"))
server_choices = [cmd.Choice(name=profile['name'], value=profile['id']) for profile in profiles]
contents = {
    "start": {"emoji":"white_check_mark","msg":"起動", "color": 0x00ff00},
    "stop": {"emoji":"octagonal_sign","msg":"停止", "color": 0xff0000},
    "gsm": {"emoji":"desktop","msg":"コマンドを実行", "color": 0x0000ff}
}

async def manage_server(interaction: discord.Interaction, server: str, action: str):
    await interaction.response.defer()
    index = next(i for i, profile in enumerate(profiles) if profile['id'] == server)
    profile = profiles[index]
    
    gsm = profile["gsm"]
    if gsm:
        command = f"/home/mame/games/{server}/gs {action}"
    else:
        command = profile["command"][action]

    try:
        await execute_remote_command_async(command)
    except Exception as e:
        await interaction.followup.send(f"エラー: {str(e)}")
        return
    
    content = contents[action]
    embed = discord.Embed(title=f":{content['emoji']}: {content['msg']}しました",
                          description=f"{profile['name']}が{content['msg']}しました", color=content['color'])

    if action == "start":
        embed.add_field(name="アドレス", value=f"{GLOBAL_IP}:{profile['info']['port']}")
        if 'password' in profile['info']:
            embed.add_field(name="パスワード", value=profile['info']['password'])

        await client.change_presence(activity=discord.Game(profile["name"]))
    else:
        await client.change_presence()
    await interaction.followup.send(embed=embed)

@tree.command(name="start", description="サーバー起動")
@cmd.describe(server="起動するサーバーを選んでください")
@cmd.choices(server=server_choices)
async def on_start(interaction: discord.Interaction, server: str):
    await manage_server(interaction, server, "start")

@tree.command(name="stop", description="サーバー停止")
@cmd.describe(server="停止するサーバーを選んでください")
@cmd.choices(server=server_choices)
async def on_stop(interaction: discord.Interaction, server: str):
    await manage_server(interaction, server, "stop")

gsm_servers = [cmd.Choice(name=profile['name'], value=profile['id']) for profile in profiles if profile["gsm"]]
actions = [
        ["Start", "start"], ["Stop", "stop"], ["Restart", "restart"],
        ["Details", "details"], ["Post Details", "postdetails"],["Skeleton", "skeleton"],
        ["Backup", "backup"], ["Update LinuxGSM", "update-lgsm"], ["Monitor", "monitor"],
        ["Test Alert", "test-alert"], ["Update", "update"], ["Check Update", "check-update"],
        ["Force Update", "force-update"], ["Validate", "validate"]
    ]
action_choices = [cmd.Choice(name=action[0], value=action[1]) for action in actions]

@tree.command(name="gsm", description="サーバー管理")
@cmd.describe(server="LinuxGSMで操作するサーバーを選んでください")
@cmd.choices(server=gsm_servers, action=action_choices)
async def on_gsm(interaction: discord.Interaction, server: str, action: str):
    await interaction.response.defer()

    try:
        command = f"/home/mame/games/{server}/gs {action}"
        output = await execute_remote_command_async(command)
        
        true_output = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]').sub('', output)
        status = "成功"
        
    except Exception as e:
        true_output = str(e)
        status = "失敗"

    content = contents["gsm"]
    embed = discord.Embed(
        title=f":{content['emoji'] if status == '成功' else 'warning'}: コマンド実行 {status}",
        description=f"{server}でコマンド'{action}'を実行しました",
        color=content["color"]
    )

    if len(true_output) > 1024:
        with open("log.txt", "w", encoding="utf-8") as f:
            f.write(true_output)

        await interaction.followup.send(embed=embed, file=discord.File("log.txt"))
        
        try:
            os.remove("log.txt")
        except:
            pass
    else:
        embed.add_field(name="実行結果", value=f"```{true_output}```")
        await interaction.followup.send(embed=embed)

@tree.command(name="on", description="デバイスを起動します")
async def on_power_on(interaction: discord.Interaction):
    """WoLでデバイスを起動し、オンラインになるまで待機します。"""
    await interaction.response.defer()
    try:
        if ping_host(SSH_HOST):
            await interaction.followup.send(f":information_source: デバイスは既にオンラインです。")
            return

        send_magic_packet(TARGET_MAC, ip_address=BROADCAST_IP)
        await interaction.followup.send(f":electric_plug: 起動信号を送信しました。デバイスがオンラインになるまで待機します... (最大{PING_TIMEOUT}秒)")

        start_time = time.time()
        while time.time() - start_time < PING_TIMEOUT:
            if ping_host(SSH_HOST):
                embed = discord.Embed(title=":white_check_mark: 起動成功", description="**ミニPC**がオンラインになりました。", color=0x00ff00)
                await interaction.edit_original_response(content=None, embed=embed)
                return
            await asyncio.sleep(5)

        embed = discord.Embed(title=":warning: 起動タイムアウト", description=f"{PING_TIMEOUT}秒以内に `{SSH_HOST}` がオンラインになりませんでした。", color=0xffcc00)
        await interaction.edit_original_response(content=None, embed=embed)

    except Exception as e:
        embed = discord.Embed(title=":x: エラー発生", description=str(e), color=0xff0000)
        if interaction.response.is_done():
            await interaction.edit_original_response(content=None, embed=embed)
        else:
            await interaction.followup.send(embed=embed)


@tree.command(name="off", description="デバイスをシャットダウンします")
async def on_power_off(interaction: discord.Interaction):
    """SSH経由でデバイスをシャットダウンし、オフラインになるまで待機します。"""
    await interaction.response.defer()
    try:
        if not ping_host(SSH_HOST):
            await interaction.followup.send(f":information_source: デバイスは既にオフラインです。")
            return

        await execute_remote_command_async("sudo poweroff")  # 非同期版を使用
        await interaction.followup.send(f":octagonal_sign: シャットダウンコマンドを送信しました。デバイスがオフラインになるまで待機します... (最大{PING_TIMEOUT}秒)")

        start_time = time.time()
        while time.time() - start_time < PING_TIMEOUT:
            if not ping_host(SSH_HOST):
                embed = discord.Embed(title=":white_check_mark: シャットダウン成功", description="**ミニPC**がオフラインになりました。", color=0xff0000)
                await interaction.edit_original_response(content=None, embed=embed)
                return
            await asyncio.sleep(5)

        embed = discord.Embed(title=":warning: シャットダウンタイムアウト", description=f"{PING_TIMEOUT}秒以内に `{SSH_HOST}` がオフラインになりませんでした。", color=0xffcc00)
        await interaction.edit_original_response(content=None, embed=embed)

    except Exception as e:
        embed = discord.Embed(title=":x: エラー発生", description=str(e), color=0xff0000)
        if interaction.response.is_done():
            await interaction.edit_original_response(content=None, embed=embed)
        else:
            await interaction.followup.send(embed=embed)

@tree.command(name="reboot", description="デバイスを再起動します")
async def on_reboot(interaction: discord.Interaction):
    """SSH経由でデバイスを再起動し、オンラインになるまで待機します。"""
    await interaction.response.defer()
    try:
        if not ping_host(SSH_HOST):
            await interaction.followup.send(f":information_source: デバイスはオフラインです。再起動できません。")
            return

        await execute_remote_command_async("sudo reboot")  # 非同期版を使用
        await interaction.followup.send(f":arrows_counterclockwise: 再起動コマンドを送信しました。デバイスが再起動するまで待機します... (最大{PING_TIMEOUT}秒)")

        start_time = time.time()
        while time.time() - start_time < PING_TIMEOUT:
            if ping_host(SSH_HOST):
                embed = discord.Embed(title=":white_check_mark: 再起動成功", description=f"`{SSH_HOST}` がオンラインになりました。", color=0x00ff00)
                await interaction.edit_original_response(content=None, embed=embed)
                return
            await asyncio.sleep(5)

        embed = discord.Embed(title=":warning: 再起動タイムアウト", description=f"{PING_TIMEOUT}秒以内に `{SSH_HOST}` がオンラインになりませんでした。", color=0xffcc00)
        await interaction.edit_original_response(content=None, embed=embed)

    except Exception as e:
        embed = discord.Embed(title=":x: エラー発生", description=str(e), color=0xff0000)
        if interaction.response.is_done():
            await interaction.edit_original_response(content=None, embed=embed)
        else:
            await interaction.followup.send(embed=embed)

@tree.command(name="status", description="デバイスのオンライン状態を確認します")
async def on_status(interaction: discord.Interaction):
    """pingでデバイスのオンライン状態を確認します。"""
    await interaction.response.defer()
    if ping_host(SSH_HOST):
        embed = discord.Embed(title=":green_circle: オンライン", description=f"`{SSH_HOST}` は現在オンラインです。", color=0x00ff00)
    else:
        embed = discord.Embed(title=":red_circle: オフライン", description=f"`{SSH_HOST}` は現在オフラインです。", color=0xff0000)
    await interaction.followup.send(embed=embed)

@tree.command(name="stats", description="サーバーのリソース使用状況を表示")
async def on_stats(interaction: discord.Interaction):
    """CPU、メモリ、ディスク使用量を表示"""
    await interaction.response.defer()

    try:
        cpu_cmd = "top -bn1 | grep '%Cpu' | awk '{print 100 - $8}'"
        memory_cmd = "free -b | awk 'NR==2 { printf \"%.1f %.1f\", $3/1024/1024/1024, $2/1024/1024/1024 }'"
        disk_cmd = "df -B1 / | awk 'NR==2 { printf \"%.1f %.1f\", $3/1024/1024/1024, $2/1024/1024/1024 }'"
        uptime_cmd = "uptime -p"

        cpu_usage = await execute_remote_command_async(cpu_cmd)
        mem_used, mem_total = map(float, (await execute_remote_command_async(memory_cmd)).strip().split())
        disk_used, disk_total = map(float, (await execute_remote_command_async(disk_cmd)).strip().split())
        uptime_raw = await execute_remote_command_async(uptime_cmd)

        uptime_jp = (
            uptime_raw.replace("up ", "")
            .replace(" hours", "時間")
            .replace(" hour", "時間")
            .replace(" minutes", "分")
            .replace(" minute", "分")
            .replace(", ", "")
        )

        embed = discord.Embed(title=":chart_with_upwards_trend: システム状況", color=0x00ff00)
        embed.add_field(name="CPU使用率", value=f"{float(cpu_usage):.1f}%", inline=True)
        embed.add_field(
            name="メモリ使用量",
            value=f"{mem_used:.1f} GB / {mem_total:.1f} GB ({mem_used*100/mem_total:.1f}%)",
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        embed.add_field(
            name="ディスク使用量",
            value=f"{disk_used:.1f} GB / {disk_total:.1f} GB ({disk_used*100/disk_total:.1f}%)",
            inline=True,
        )
        embed.add_field(name="稼働時間", value=f"{uptime_jp}", inline=True)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"エラー: {str(e)}")


try:
  client.run(DISCORD_TOKEN)
except:
  os.system("kill 1")
