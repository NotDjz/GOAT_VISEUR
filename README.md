# Viseur — Crosshair Overlay

## Utilisation
Lancer `Viseur.exe` — le viseur apparaît au centre de l'écran.
Clic droit sur l'icône dans le system tray pour les options.

## Raccourcis
| Raccourci | Action |
|-----------|--------|
| `Mod+S` | Ouvrir/fermer les paramètres |
| `Mod+H` | Masquer/afficher le viseur |
| `Mod+1-0` | Changer de preset (1-10) |
| `Mod+Q` | Quitter |

`Mod` est le modificateur, `Ctrl+Alt` par défaut. Il se change dans les paramètres
(`Ctrl+Alt`, `Ctrl+Shift`, `Alt+Shift` ou `Ctrl+Alt+Shift`) si l'un de ces raccourcis
entre en conflit avec un jeu, et le choix est conservé dans `config.json`.

## Recompiler (optionnel)
Nécessite Python 3 + `py -m pip install -r requirements.txt`
1. `py generate_icon.py`
2. `build.bat`
3. L'exe est dans `dist\Viseur.exe`
