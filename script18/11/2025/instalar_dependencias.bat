@echo off
echo Ativando o ambiente virtual...
call venv\Scripts\activate

echo Instalando dependências do projeto...
pip install -r requirements.txt

echo Instalando dependências do TTS...
cd TTS
pip install -r requirements.txt
pip install -e .
cd ..

echo Dependências instaladas!
pause