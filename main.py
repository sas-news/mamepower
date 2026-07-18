import os
import platform
import subprocess
import re
import json
import discord
from discord import app_commands as cmd
from discord.ext import tasks
import time
import asyncio
from dataclasses import dataclass, field
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

# ==============================================================================
# 設定と定数
# ==============================================================================

load_dotenv()

@dataclass
class Config:
    """環境変数から読み込む設定値"""
    discord_token: str = os.getenv("DISCORD_TOKEN")
    ssh_host: str = os.getenv("SSH_HOST")
    ssh_port: int = int(os.getenv("SSH_PORT", 22))
    ssh_user: str = os.getenv("SSH_USER")
    target_mac: str = os.getenv("TARGET_MAC")
    broadcast_ip: str = os.getenv("BROADCAST_IP")
    ping_timeout: int = 120
    ssh_ready_timeout: int = int(os.getenv("SSH_READY_TIMEOUT", 90))
    global_ip: str = field(init=False)

    def __post_init__(self):
        public_hostname = os.getenv("PUBLIC_HOSTNAME")
        if public_hostname:
            self.global_ip = public_hostname
        else:
            try:
                self.global_ip = subprocess.run(["curl", "-s", "https://api.ipify.org"], capture_output=True, text=True, check=True).stdout.strip()
            except (subprocess.CalledProcessError, FileNotFoundError):
                self.global_ip = "取得失敗"

@dataclass
class Constants:
    """アプリケーション内で使用する定数"""
    profiles: List[Dict[str, Any]] = field(default_factory=lambda: json.load(open("./servers.json", "r")))
    server_choices: List[cmd.Choice] = field(init=False)
    gsm_server_choices: List[cmd.Choice] = field(init=False)
    action_choices: List[cmd.Choice] = field(init=False)

    content_map: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "start": {"emoji": "white_check_mark", "msg": "起動", "color": 0x00ff00},
        "stop": {"emoji": "octagonal_sign", "msg": "停止", "color": 0xff0000},
        "gsm": {"emoji": "desktop", "msg": "コマンドを実行", "color": 0x0000ff},
    })
    
    gsm_actions: List[List[str]] = field(default_factory=lambda: [
        ["Start", "start"], ["Stop", "stop"], ["Restart", "restart"],
        ["Details", "details"], ["Post Details", "postdetails"], ["Skeleton", "skeleton"],
        ["Backup", "backup"], ["Update LinuxGSM", "update-lgsm"], ["Monitor", "monitor"],
        ["Test Alert", "test-alert"], ["Update", "update"], ["Check Update", "check-update"],
        ["Force Update", "force-update"], ["Validate", "validate"]
    ])

    def __post_init__(self):
        self.server_choices = [cmd.Choice(name=p["name"], value=p["id"]) for p in self.profiles]
        self.gsm_server_choices = [cmd.Choice(name=p["name"], value=p["id"]) for p in self.profiles if p.get("gsm")]
        self.action_choices = [cmd.Choice(name=a[0], value=a[1]) for a in self.gsm_actions]


# グローバルインスタンス
config = Config()
constants = Constants()

# グローバル変数
current_game_name: Optional[str] = None

# Discord クライアント初期化
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = cmd.CommandTree(client)

# ==============================================================================
# 定期実行タスク
# ==============================================================================
@tasks.loop(minutes=1)
async def update_presence_task():
    """定期的にデバイスの状態を確認し、プレゼンスを更新するタスク"""
    global current_game_name
    try:
        if await device_manager.is_online():
            activity = discord.Game(name=current_game_name) if current_game_name else None
            await client.change_presence(status=discord.Status.online, activity=activity)
        else:
            # オフラインになったらゲームも終了しているはず
            if current_game_name:
                current_game_name = None
            await client.change_presence(status=discord.Status.idle, activity=None)
    except Exception as e:
        print(f"プレゼンスの更新中にエラーが発生しました: {e}")

