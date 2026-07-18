# MamePower Bot

Discord 経由でゲームサーバーを管理する Python ベースのボットシステムです。
常時起動PC上で動作し、ローカルで直接サーバーを制御します。

## 概要

まめぱわ～は、以下の機能を提供します：

- Discord SlashCommands によるサーバー管理
- ローカルでの LinuxGSM サーバー操作
- `/off` / `/reboot` によるデバイスのシャットダウン・再起動
- システムリソース監視（CPU/メモリ/ディスク）

## 機能

### 電源管理

- `/on` - 常時起動モードのため常にオンライン（WoL 不要）
- `/off` - デバイスをシャットダウン
- `/reboot` - デバイスを再起動
- `/status` - デバイスのオンライン状態を確認

### サーバー管理

- `/start <server>` - サーバーを起動
- `/stop <server>` - サーバーを停止（`shutdown=True` で停止後にPCシャットダウンも可能）
- `/gsm <server> <action>` - LinuxGSM コマンドを実行（start/stop/restart/details など）

### システム監視

- `/stats` - CPU、メモリ、ディスク使用量を表示

## 対応サーバー

[servers.json](servers.json)で定義されたサーバー：

- Palworld
- FTB NeoTech
- FTB OceanBlock
- FTB Infinity Evolved
- Minecraft Vanilla Latest
- Terraria

※サーバーの追加は`servers.json`に設定を追加することで可能です。

## セットアップ

### 1. 依存関係のインストール

```bash
bash setup.sh
```

### 2. 環境変数の設定

[example.env](example.env)を参考に`.env`ファイルを作成：

```bash
cp example.env .env
```

`.env`ファイルを編集して、以下の環境変数を設定します：

```env
DISCORD_TOKEN=your_discord_token_here
PUBLIC_HOSTNAME=your_public_hostname_here (optional)
```

| 変数名          | 説明                                   | 必須 |
| --------------- | -------------------------------------- | ---- |
| DISCORD_TOKEN   | Discord Bot のトークン                 | はい |
| PUBLIC_HOSTNAME | 公開ホスト名（/start 時の接続先表示用） | いいえ |

### 3. サーバー設定

[servers.json](servers.json)でサーバー設定を編集：

```json
[
  {
    "name": "サーバー名",
    "id": "サーバーID",
    "gsm": true,
    "info": {
      "port": ポート番号,
      "password": "パスワード"
    }
  }
]
```

- `gsm: true` → LinuxGSM スクリプト `/home/mame/games/<id>/gs` を使用
- `gsm: false` → `command` フィールドでカスタム起動/停止コマンドを指定

## 実行方法

### 手動実行

```bash
python main.py
```

### スクリプト実行

```bash
bash start.sh
```

### systemd サービスとして実行

1. [mamepower.service](mamepower.service)を自分の環境に合わせて編集

   - `WorkingDirectory` をプロジェクトのパスに変更
   - `ExecStart` を `start.sh` のパスに変更
   - `EnvironmentFile` を `.env` ファイルのパスに変更
   - `User` を実行ユーザーに合わせて変更

2. [mamepower.service](mamepower.service)を systemd ディレクトリにコピー
3. サービスを有効化：

```bash
sudo cp mamepower.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mamepower.service
sudo systemctl start mamepower.service
```

## ファイル構成

- [main.py](main.py) - メインのボットプログラム
- [servers.json](servers.json) - サーバー設定ファイル
- [start.sh](start.sh) - 起動スクリプト（仮想環境自動作成）
- [setup.sh](setup.sh) - 仮想環境セットアップ、依存関係インストール
- [example.env](example.env) - 環境変数のサンプル
- [mamepower.service](mamepower.service) - systemd サービス設定
- [requirements.txt](requirements.txt) - Python 依存関係

## 必要な権限

- Discord Bot Token（Application Commands 権限必要）
- ゲームサーバーの実行スクリプト（`/home/mame/games/<id>/gs`）へのアクセス権限
- シャットダウン/再起動機能を使用する場合は sudo 権限（`poweroff` / `reboot`）

## 技術スタック

- Python 3.x
- discord.py - Discord API
- python-dotenv - 環境変数管理
- LinuxGSM - ゲームサーバー管理（サーバー側）

## 注意事項

- ボットは常時起動PC上でローカル実行する前提です（SSH 接続不要）
- LinuxGSM の tmuxception を防ぐため、ボットは `TMUX` 環境変数を除去してコマンドを実行します
- `/off` `/reboot` はローカル実行のため、コマンド発行後にボットプロセスも終了します
- `.env`ファイルの誤コミットに気を付けて！
