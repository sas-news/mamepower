#!/bin/bash

VENV_DIR="./venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "仮想環境を作成しています..."
  python3 -m venv "$VENV_DIR"
fi
echo "仮想環境を有効化しています..."
source "$VENV_DIR/bin/activate"

echo "必要な依存関係をインストールしています..."
pip install -r requirements.txt
