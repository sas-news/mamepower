@echo off

set VENV_DIR=venv

if not exist %VENV_DIR% (
    echo 仮想環境を作成しています...
    python -m venv %VENV_DIR%
)

echo 仮想環境を有効化しています...
call %VENV_DIR%\Scripts\activate.bat

echo 必要な依存関係をインストールしています...
pip install -r requirements.txt
