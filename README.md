# MamePower Bot

Discord 経由でサーバーの管理と電源制御を行う Python ベースのボットシステムです。

## 概要

まめぱわ～は、以下の機能を提供します：

- Discord SlashCommands によるサーバー管理
- Wake-on-LAN（WoL）によるデバイス起動
- SSH 経由でのリモートサーバー制御
- LinuxGSM サーバーの操作
- システムリソース監視

## 機能

### 電源管理

- `/on` - Wake-on-LAN でデバイスを起動
- `/off` - SSH 経由でデバイスをシャットダウン
- `/reboot` - デバイスを再起動
- `/status` - デバイスのオンライン状態を確認

### サーバー管理

- `/start <server>` - サーバーを起動
- `/stop <server>` - サーバーを停止
- `/gsm <server> <action>` - LinuxGSM コマンドを実行

### システム監視

- `/stats` - CPU、メモリ、ディスク使用量を表示

## 対応サーバー

[servers.json](servers.json)で定義されたサーバー：

- Palworld
- FTB NeoTech
- FTB OceanBlock
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
SSH_HOST=your_server_ip_here
SSH_PORT=your_ssh_port_here
SSH_USER=your_ssh_username_here
TARGET_MAC=your_target_mac_here
BROADCAST_IP=your_broadcast_ip_here
```

| 変数名        | 説明                                       |
| ------------- | ------------------------------------------ |
| DISCORD_TOKEN | Discord Bot のトークン                     |
| SSH_HOST      | SSH 接続先のサーバー IP アドレス           |
| SSH_PORT      | SSH 接続ポート（通常は 22）                |
| SSH_USER      | SSH 接続ユーザー名                         |
| TARGET_MAC    | Wake-on-LAN 対象デバイスの MAC アドレス    |
| BROADCAST_IP  | Wake-on-LAN のブロードキャスト IP アドレス |

### 3. サーバー設定

[servers.json](servers.json)でサーバー設定を編集：

```json
[
  {
    "name": "サーバー名",
    "id": "サーバーID",
    "gsm": true/false,
    "info": {
      "port": ポート番号,
      "password": "パスワード"
    }
  }
]
```

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
- SSH 接続権限（sudo 権限推奨）
- Wake-on-LAN 対応ネットワーク環境

## 技術スタック

- Python 3.x
- discord.py - Discord API
- paramiko - SSH 接続
- wakeonlan - Wake-on-LAN 機能
- python-dotenv - 環境変数管理

## 注意事項

- SSH 接続には公開鍵認証の使用が必須です
- Wake-on-LAN 機能はネットワーク設定とハードウェア対応が必要です
- `.env`ファイルの誤コミットに気を付けて！