# ==============================================================================
# ユーティリティ & ヘルパークラス
# ==============================================================================

class EmbedHelper:
    """Discord Embed メッセージ生成を補助するクラス"""
    @staticmethod
    def create_embed(title: str, description: str, color: int, fields: List[Dict[str, Any]] = None) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color)
        if fields:
            for f in fields:
                embed.add_field(name=f["name"], value=f["value"], inline=f.get("inline", False))
        return embed

    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        return EmbedHelper.create_embed(f":white_check_mark: {title}", description, 0x00ff00)

    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        return EmbedHelper.create_embed(f":x: {title}", description, 0xff0000)

    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        return EmbedHelper.create_embed(f":warning: {title}", description, 0xffcc00)

    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        return EmbedHelper.create_embed(f":information_source: {title}", description, 0x0000ff)


class LocalExecutor:
    """ローカルでのコマンド実行を管理するクラス（常時起動PCでSSH不要）"""

    @staticmethod
    def _env() -> dict:
        """LinuxGSMのtmuxceptionを防ぐため TMUX を除去した環境変数を返す"""
        env = os.environ.copy()
        env.pop("TMUX", None)
        return env

    async def execute(self, command: str) -> str:
        """ローカルコマンドを実行し、標準出力を返す"""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                err = stderr.decode().strip() or f"(exit code {proc.returncode})"
                raise ConnectionError(f"コマンド実行に失敗しました: {err}")
            return stdout.decode().strip()
        except asyncio.TimeoutError:
            raise ConnectionError("コマンドがタイムアウトしました")

    async def check_path(self, path: str) -> bool:
        """パスが存在するか確認"""
        return os.path.exists(path)

executor = LocalExecutor()


