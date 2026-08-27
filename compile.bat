python -m PyInstaller --onefile --windowed --noconsole --noupx --icon=hd2_icon.ico --name "hd2_custom_clan_rpc" --hidden-import=psutil --hidden-import=pystray --hidden-import=PIL --hidden-import=PIL.Image --hidden-import=PIL.ImageDraw hd2_rpc.py
pause