class DeviceManager:
    """常時起動PCでのローカル状態管理（WoL・リモートping不要）"""
    def __init__(self, host: str, mac: str, broadcast_ip: str, ping_timeout: int):
        self.host = host
        self.mac = mac
        self.broadcast_ip = broadcast_ip
        self.ping_timeout = ping_timeout

    async def is_online(self) -> bool:
        """常時起動のため常にオンラインを返す"""
        return True

    async def wait_for_online(self, interval: int = 5) -> bool:
        """常時起動のため即座にTrueを返す"""
        return True

    async def wait_for_offline(self, interval: int = 5) -> bool:
        """ローカルホストへのpingでオフラインになるまで待機（シャットダウン/再起動用）"""
        start_time = time.time()
        while time.time() - start_time < self.ping_timeout:
            param = "-n" if platform.system() == "Windows" else "-c"
            command = ["ping", param, "1", "-W", "1", "127.0.0.1"]
            try:
                proc = await asyncio.create_subprocess_exec(*command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                await asyncio.wait_for(proc.wait(), timeout=2.0)
                if proc.returncode != 0:
                    return True  # ping失敗 = オフライン
            except (FileNotFoundError, asyncio.TimeoutError):
                return True
            await asyncio.sleep(interval)
        return False

    async def wait_for_ssh_ready(self, timeout: int, path_to_check: Optional[str] = None) -> bool:
        """指定パスが存在すれば即座にTrueを返す（SSH不要）"""
        if path_to_check:
            return os.path.exists(path_to_check)
        return True

device_manager = DeviceManager(config.ssh_host, config.target_mac, config.broadcast_ip, config.ping_timeout)

# ==============================================================================
# Discord イベントハンドラ & コマンド
# ==============================================================================

@client.event
async def on_ready():
    """ボット起動時の処理"""
    await client.change_presence(status=discord.Status.idle)
    await tree.sync()
    update_presence_task.start()
    print(f"{client.user} としてログインしました。")

async def handle_interaction_error(interaction: discord.Interaction, e: Exception):
    """コマンド実行中のエラーを処理し、Embedを送信"""
    embed = EmbedHelper.error("エラー発生", str(e))
    try:
        if interaction.response.is_done():
            # defer() 後の followup.send() でメッセージを送信済みの場合は編集、そうでなければ新規送信
            await interaction.edit_original_response(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)
    except (discord.errors.NotFound, discord.errors.InteractionResponded):
        # フォローアップメッセージでエラーを送信しようとする
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.errors.HTTPException:
             print(f"インタラクションへの応答に失敗しました: {e}")


async def manage_server(interaction: discord.Interaction, server_id: str, action: str):
    """ゲームサーバーの start/stop などを共通処理"""
    global current_game_name
    await interaction.response.defer()
    
    profile = next((p for p in constants.profiles if p["id"] == server_id), None)
    if not profile:
        await interaction.followup.send(embed=EmbedHelper.error("サーバー未定義", f"ID `{server_id}` のサーバーが見つかりません。"))
        return

    try:
        content_initial = constants.content_map[action]
        server_message = await interaction.followup.send(embed=EmbedHelper.info(f"{profile['name']}を{content_initial['msg']}中...", f"{profile['name']}の{content_initial['msg']}処理を開始します。"))

        if action == "start":
            game_script_path = f"/home/mame/games/{server_id}/gs" if profile.get("gsm") else None
            if profile.get("gsm"):
                await server_message.edit(embed=EmbedHelper.info("確認中...", "ゲームスクリプトの存在を確認しています..."))
                if not await device_manager.wait_for_ssh_ready(config.ssh_ready_timeout, game_script_path):
                    desc = f"ゲームスクリプト `{game_script_path}` が見つかりませんでした。\nサーバーがセットアップされているか確認してください。"
                    await server_message.edit(embed=EmbedHelper.warning("スクリプトが見つかりません", desc))
                    return

        command = f"/home/mame/games/{server_id}/gs {action}" if profile.get("gsm") else profile["command"][action]
        await executor.execute(command)

        content = constants.content_map[action]
        embed = EmbedHelper.create_embed(
            title=f":{content['emoji']}: {profile['name']}を{content['msg']}しました",
            description=f"{profile['name']}が{content['msg']}しました",
            color=content['color']
        )

        if action == "start":
            base_address = profile["info"].get("hostname") or config.global_ip
            port = profile["info"].get("port")
            address = f"{base_address}:{port}" if port else base_address
            embed.add_field(name="アドレス", value=address, inline=False)
            if "password" in profile["info"]:
                embed.add_field(name="パスワード", value=profile["info"]["password"], inline=False)
            current_game_name = profile["name"]
            await client.change_presence(activity=discord.Game(name=current_game_name))
        else:
            current_game_name = None
            await client.change_presence(activity=None)
        
        await server_message.edit(embed=embed)

    except Exception as e:
        await handle_interaction_error(interaction, e)


@tree.command(name="start", description="サーバーを起動します")
@cmd.describe(server="起動するサーバーを選んでください")
@cmd.choices(server=constants.server_choices)
async def on_start(interaction: discord.Interaction, server: str):
    await manage_server(interaction, server, "start")

@tree.command(name="stop", description="サーバーを停止します")
@cmd.describe(server="停止するサーバーを選んでください", shutdown="停止後にPCをシャットダウンしますか？ (既定: しない)")
@cmd.choices(server=constants.server_choices)
async def on_stop(interaction: discord.Interaction, server: str, shutdown: bool = False):
    await interaction.response.defer()
    
    profile = next((p for p in constants.profiles if p["id"] == server), None)
    if not profile:
        await interaction.followup.send(embed=EmbedHelper.error("サーバー未定義", f"ID `{server}` のサーバーが見つかりません。"))
        return

    server_message = await interaction.followup.send(embed=EmbedHelper.info(f"{profile['name']}を停止中...", f"{profile['name']}の停止処理を開始します。"))

    try:
        command = f"/home/mame/games/{server}/gs stop" if profile.get("gsm") else profile["command"]["stop"]
        await executor.execute(command)

        content = constants.content_map["stop"]
        embed = EmbedHelper.create_embed(
            title=f":{content['emoji']}: {profile['name']}を{content['msg']}しました",
            description=f"{profile['name']}が{content['msg']}しました",
            color=content['color']
        )
        await client.change_presence(activity=None)
        await server_message.edit(embed=embed)

        if shutdown:
            await asyncio.sleep(5)
            if not await device_manager.is_online():
                return

            pc_message = await interaction.followup.send(embed=EmbedHelper.info("シャットダウン中...", "サーバー停止完了。シャットダウンを開始します..."))
            
            await executor.execute("sudo poweroff")

            if await device_manager.wait_for_offline():
                embed = EmbedHelper.success("シャットダウン成功", "*`MAME G.S.`*がオフラインになりました。")
                await client.change_presence(status=discord.Status.idle)
            else:
                embed = EmbedHelper.warning("シャットダウンタイムアウト", f"{config.ping_timeout}秒以内に*`MAME G.S.`*がオフラインになりませんでした。")
            
            await pc_message.edit(embed=embed)

    except Exception as e:
        await handle_interaction_error(interaction, e)

@tree.command(name="gsm", description="LinuxGSMサーバーを管理します")
@cmd.describe(server="操作するサーバーを選んでください", action="実行するアクションを選んでください")
@cmd.choices(server=constants.gsm_server_choices, action=constants.action_choices)
async def on_gsm(interaction: discord.Interaction, server: str, action: str):
    await interaction.response.defer()
    try:
        command = f"/home/mame/games/{server}/gs {action}"
        output = await executor.execute(command)
        true_output = re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', output)
        
        embed = EmbedHelper.create_embed(
            title=f":desktop: コマンド実行成功",
            description=f"`{server}` でコマンド `{action}` を実行しました。",
            color=constants.content_map["gsm"]["color"]
        )

        if len(true_output) > 1024:
            with open("log.txt", "w", encoding="utf-8") as f:
                f.write(true_output)
            await interaction.followup.send(embed=embed, file=discord.File("log.txt"))
            os.remove("log.txt")
        else:
            embed.add_field(name="実行結果", value=f"```{true_output or '（出力なし）'}```")
            await interaction.followup.send(embed=embed)

    except Exception as e:
        await handle_interaction_error(interaction, e)

@tree.command(name="on", description="デバイスを起動します（常時起動モードでは不要）")
async def on_power_on(interaction: discord.Interaction):
    await interaction.response.defer()
    await interaction.followup.send(embed=EmbedHelper.info("常時起動モード", "*`MAME G.S.`*は常時起動のため、すでにオンラインです。"))

@tree.command(name="off", description="デバイスをシャットダウンします")
async def on_power_off(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        if not await device_manager.is_online():
            await interaction.followup.send(embed=EmbedHelper.info("デバイスはオフラインです", "*`MAME G.S.`*は既にオフラインです。"))
            return

        message = await interaction.followup.send(embed=EmbedHelper.info("シャットダウン中...", "シャットダウンを開始します。完了までお待ちください..."))
        
        await executor.execute("sudo poweroff")

        if await device_manager.wait_for_offline():
            embed = EmbedHelper.success("シャットダウン成功", "*`MAME G.S.`*がオフラインになりました。")
            await client.change_presence(status=discord.Status.idle)
        else:
            embed = EmbedHelper.warning("シャットダウンタイムアウト", f"{config.ping_timeout}秒以内に*`MAME G.S.`*がオンラインになりませんでした。")
        
        await message.edit(embed=embed)

    except Exception as e:
        await handle_interaction_error(interaction, e)

@tree.command(name="reboot", description="デバイスを再起動します")
async def on_reboot(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        if not await device_manager.is_online():
            await interaction.followup.send(embed=EmbedHelper.info("デバイスはオフラインです", "オフラインのため再起動できません。"))
            return

        message = await interaction.followup.send(embed=EmbedHelper.info("再起動中...", "再起動コマンドを送信しました。デバイスがオンラインになるまで待機します..."))
        await executor.execute("sudo reboot")

        # オフライン->オンラインになるのを待つ
        await asyncio.sleep(10) # シャットダウンシーケンスのための待機
        await message.edit(embed=EmbedHelper.info("再起動中...", "デバイスのシャットダウンを待っています..."))
        await device_manager.wait_for_offline()

        await message.edit(embed=EmbedHelper.info("再起動中...", "デバイスの再起動を待っています..."))
        if await device_manager.wait_for_online():
            embed = EmbedHelper.success("再起動成功", "*`MAME G.S.`*がオンラインになりました。")
            await client.change_presence(status=discord.Status.online)
        else:
            embed = EmbedHelper.warning("再起動タイムアウト", f"{config.ping_timeout}秒以内に*`MAME G.S.`*がオンラインになりませんでした。")

        await message.edit(embed=embed)

    except Exception as e:
        await handle_interaction_error(interaction, e)

@tree.command(name="status", description="デバイスのオンライン状態を確認します")
async def on_status(interaction: discord.Interaction):
    await interaction.response.defer()
    if await device_manager.is_online():
        embed = EmbedHelper.create_embed(":green_circle: オンライン", "*`MAME G.S.`*は現在オンラインです。", 0x00ff00)
    else:
        embed = EmbedHelper.create_embed(":red_circle: オフライン", "*`MAME G.S.`*は現在オフラインです。", 0xff0000)
    await interaction.followup.send(embed=embed)

@tree.command(name="stats", description="サーバーのリソース使用状況を表示します")
async def on_stats(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        if not await device_manager.is_online():
            await interaction.followup.send(embed=EmbedHelper.info("デバイスはオフラインです", "オフラインのため情報を取得できません。"))
            return

        cmds = {
            "cpu": "top -bn1 | grep '%Cpu' | awk '{print 100 - $8}'",
            "mem": "free -b | awk 'NR==2 { printf \"%f %f\", $3, $2 }'",
            "disk": "df -B1 / | awk 'NR==2 { printf \"%f %f\", $3, $2 }'",
            "uptime": "uptime -p"
        }
        
        results = await asyncio.gather(*[executor.execute(cmd) for cmd in cmds.values()])
        cpu_usage, mem_raw, disk_raw, uptime_raw = results

        mem_used, mem_total = map(float, mem_raw.split())
        disk_used, disk_total = map(float, disk_raw.split())

        uptime_jp = (
            uptime_raw.replace("up ", "").replace(" hours", "時間").replace(" hour", "時間")
            .replace(" minutes", "分").replace(" minute", "分").replace(", ", "")
        )

        gb = 1024**3
        embed = EmbedHelper.create_embed(title=":chart_with_upwards_trend: システム状況", description="*`MAME G.S.`*の現在のリソース使用率です。", color=0x00ff00)
        embed.add_field(name="CPU使用率", value=f"{float(cpu_usage):.1f}%", inline=True)
        embed.add_field(name="メモリ使用量", value=f"{mem_used/gb:.1f} GB / {mem_total/gb:.1f} GB ({mem_used*100/mem_total:.1f}%)", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True) # Spacer
        embed.add_field(name="ディスク使用量", value=f"{disk_used/gb:.1f} GB / {disk_total/gb:.1f} GB ({disk_used*100/disk_total:.1f}%)", inline=True)
        embed.add_field(name="稼働時間", value=uptime_jp.strip(), inline=True)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await handle_interaction_error(interaction, e)

def main():
    """メインループ"""
    if not config.discord_token:
        print("エラー: DISCORD_TOKENが設定されていません。")
        return
    try:
        client.run(config.discord_token)
    except (discord.errors.LoginFailure, discord.errors.HTTPException) as e:
        print(f"Discordへのログインに失敗しました: {e}")
    except KeyboardInterrupt:
        print("ボットを終了します。")
    finally:
        if not client.is_closed():
            asyncio.run(client.close())

if __name__ == "__main__":
    main()
